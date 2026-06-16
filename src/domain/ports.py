"""Ports — the abstract interfaces the application layer depends on.

These are the seams of the onion. The application/use-case layer talks ONLY to
these abstractions; concrete adapters live in `app/infrastructure/*` and are
injected at the edge (`app/api/deps.py`). This keeps the core independent of
httpx / psycopg / sqlglot and trivially testable with fakes.

Use `typing.Protocol` so adapters don't need to inherit anything — structural
typing keeps the layers decoupled.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from src.domain.entities import DatabaseSchema, GeneratedSql, QueryResult


@runtime_checkable
class SchemaProvider(Protocol):
    """Supplies the database schema that grounds the LLM prompt."""

    async def get_schema(self) -> DatabaseSchema:
        """Return the (possibly cached) database schema.

        Raises SchemaUnavailableError if the schema cannot be obtained.
        """
        ...


@runtime_checkable
class SqlGenerator(Protocol):
    """Turns a natural-language question + schema into a SQL statement."""

    async def generate_sql(self, question: str, schema: DatabaseSchema) -> GeneratedSql:
        """Ask the LLM for a single PostgreSQL SELECT answering `question`.

        Raises LLMUnavailableError on transport failure/timeout,
        LLMResponseError if the reply can't be parsed into SQL.
        """
        ...


@runtime_checkable
class SqlGuard(Protocol):
    """Validates and normalizes LLM-produced SQL before execution.

    This is the security boundary: it must guarantee the statement is a single
    read-only SELECT and may inject/cap a LIMIT.
    """

    def validate(self, sql: str, *, max_rows: int) -> str:
        """Return a safe, normalized SQL string ready to execute.

        Raises UnsafeSqlError if the statement is not a single read-only SELECT
        or contains a forbidden construct.
        """
        ...


@runtime_checkable
class SqlExecutor(Protocol):
    """Executes a validated read-only SQL statement against PostgreSQL."""

    async def execute(self, sql: str, *, max_rows: int) -> QueryResult:
        """Run `sql` in a read-only transaction with a statement timeout.

        Raises QueryTimeoutError on timeout, QueryExecutionError on any other
        database error. Must serialize results into JSON-safe Python values.
        """
        ...
