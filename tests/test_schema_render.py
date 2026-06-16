"""Tests for DatabaseSchema.render_for_prompt()."""

from __future__ import annotations

from datetime import UTC, datetime

from src.domain.entities import ColumnSchema, DatabaseSchema, TableSchema


def _make_schema() -> DatabaseSchema:
    return DatabaseSchema(
        tables=(
            TableSchema(
                name="customers",
                columns=(
                    ColumnSchema("customer_id", "integer", False, is_primary_key=True),
                    ColumnSchema("full_name", "text", False),
                    ColumnSchema(
                        "country_id",
                        "integer",
                        False,
                        references="countries.country_id",
                    ),
                ),
            ),
        ),
        captured_at=datetime.now(UTC),
    )


def test_render_contains_table_name() -> None:
    rendered = _make_schema().render_for_prompt()
    assert "TABLE customers" in rendered


def test_render_marks_primary_key() -> None:
    rendered = _make_schema().render_for_prompt()
    assert "customer_id" in rendered
    assert "PK" in rendered


def test_render_marks_fk_arrow() -> None:
    rendered = _make_schema().render_for_prompt()
    assert "-> countries.country_id" in rendered


def test_render_marks_not_null() -> None:
    rendered = _make_schema().render_for_prompt()
    assert "NOT NULL" in rendered


def test_render_pk_column_does_not_repeat_not_null() -> None:
    rendered = _make_schema().render_for_prompt()
    # "customer_id integer PK" line should not also have NOT NULL
    pk_line = next(line for line in rendered.splitlines() if "customer_id" in line)
    assert "NOT NULL" not in pk_line


def test_render_multiple_tables() -> None:
    schema = DatabaseSchema(
        tables=(
            TableSchema(
                name="orders",
                columns=(ColumnSchema("order_id", "integer", False, is_primary_key=True),),
            ),
            TableSchema(
                name="items",
                columns=(ColumnSchema("item_id", "integer", False, is_primary_key=True),),
            ),
        ),
        captured_at=datetime.now(UTC),
    )
    rendered = schema.render_for_prompt()
    assert "TABLE orders" in rendered
    assert "TABLE items" in rendered
