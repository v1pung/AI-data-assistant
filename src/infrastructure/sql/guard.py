"""SQL safety guard — the security boundary between the LLM and the database.

Defense in depth. Even though the service connects with a read-only DB role
and wraps every query in a READ ONLY transaction with a statement timeout, we
NEVER trust LLM output. This guard parses the SQL with sqlglot and rejects
anything that is not a single, read-only SELECT.

Layers of protection (this file is one of three):
  1. This guard           -> only a single SELECT/CTE passes, LIMIT is capped.
  2. READ ONLY transaction -> PostgreSQL rejects writes (see sql_executor.py).
  3. Read-only DB role      -> no write/DDL grants at all (see db/01_schema.sql).

Fully implemented: this is sensitive, so the policy is explicit here rather
than left to the implementer.
"""

from __future__ import annotations

import logging

import sqlglot
from sqlglot import exp

from src.domain.exceptions import UnsafeSqlError

# Statement types that are allowed at the top level.
_ALLOWED_STATEMENTS = (exp.Select,)

# Any of these expression types appearing anywhere in the tree -> reject.
# (DML/DDL/transaction/permission statements.)
_FORBIDDEN_NODES = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Drop,
    exp.Create,
    exp.Alter,
    exp.TruncateTable,
    exp.Command,  # catch-all for unparsed statements like GRANT, COPY, VACUUM, SET
)

logger = logging.getLogger(__name__)


class SqlGlotGuard:
    """Concrete `SqlGuard` adapter backed by sqlglot (PostgreSQL dialect)."""

    def __init__(
        self,
        *,
        quality_strict: bool = False,
        max_joins: int = 6,
        max_subqueries: int = 8,
        disallow_select_star_with_join: bool = True,
    ) -> None:
        self._dialect = "postgres"
        self._quality_strict = quality_strict
        self._max_joins = max(0, max_joins)
        self._max_subqueries = max(0, max_subqueries)
        self._disallow_select_star_with_join = disallow_select_star_with_join

    def validate(self, sql: str, *, max_rows: int) -> str:
        sql = self._strip_markdown(sql).strip().rstrip(";").strip()
        if not sql:
            raise UnsafeSqlError("Empty SQL statement.")

        try:
            statements = sqlglot.parse(sql, dialect=self._dialect)
        except Exception as err:  # sqlglot.errors.ParseError and friends
            raise UnsafeSqlError("Could not parse SQL.", detail=str(err)) from err

        statements = [s for s in statements if s is not None]
        if len(statements) != 1:
            raise UnsafeSqlError("Only a single statement is allowed.")

        statement = statements[0]

        # The root must be a SELECT (a top-level CTE `WITH ... SELECT` parses as
        # a Select whose `with` arg is set, so this also permits CTEs).
        if not isinstance(statement, _ALLOWED_STATEMENTS):
            raise UnsafeSqlError("Only read-only SELECT statements are allowed.")

        # Reject any forbidden node anywhere in the tree (e.g. a write hidden in
        # a subquery or CTE).
        for node in statement.walk():
            if isinstance(node, _FORBIDDEN_NODES):
                raise UnsafeSqlError("Statement contains a forbidden operation.")

        self._run_quality_policy(statement)

        return self._apply_limit(statement, max_rows)

    def _run_quality_policy(self, statement: exp.Select) -> None:
        joins_count = sum(1 for _ in statement.find_all(exp.Join))
        subqueries_count = sum(1 for _ in statement.find_all(exp.Subquery))
        select_star_used = any(isinstance(node, exp.Star) for node in statement.find_all(exp.Star))

        violations: list[str] = []
        if joins_count > self._max_joins:
            violations.append(
                f"joins={joins_count} exceeds max_joins={self._max_joins}"
            )
        if subqueries_count > self._max_subqueries:
            violations.append(
                f"subqueries={subqueries_count} exceeds max_subqueries={self._max_subqueries}"
            )
        if self._disallow_select_star_with_join and joins_count > 0 and select_star_used:
            violations.append("SELECT * is not allowed in JOIN queries")

        if not violations:
            return

        detail = "; ".join(violations)
        if self._quality_strict:
            raise UnsafeSqlError("SQL quality policy violation", detail=detail)
        logger.warning("SQL quality policy warning: %s", detail)

    def _apply_limit(self, statement: exp.Select, max_rows: int) -> str:
        """Cap the result size. If the query has no LIMIT, inject `max_rows`.
        If it has a larger LIMIT, lower it to `max_rows`."""
        existing = statement.args.get("limit")
        if existing is None:
            statement = statement.limit(max_rows)
        else:
            try:
                current = int(existing.expression.this)
                if current > max_rows:
                    statement = statement.limit(max_rows)
            except (AttributeError, ValueError, TypeError):
                # Non-literal LIMIT (e.g. parameter) — replace with our cap.
                statement = statement.limit(max_rows)
        return statement.sql(dialect=self._dialect)

    @staticmethod
    def _strip_markdown(sql: str) -> str:
        """Remove ```sql ... ``` fences the LLM may wrap the query in."""
        text = sql.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            # drop first fence line (``` or ```sql) and a trailing fence line
            lines = lines[1:]
            if lines and lines[-1].strip().startswith("```"):
                lines = lines[:-1]
            text = "\n".join(lines)
        return text
