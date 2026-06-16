"""Schema introspection (implements the `SchemaProvider` port).

Reads table/column/PK/FK metadata from the PostgreSQL catalogs and builds a
`DatabaseSchema`. The result is optionally cached (settings.cache_schema) so we
don't hit the catalog on every request.

STATUS: skeleton. The introspection query and mapping are specified below.
"""

from __future__ import annotations

from datetime import UTC, datetime

import psycopg
from psycopg_pool import AsyncConnectionPool

from src.domain.entities import ColumnSchema, DatabaseSchema, TableSchema
from src.domain.exceptions import SchemaUnavailableError
from src.infrastructure.config import Settings

# Introspection scope: only user tables in the `public` schema.
_INTROSPECTION_SQL = """
SELECT
    c.table_name,
    c.column_name,
    c.data_type,
    (c.is_nullable = 'YES')                         AS is_nullable,
    (pk.column_name IS NOT NULL)                    AS is_primary_key,
    fk.foreign_table || '.' || fk.foreign_column    AS references,
    col_description(
        (quote_ident(c.table_schema) || '.' || quote_ident(c.table_name))::regclass::oid,
        c.ordinal_position
    )                                               AS column_comment
FROM information_schema.columns c
LEFT JOIN (
    SELECT kcu.table_name, kcu.column_name
    FROM information_schema.table_constraints tc
    JOIN information_schema.key_column_usage kcu
      ON tc.constraint_name = kcu.constraint_name
    WHERE tc.constraint_type = 'PRIMARY KEY'
) pk ON pk.table_name = c.table_name AND pk.column_name = c.column_name
-- NOTE: joins FK columns by constraint_name only. Correct for single-column
-- FKs (all of them in this schema); a composite FK would need ordinal_position
-- matching to avoid a cartesian product.
LEFT JOIN (
    SELECT
        kcu.table_name,
        kcu.column_name,
        ccu.table_name  AS foreign_table,
        ccu.column_name AS foreign_column
    FROM information_schema.table_constraints tc
    JOIN information_schema.key_column_usage kcu
      ON tc.constraint_name = kcu.constraint_name
    JOIN information_schema.constraint_column_usage ccu
      ON tc.constraint_name = ccu.constraint_name
    WHERE tc.constraint_type = 'FOREIGN KEY'
) fk ON fk.table_name = c.table_name AND fk.column_name = c.column_name
WHERE c.table_schema = 'public'
ORDER BY c.table_name, c.ordinal_position;
"""


class PostgresSchemaProvider:
    def __init__(self, pool: AsyncConnectionPool, settings: Settings) -> None:
        self._pool = pool
        self._settings = settings
        self._cached: DatabaseSchema | None = None

    async def get_schema(self) -> DatabaseSchema:
        """Return the schema, using the cache when enabled.

        Implement:
          - if settings.cache_schema and self._cached is not None: return cache
          - else call self._introspect(), store in self._cached, return it
        """
        if self._settings.cache_schema and self._cached is not None:
            return self._cached
        schema = await self._introspect()
        self._cached = schema
        return schema

    async def _introspect(self) -> DatabaseSchema:
        """Run _INTROSPECTION_SQL and assemble a DatabaseSchema.

        Implement:
          - borrow a connection from the pool, execute _INTROSPECTION_SQL
          - group rows by table_name; for each, build ColumnSchema(...) in order
          - build TableSchema(name, columns=tuple(...)) per table
          - return DatabaseSchema(tables=tuple(...),
                                  captured_at=datetime.now(timezone.utc))
          - wrap ANY psycopg error in SchemaUnavailableError(detail=str(err))

        Also implement DatabaseSchema.render_for_prompt() in
        app/domain/entities.py (see its docstring) — the prompt depends on it.
        """
        try:
            async with self._pool.connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(_INTROSPECTION_SQL)
                    raw_rows = await cur.fetchall()
        except psycopg.Error as err:
            raise SchemaUnavailableError(
                "Schema introspection failed", detail=str(err)
            ) from err

        tables_cols: dict[str, list[ColumnSchema]] = {}
        for row in raw_rows:
            table_name: str = row[0]
            col = ColumnSchema(
                name=row[1],
                data_type=row[2],
                is_nullable=bool(row[3]),
                is_primary_key=bool(row[4]),
                references=row[5],
                comment=row[6] if row[6] else None,
            )
            tables_cols.setdefault(table_name, []).append(col)

        tables = tuple(
            TableSchema(name=name, columns=tuple(cols))
            for name, cols in tables_cols.items()
        )
        return DatabaseSchema(tables=tables, captured_at=datetime.now(UTC))
