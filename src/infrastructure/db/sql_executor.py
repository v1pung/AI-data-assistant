"""Read-only SQL execution (implements the `SqlExecutor` port).

Runs the guard-approved SELECT inside a READ ONLY transaction with a
PostgreSQL statement timeout, then serializes the rows into JSON-safe values.

This is layer 2 of the safety model (the read-only role is layer 3): even if a
write somehow slipped past the guard, the transaction would reject it.

STATUS: skeleton. The execution recipe is specified below.
"""

from __future__ import annotations

import logging
import time
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

import psycopg
import psycopg.errors
from psycopg_pool import AsyncConnectionPool

from src.domain.entities import QueryResult
from src.domain.exceptions import QueryCostExceededError, QueryExecutionError, QueryTimeoutError
from src.infrastructure.config import Settings
from src.infrastructure.observability.metrics import (
    sql_cost_exceeded_total,
    sql_exec_latency_seconds,
    sql_preflight_explain_total,
)

logger = logging.getLogger(__name__)


def _to_jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, memoryview | bytes | bytearray):
        # Binary columns (bytea) -> hex string, so data is preserved, not dropped.
        return bytes(value).hex()
    return value


class PostgresSqlExecutor:
    def __init__(self, pool: AsyncConnectionPool, settings: Settings) -> None:
        self._pool = pool
        self._settings = settings

    async def _preflight_explain(
        self,
        cur: psycopg.AsyncCursor[Any],
        sql: str,
    ) -> tuple[float | None, int | None, tuple[str, ...]]:
        if not self._settings.db_explain_preflight_enabled:
            logger.info("event=sql_preflight_explain outcome=disabled")
            sql_preflight_explain_total.labels(outcome="disabled").inc()
            return None, None, ()

        try:
            await cur.execute(f"EXPLAIN (FORMAT JSON) {sql}")
            explain_row = await cur.fetchone()
        except psycopg.errors.QueryCanceled as err:
            logger.warning("event=sql_preflight_explain outcome=timeout")
            sql_preflight_explain_total.labels(outcome="timeout").inc()
            raise QueryTimeoutError("Query preflight explain timed out") from err
        except psycopg.Error as err:
            if self._settings.db_explain_strict:
                logger.warning(
                    "event=sql_preflight_explain outcome=error_strict detail=%r", str(err)
                )
                sql_preflight_explain_total.labels(outcome="error_strict").inc()
                raise QueryExecutionError(
                    "Query preflight explain failed", detail=str(err)
                ) from err
            logger.warning(
                "event=sql_preflight_explain outcome=error_relaxed detail=%r", str(err)
            )
            sql_preflight_explain_total.labels(outcome="error_relaxed").inc()
            return None, None, ("Could not run EXPLAIN preflight; proceeding.",)

        if not explain_row:
            if self._settings.db_explain_strict:
                logger.warning("event=sql_preflight_explain outcome=empty_plan_strict")
                sql_preflight_explain_total.labels(outcome="empty_plan_strict").inc()
                raise QueryExecutionError("Query preflight explain returned no plan")
            logger.warning("event=sql_preflight_explain outcome=empty_plan_relaxed")
            sql_preflight_explain_total.labels(outcome="empty_plan_relaxed").inc()
            return None, None, ("EXPLAIN returned no plan; proceeding.",)

        try:
            payload = explain_row[0]
            if not isinstance(payload, list) or not payload or not isinstance(payload[0], dict):
                raise TypeError("Unexpected EXPLAIN payload shape")
            root = payload[0].get("Plan")
            if not isinstance(root, dict):
                raise TypeError("EXPLAIN plan root is missing")

            raw_cost = root.get("Total Cost")
            raw_rows = root.get("Plan Rows")
            total_cost = float(raw_cost) if raw_cost is not None else None
            plan_rows = int(raw_rows) if raw_rows is not None else None
        except (KeyError, TypeError, ValueError, IndexError) as err:
            if self._settings.db_explain_strict:
                logger.warning(
                    "event=sql_preflight_explain outcome=parse_error_strict detail=%r",
                    str(err),
                )
                sql_preflight_explain_total.labels(outcome="parse_error_strict").inc()
                raise QueryExecutionError(
                    "Could not parse EXPLAIN JSON output", detail=str(err)
                ) from err
            logger.warning(
                "event=sql_preflight_explain outcome=parse_error_relaxed detail=%r",
                str(err),
            )
            sql_preflight_explain_total.labels(outcome="parse_error_relaxed").inc()
            return None, None, ("Could not parse EXPLAIN plan; proceeding.",)

        warnings: list[str] = []
        violations: list[str] = []

        if (
            total_cost is not None
            and total_cost > self._settings.db_explain_max_total_cost
        ):
            violations.append(
                f"estimated_total_cost={total_cost:.2f} exceeds "
                f"max_total_cost={self._settings.db_explain_max_total_cost:.2f}"
            )
        if (
            plan_rows is not None
            and plan_rows > self._settings.db_explain_max_plan_rows
        ):
            violations.append(
                f"estimated_plan_rows={plan_rows} exceeds "
                f"max_plan_rows={self._settings.db_explain_max_plan_rows}"
            )

        if violations:
            detail = "; ".join(violations)
            if self._settings.db_explain_strict:
                logger.warning(
                    "event=sql_preflight_explain outcome=cost_exceeded_strict detail=%r",
                    detail,
                )
                sql_preflight_explain_total.labels(outcome="cost_exceeded_strict").inc()
                sql_cost_exceeded_total.inc()
                raise QueryCostExceededError(
                    "Query exceeds configured cost budget", detail=detail
                )
            logger.warning(
                "event=sql_preflight_explain outcome=cost_exceeded_relaxed detail=%r",
                detail,
            )
            sql_preflight_explain_total.labels(outcome="cost_exceeded_relaxed").inc()
            warnings.append(f"Cost warning: {detail}")
        else:
            logger.info(
                "event=sql_preflight_explain outcome=ok estimated_cost=%s estimated_plan_rows=%s",
                total_cost,
                plan_rows,
            )
            sql_preflight_explain_total.labels(outcome="ok").inc()

        return total_cost, plan_rows, tuple(warnings)

    async def execute(self, sql: str, *, max_rows: int) -> QueryResult:
        """Execute `sql` safely and return a QueryResult.

        Implement:
          1. start = time.perf_counter()
          2. async with self._pool.connection() as conn:
                 async with conn.transaction():
                     async with conn.cursor() as cur:
                         await cur.execute(
                             "SET TRANSACTION READ ONLY")            # belt
                         await cur.execute(
                             f"SET LOCAL statement_timeout = {settings.db_statement_timeout_ms}")
                         await cur.execute(sql)
                         rows = await cur.fetchmany(max_rows + 1)    # +1 detects truncation
                         columns = tuple(d.name for d in cur.description)
          3. truncated = len(rows) > max_rows; rows = rows[:max_rows]
          4. serialize each cell via _to_jsonable (Decimal->float/str, date/
             datetime->isoformat, UUID->str, memoryview->None/str, else as-is)
          5. execution_ms = (time.perf_counter() - start) * 1000
          6. return QueryResult(columns, tuple(serialized_rows), len(rows),
                                truncated, execution_ms)

        Error mapping:
          - psycopg.errors.QueryCanceled  -> QueryTimeoutError
          - any other psycopg.Error       -> QueryExecutionError(detail=str(err))
        Never let a raw psycopg exception escape this method.
        """
        start = time.perf_counter()
        try:
            async with self._pool.connection() as conn:
                async with conn.transaction():
                    async with conn.cursor() as cur:
                        await cur.execute("SET TRANSACTION READ ONLY")
                        timeout_ms = self._settings.db_statement_timeout_ms
                        await cur.execute(
                            f"SET LOCAL statement_timeout = {timeout_ms}"
                        )
                        estimated_cost, estimated_plan_rows, preflight_warnings = (
                            await self._preflight_explain(cur, sql)
                        )
                        await cur.execute(sql)
                        raw_rows = await cur.fetchmany(max_rows + 1)
                        columns = tuple(d.name for d in cur.description) if cur.description else ()
        except psycopg.errors.QueryCanceled as err:
            logger.warning("event=sql_execution outcome=timeout")
            sql_exec_latency_seconds.labels(outcome="timeout").observe(
                time.perf_counter() - start
            )
            raise QueryTimeoutError("Query timed out") from err
        except psycopg.Error as err:
            logger.warning("event=sql_execution outcome=error detail=%r", str(err))
            sql_exec_latency_seconds.labels(outcome="error").observe(
                time.perf_counter() - start
            )
            raise QueryExecutionError("Query execution failed", detail=str(err)) from err

        truncated = len(raw_rows) > max_rows
        trimmed = raw_rows[:max_rows]

        serialized_rows = tuple(
            tuple(_to_jsonable(cell) for cell in row) for row in trimmed
        )

        execution_ms = (time.perf_counter() - start) * 1000
        logger.info(
            "event=sql_execution outcome=success rows=%d execution_ms=%.2f",
            len(serialized_rows),
            execution_ms,
        )
        sql_exec_latency_seconds.labels(outcome="success").observe(execution_ms / 1000)
        return QueryResult(
            columns=columns,
            rows=serialized_rows,
            row_count=len(serialized_rows),
            truncated=truncated,
            execution_ms=execution_ms,
            estimated_cost=estimated_cost,
            estimated_plan_rows=estimated_plan_rows,
            warnings=preflight_warnings,
        )
