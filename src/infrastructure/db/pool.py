"""Async PostgreSQL connection pool lifecycle (psycopg3).

A single AsyncConnectionPool is created at app startup and closed at shutdown
(wired in app/main.py via the lifespan handler). Adapters receive the pool and
borrow connections per query.

Fully implemented — straightforward lifecycle.
"""

from __future__ import annotations

from psycopg_pool import AsyncConnectionPool

from src.infrastructure.config import Settings


def create_pool(settings: Settings) -> AsyncConnectionPool:
    """Create (but do not open) the connection pool.

    `open=False` keeps construction side-effect free; main.py calls
    `await pool.open()` during the lifespan startup and `await pool.close()`
    on shutdown. We do NOT block app startup if the DB is briefly unavailable —
    health/readiness endpoints report DB status instead.
    """
    return AsyncConnectionPool(
        conninfo=settings.database_url,
        min_size=settings.db_pool_min_size,
        max_size=settings.db_pool_max_size,
        open=False,
        kwargs={"autocommit": True},
    )
