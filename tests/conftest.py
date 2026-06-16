"""Shared fixtures and in-memory fakes for the domain ports.

Because the use case depends only on ports (Protocols), we can test the whole
pipeline with trivial fakes — no DB, no LLM, no network. This is the payoff of
the onion architecture.

Fully implemented — reuse these fakes in test_ask_use_case.py.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.domain.entities import (
    ColumnSchema,
    DatabaseSchema,
    GeneratedSql,
    QueryResult,
    TableSchema,
)


@pytest.fixture
def sample_schema() -> DatabaseSchema:
    return DatabaseSchema(
        tables=(
            TableSchema(
                name="countries",
                columns=(
                    ColumnSchema("country_id", "integer", False, is_primary_key=True),
                    ColumnSchema("name", "text", False),
                ),
            ),
        ),
        captured_at=datetime.now(UTC),
    )


class FakeSchemaProvider:
    def __init__(self, schema: DatabaseSchema) -> None:
        self._schema = schema

    async def get_schema(self) -> DatabaseSchema:
        return self._schema


class FakeSqlGenerator:
    """Returns a canned SQL string (or raises a preset exception)."""

    def __init__(
        self,
        sql: str = "SELECT 1",
        *,
        sql_sequence: list[str] | None = None,
        error: Exception | None = None,
    ) -> None:
        self._sql = sql
        self._sql_sequence = sql_sequence
        self._error = error
        self.calls = 0

    async def generate_sql(self, question: str, schema: DatabaseSchema) -> GeneratedSql:
        self.calls += 1
        if self._error:
            raise self._error
        if self._sql_sequence:
            index = min(self.calls - 1, len(self._sql_sequence) - 1)
            return GeneratedSql(sql=self._sql_sequence[index], explanation="canned")
        return GeneratedSql(sql=self._sql, explanation="canned")


class FakeSqlExecutor:
    """Returns a canned result (or raises a preset exception)."""

    def __init__(
        self, result: QueryResult | None = None, *, error: Exception | None = None
    ) -> None:
        self._result = result or QueryResult(("n",), ((1,),), 1)
        self._error = error
        self.executed_sql: str | None = None

    async def execute(self, sql: str, *, max_rows: int) -> QueryResult:
        self.executed_sql = sql
        if self._error:
            raise self._error
        return self._result
