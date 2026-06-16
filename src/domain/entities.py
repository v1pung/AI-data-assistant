"""Domain entities and value objects.

This is the innermost layer of the onion. It MUST NOT import from any other
layer (no fastapi, no httpx, no psycopg, no sqlglot). Only the Python stdlib.

These objects model the business concepts of the assistant:
  - the database schema we feed to the LLM,
  - the SQL the LLM produces,
  - the tabular result we return to the caller.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class ColumnSchema:
    """A single column of a table as seen during schema introspection."""

    name: str
    data_type: str
    is_nullable: bool
    is_primary_key: bool = False
    # If this column is a foreign key, the "table.column" it references.
    references: str | None = None
    # Free-text hint for the LLM (e.g. allowed values for enum-like columns).
    comment: str | None = None


@dataclass(frozen=True)
class TableSchema:
    """A single table (with its columns) discovered in the database."""

    name: str
    columns: tuple[ColumnSchema, ...]
    comment: str | None = None


@dataclass(frozen=True)
class DatabaseSchema:
    """The full set of tables the assistant is allowed to reason about.

    `render_for_prompt()` produces the compact, LLM-friendly textual
    description that is embedded into the system prompt. Keep it deterministic
    and stable so prompts (and therefore tests) are reproducible.
    """

    tables: tuple[TableSchema, ...]
    captured_at: datetime

    def render_for_prompt(self) -> str:
        """Render the schema as a readable pseudo-DDL string for the prompt.

        Implementation note (Sonnet): produce something like::

            TABLE customers(
              customer_id integer PK,
              full_name text NOT NULL,
              country_id integer -> countries.country_id
            )

        One table per block, columns indented, mark PK and FK relationships.
        This text is the LLM's only knowledge of the database, so be complete
        but compact (no data, just structure).
        """
        blocks: list[str] = []
        for table in self.tables:
            col_lines: list[str] = []
            for col in table.columns:
                parts = [col.name, col.data_type]
                if col.is_primary_key:
                    parts.append("PK")
                if not col.is_nullable and not col.is_primary_key:
                    parts.append("NOT NULL")
                if col.references:
                    parts.append(f"-> {col.references}")
                line = "  " + " ".join(parts)
                if col.comment:
                    line += f"  -- {col.comment}"
                col_lines.append(line)
            blocks.append(f"TABLE {table.name}(\n" + ",\n".join(col_lines) + "\n)")
        return "\n".join(blocks)


@dataclass(frozen=True)
class GeneratedSql:
    """The SQL statement produced by the LLM for a natural-language question."""

    sql: str
    # Optional natural-language rationale the model returned alongside the SQL.
    explanation: str | None = None


@dataclass(frozen=True)
class QueryResult:
    """The tabular result of executing a (validated) SQL statement."""

    columns: tuple[str, ...]
    rows: tuple[tuple[Any, ...], ...]
    row_count: int
    # True when the result was capped by the configured max-rows limit.
    truncated: bool = False
    execution_ms: float = 0.0
    # Optional diagnostics from preflight planning (EXPLAIN).
    estimated_cost: float | None = None
    estimated_plan_rows: int | None = None
    warnings: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class AskOutcome:
    """Everything the API needs to return for one successful `ask` request."""

    question: str
    generated_sql: GeneratedSql
    result: QueryResult
    explanation: str | None = None
    warnings: tuple[str, ...] = field(default_factory=tuple)
