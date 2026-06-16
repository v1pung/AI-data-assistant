"""Domain-level exceptions.

The whole point of this hierarchy is resilience: every foreseeable failure
(LLM down, model returned garbage, unsafe SQL, DB error, timeout) is expressed
as one of these exceptions. The API layer maps each to a clean HTTP response,
so the service degrades gracefully and NEVER crashes the process.

Mapping to HTTP status lives in `app/api/errors.py`. Keep these free of any
framework imports.
"""

from __future__ import annotations


class AssistantError(Exception):
    """Base class for all expected, handled failures.

    `code` is a stable machine-readable string returned in the error payload
    (e.g. "llm_unavailable"). `message` is human-readable and safe to expose.
    """

    code: str = "assistant_error"

    def __init__(self, message: str, *, detail: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail


# LLM-related failures


class LLMError(AssistantError):
    """Base for any failure talking to the LLM endpoint."""

    code = "llm_error"


class LLMUnavailableError(LLMError):
    """The LLM endpoint was unreachable, timed out, or returned 5xx."""

    code = "llm_unavailable"


class LLMResponseError(LLMError):
    """The LLM replied, but the response could not be parsed into SQL."""

    code = "llm_bad_response"


# SQL safety failures


class UnsafeSqlError(AssistantError):
    """The generated SQL violated the safety policy (non-SELECT, multi-statement,
    forbidden construct, etc.). It is rejected before ever touching the DB."""

    code = "unsafe_sql"


# Database failures


class DatabaseError(AssistantError):
    """Base for failures executing SQL against PostgreSQL."""

    code = "database_error"


class QueryExecutionError(DatabaseError):
    """The (valid, safe) SQL failed at execution time, e.g. unknown column,
    type mismatch, or a PostgreSQL error. The model may have hallucinated a
    column name. Safe to expose the DB message as `detail`."""

    code = "query_execution_failed"


class QueryTimeoutError(DatabaseError):
    """Execution exceeded the configured statement timeout."""

    code = "query_timeout"


class QueryCostExceededError(DatabaseError):
    """Execution plan exceeded configured query budget thresholds."""

    code = "query_cost_exceeded"


class SchemaUnavailableError(DatabaseError):
    """The database schema could not be introspected (DB down at startup,
    permissions, etc.)."""

    code = "schema_unavailable"
