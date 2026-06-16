"""The single use case: answer a natural-language question over the database.

Orchestration only. It depends exclusively on the domain ports and knows
nothing about HTTP, httpx, psycopg or sqlglot. This file is intentionally
fully implemented — it is the canonical description of the request pipeline:

    question
      -> SchemaProvider.get_schema()          (what tables exist)
      -> SqlGenerator.generate_sql()          (LLM writes SQL)
      -> SqlGuard.validate()                  (reject/normalize unsafe SQL)
      -> SqlExecutor.execute()                (run read-only, capped)
      -> AskOutcome                           (sql + tabular result)

Every step raises a domain exception on failure; we let those propagate to the
API layer, which renders them as clean error responses. The use case itself
never swallows errors silently and never crashes the process.
"""

from __future__ import annotations

import logging
import time

from src.domain.entities import AskOutcome
from src.domain.exceptions import UnsafeSqlError
from src.domain.ports import SchemaProvider, SqlExecutor, SqlGenerator, SqlGuard

logger = logging.getLogger(__name__)


class AskQuestionUseCase:
    def __init__(
        self,
        schema_provider: SchemaProvider,
        sql_generator: SqlGenerator,
        sql_guard: SqlGuard,
        sql_executor: SqlExecutor,
        *,
        default_max_rows: int,
        max_rows_limit: int,
        sql_generation_max_attempts: int = 2,
    ) -> None:
        self._schema_provider = schema_provider
        self._sql_generator = sql_generator
        self._sql_guard = sql_guard
        self._sql_executor = sql_executor
        self._default_max_rows = default_max_rows
        self._max_rows_limit = max_rows_limit
        self._sql_generation_max_attempts = max(1, sql_generation_max_attempts)

    @staticmethod
    def _retry_question(question: str, reason: str) -> str:
        return (
            f"{question}\n\n"
            "Previous SQL was rejected by safety checks. "
            f"Reason: {reason}. "
            "Return ONE safe PostgreSQL SELECT statement only."
        )

    async def execute(self, question: str, *, max_rows: int | None = None) -> AskOutcome:
        pipeline_start = time.perf_counter()
        # Apply the caller's cap if given, else the default, but never let it
        # exceed the absolute server ceiling — a client can't ask for "all rows".
        requested = max_rows or self._default_max_rows
        effective_max_rows = min(requested, self._max_rows_limit)

        schema_start = time.perf_counter()
        schema = await self._schema_provider.get_schema()
        schema_ms = (time.perf_counter() - schema_start) * 1000
        logger.info(
            "event=schema_loaded schema_ms=%.2f tables=%d",
            schema_ms,
            len(schema.tables),
        )
        logger.info("event=sql_generation_started question=%r", question)

        retry_question = question
        last_unsafe_error: UnsafeSqlError | None = None
        for attempt in range(1, self._sql_generation_max_attempts + 1):
            llm_start = time.perf_counter()
            generated = await self._sql_generator.generate_sql(retry_question, schema)
            llm_ms = (time.perf_counter() - llm_start) * 1000
            logger.info(
                "event=llm_sql_generated attempt=%d max_attempts=%d llm_ms=%.2f",
                attempt,
                self._sql_generation_max_attempts,
                llm_ms,
            )
            logger.info("event=llm_sql_text sql=%r", generated.sql)

            try:
                safe_sql = self._sql_guard.validate(generated.sql, max_rows=effective_max_rows)
                break
            except UnsafeSqlError as err:
                last_unsafe_error = err
                if attempt >= self._sql_generation_max_attempts:
                    raise
                logger.warning(
                    "event=sql_rejected attempt=%d max_attempts=%d reason=%r",
                    attempt,
                    self._sql_generation_max_attempts,
                    err.message,
                )
                retry_question = self._retry_question(question, err.message)
        else:
            if last_unsafe_error is not None:
                raise last_unsafe_error
            raise RuntimeError("SQL generation retry loop ended unexpectedly")

        result = await self._sql_executor.execute(safe_sql, max_rows=effective_max_rows)
        logger.info(
            "event=sql_executed rows=%d execution_ms=%.2f estimated_cost=%s estimated_plan_rows=%s",
            result.row_count,
            result.execution_ms,
            result.estimated_cost,
            result.estimated_plan_rows,
        )

        warnings: tuple[str, ...] = result.warnings
        if result.truncated:
            warnings = warnings + (f"Result truncated to {effective_max_rows} rows.",)

        pipeline_ms = (time.perf_counter() - pipeline_start) * 1000
        logger.info("event=pipeline_finished pipeline_ms=%.2f", pipeline_ms)

        # Re-wrap so the outcome reports the SQL that was actually executed
        # (post-guard, e.g. with an injected LIMIT) rather than the raw LLM text.
        executed_sql = generated.__class__(sql=safe_sql, explanation=generated.explanation)

        return AskOutcome(
            question=question,
            generated_sql=executed_sql,
            result=result,
            explanation=generated.explanation,
            warnings=warnings,
        )
