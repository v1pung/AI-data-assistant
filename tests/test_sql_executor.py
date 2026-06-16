"""Targeted unit tests for EXPLAIN preflight behavior in PostgresSqlExecutor."""

from __future__ import annotations

from types import SimpleNamespace

import psycopg
import pytest

from src.domain.exceptions import QueryCostExceededError, QueryExecutionError
from src.infrastructure.config import Settings
from src.infrastructure.db.sql_executor import PostgresSqlExecutor


class _FakeCursor:
    def __init__(
        self,
        *,
        explain_error: Exception | None = None,
        explain_row: tuple[object, ...] | None = None,
        query_rows: list[tuple[object, ...]] | None = None,
    ) -> None:
        self._explain_error = explain_error
        self._explain_row = explain_row
        self._query_rows = query_rows or [(1,)]
        self.description = (SimpleNamespace(name="n"),)

    async def __aenter__(self) -> _FakeCursor:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def execute(self, sql: str) -> None:
        if sql.startswith("EXPLAIN") and self._explain_error is not None:
            raise self._explain_error

    async def fetchone(self) -> tuple[object, ...] | None:
        return self._explain_row

    async def fetchmany(self, size: int) -> list[tuple[object, ...]]:
        return self._query_rows[:size]


class _NullTx:
    async def __aenter__(self) -> _NullTx:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


class _FakeConn:
    def __init__(self, cursor: _FakeCursor) -> None:
        self._cursor = cursor

    async def __aenter__(self) -> _FakeConn:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    def transaction(self) -> _NullTx:
        return _NullTx()

    def cursor(self) -> _FakeCursor:
        return self._cursor


class _FakePool:
    def __init__(self, conn: _FakeConn) -> None:
        self._conn = conn

    def connection(self) -> _FakeConn:
        return self._conn


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "db_explain_preflight_enabled": True,
        "db_explain_strict": False,
        "db_explain_max_total_cost": 1000.0,
        "db_explain_max_plan_rows": 1000,
    }
    base.update(overrides)
    return Settings(**base)


@pytest.mark.asyncio
async def test_explain_strict_error_blocks_execution() -> None:
    cursor = _FakeCursor(explain_error=psycopg.OperationalError("boom"))
    executor = PostgresSqlExecutor(_FakePool(_FakeConn(cursor)), _settings(db_explain_strict=True))

    with pytest.raises(QueryExecutionError, match="preflight explain failed"):
        await executor.execute("SELECT 1", max_rows=10)


@pytest.mark.asyncio
async def test_explain_relaxed_error_adds_warning_and_continues() -> None:
    cursor = _FakeCursor(explain_error=psycopg.OperationalError("boom"), query_rows=[(1,)])
    executor = PostgresSqlExecutor(_FakePool(_FakeConn(cursor)), _settings(db_explain_strict=False))

    result = await executor.execute("SELECT 1", max_rows=10)

    assert result.row_count == 1
    assert result.warnings
    assert "EXPLAIN" in result.warnings[0]


@pytest.mark.asyncio
async def test_explain_strict_cost_exceeded_raises_domain_error() -> None:
    explain_payload = ([{"Plan": {"Total Cost": 5000.0, "Plan Rows": 10}}],)
    cursor = _FakeCursor(explain_row=explain_payload)
    executor = PostgresSqlExecutor(
        _FakePool(_FakeConn(cursor)),
        _settings(db_explain_strict=True, db_explain_max_total_cost=1000.0),
    )

    with pytest.raises(QueryCostExceededError, match="cost budget"):
        await executor.execute("SELECT 1", max_rows=10)
