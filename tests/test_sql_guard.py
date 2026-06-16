"""Tests for the SQL safety guard. Fully implemented — the guard is the
security boundary, so its behavior is pinned down here."""

from __future__ import annotations

import pytest

from src.domain.exceptions import UnsafeSqlError
from src.infrastructure.sql.guard import SqlGlotGuard

guard = SqlGlotGuard()


def test_simple_select_passes_and_gets_limit() -> None:
    out = guard.validate("SELECT 1 AS n", max_rows=100)
    assert "LIMIT 100" in out.upper()


def test_existing_smaller_limit_is_kept() -> None:
    out = guard.validate("SELECT * FROM customers LIMIT 5", max_rows=100)
    assert "LIMIT 5" in out.upper()


def test_existing_larger_limit_is_capped() -> None:
    out = guard.validate("SELECT * FROM customers LIMIT 10000", max_rows=100)
    assert "LIMIT 100" in out.upper()


def test_cte_select_is_allowed() -> None:
    sql = "WITH c AS (SELECT 1 AS n) SELECT * FROM c"
    out = guard.validate(sql, max_rows=50)
    assert "LIMIT 50" in out.upper()


def test_markdown_fences_are_stripped() -> None:
    out = guard.validate("```sql\nSELECT 1\n```", max_rows=10)
    assert out.upper().startswith("SELECT")


@pytest.mark.parametrize(
    "bad_sql",
    [
        "DELETE FROM customers",
        "UPDATE customers SET full_name = 'x'",
        "INSERT INTO customers (full_name) VALUES ('x')",
        "DROP TABLE customers",
        "TRUNCATE customers",
        "ALTER TABLE customers ADD COLUMN x int",
        "CREATE TABLE x (id int)",
        "GRANT SELECT ON customers TO public",
        "SELECT 1; DROP TABLE customers",      # multi-statement
        "SELECT 1; SELECT 2",                  # multi-statement
        "",                                    # empty
    ],
)
def test_dangerous_statements_are_rejected(bad_sql: str) -> None:
    with pytest.raises(UnsafeSqlError):
        guard.validate(bad_sql, max_rows=100)


def test_quality_policy_strict_blocks_select_star_with_join() -> None:
    strict_guard = SqlGlotGuard(quality_strict=True, max_joins=10, max_subqueries=10)
    with pytest.raises(UnsafeSqlError, match="quality policy"):
        strict_guard.validate(
            "SELECT * FROM customers c JOIN countries ctr ON ctr.country_id = c.country_id",
            max_rows=100,
        )
