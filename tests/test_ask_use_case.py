"""Use-case tests using the in-memory fakes from conftest.py.

The real SqlGlotGuard is used (no fake) because it has no external
dependencies — this exercises the actual safety boundary in the pipeline.
"""

from __future__ import annotations

import pytest

from src.application.use_cases.ask_question import AskQuestionUseCase
from src.domain.entities import QueryResult
from src.domain.exceptions import LLMUnavailableError, QueryExecutionError, UnsafeSqlError
from src.infrastructure.sql.guard import SqlGlotGuard
from tests.conftest import FakeSchemaProvider, FakeSqlExecutor, FakeSqlGenerator


def _use_case(
    schema, *, generator, executor, default_max_rows=100, max_rows_limit=1000
) -> AskQuestionUseCase:
    return AskQuestionUseCase(
        schema_provider=FakeSchemaProvider(schema),
        sql_generator=generator,
        sql_guard=SqlGlotGuard(),
        sql_executor=executor,
        default_max_rows=default_max_rows,
        max_rows_limit=max_rows_limit,
    )


async def test_happy_path_returns_outcome_with_executed_sql(sample_schema) -> None:
    generator = FakeSqlGenerator(sql="SELECT name FROM countries")
    executor = FakeSqlExecutor()
    uc = _use_case(sample_schema, generator=generator, executor=executor)

    outcome = await uc.execute("list countries")

    # The guard injected a LIMIT, and the outcome reports the SQL actually run.
    assert "LIMIT 100" in outcome.generated_sql.sql.upper()
    assert outcome.generated_sql.sql == executor.executed_sql
    assert outcome.result.row_count == 1


async def test_llm_failure_propagates(sample_schema) -> None:
    generator = FakeSqlGenerator(error=LLMUnavailableError("LLM down"))
    executor = FakeSqlExecutor()
    uc = _use_case(sample_schema, generator=generator, executor=executor)

    with pytest.raises(LLMUnavailableError):
        await uc.execute("list countries")
    # The pipeline stopped before touching the database.
    assert executor.executed_sql is None


async def test_db_failure_propagates(sample_schema) -> None:
    generator = FakeSqlGenerator(sql="SELECT name FROM countries")
    executor = FakeSqlExecutor(error=QueryExecutionError("boom"))
    uc = _use_case(sample_schema, generator=generator, executor=executor)

    with pytest.raises(QueryExecutionError):
        await uc.execute("list countries")


async def test_unsafe_sql_rejected_before_executor(sample_schema) -> None:
    generator = FakeSqlGenerator(sql="DROP TABLE countries")
    executor = FakeSqlExecutor()
    uc = _use_case(sample_schema, generator=generator, executor=executor)

    with pytest.raises(UnsafeSqlError):
        await uc.execute("delete everything")
    # The guard rejected it; the executor was never reached.
    assert executor.executed_sql is None


async def test_truncation_produces_warning(sample_schema) -> None:
    generator = FakeSqlGenerator(sql="SELECT name FROM countries")
    truncated_result = QueryResult(("name",), (("a",),), 1, truncated=True)
    executor = FakeSqlExecutor(result=truncated_result)
    uc = _use_case(sample_schema, generator=generator, executor=executor)

    outcome = await uc.execute("list countries")

    assert outcome.result.truncated is True
    assert outcome.warnings


async def test_max_rows_clamped_to_server_limit(sample_schema) -> None:
    generator = FakeSqlGenerator(sql="SELECT name FROM countries")
    executor = FakeSqlExecutor()
    uc = _use_case(
        sample_schema, generator=generator, executor=executor, max_rows_limit=500
    )

    # Caller asks for far more than the absolute ceiling.
    outcome = await uc.execute("list countries", max_rows=10_000)

    # The injected LIMIT is the server ceiling, not the requested value.
    assert "LIMIT 500" in outcome.generated_sql.sql.upper()


async def test_retries_once_when_first_sql_is_unsafe(sample_schema) -> None:
    generator = FakeSqlGenerator(
        sql_sequence=["DROP TABLE countries", "SELECT name FROM countries"]
    )
    executor = FakeSqlExecutor()
    uc = _use_case(sample_schema, generator=generator, executor=executor)

    outcome = await uc.execute("list countries")

    assert generator.calls == 2
    assert "SELECT" in outcome.generated_sql.sql.upper()
    assert "LIMIT 100" in outcome.generated_sql.sql.upper()
    assert executor.executed_sql == outcome.generated_sql.sql
