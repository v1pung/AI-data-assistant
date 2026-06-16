"""FastAPI application factory and composition root.

This is the ONLY place where all layers meet: settings are read, infrastructure
adapters are constructed and bound to the domain ports, the use case is
assembled, and everything is stashed on `app.state` for the request-time DI
providers in app/api/deps.py.

The lifespan handler owns the lifecycle of the two long-lived resources:
the httpx client and the psycopg connection pool.

Fully implemented.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from src.api.errors import register_exception_handlers
from src.api.middleware import MetricsMiddleware, RequestIdLogFilter, RequestIdMiddleware
from src.api.routers import ask, health, metrics
from src.application.use_cases.ask_question import AskQuestionUseCase
from src.infrastructure.config import Settings, get_settings
from src.infrastructure.db.pool import create_pool
from src.infrastructure.db.schema_provider import PostgresSchemaProvider
from src.infrastructure.db.sql_executor import PostgresSqlExecutor
from src.infrastructure.llm.openai_client import OpenAICompatibleClient
from src.infrastructure.sql.guard import SqlGlotGuard


def _configure_logging(settings: Settings) -> None:
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s %(levelname)s [%(request_id)s] %(name)s %(message)s",
    )
    # Make %(request_id)s available on every record (root + handlers).
    log_filter = RequestIdLogFilter()
    for handler in logging.getLogger().handlers:
        handler.addFilter(log_filter)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings

    # Long-lived resources.
    http_client = httpx.AsyncClient(timeout=settings.llm_timeout_seconds)
    db_pool = create_pool(settings)
    try:
        await db_pool.open()
    except Exception:  # do not block startup if DB is briefly down
        logging.getLogger(__name__).warning("DB pool failed to open at startup", exc_info=True)

    # Adapters (infrastructure) bound to domain ports.
    schema_provider = PostgresSchemaProvider(db_pool, settings)
    sql_generator = OpenAICompatibleClient(settings, http_client)
    sql_guard = SqlGlotGuard(
        quality_strict=settings.sql_quality_strict,
        max_joins=settings.sql_quality_max_joins,
        max_subqueries=settings.sql_quality_max_subqueries,
        disallow_select_star_with_join=settings.sql_quality_disallow_select_star_with_join,
    )
    sql_executor = PostgresSqlExecutor(db_pool, settings)

    # Use case (application).
    app.state.db_pool = db_pool
    app.state.http_client = http_client
    app.state.ask_use_case = AskQuestionUseCase(
        schema_provider=schema_provider,
        sql_generator=sql_generator,
        sql_guard=sql_guard,
        sql_executor=sql_executor,
        default_max_rows=settings.default_max_rows,
        max_rows_limit=settings.max_rows_limit,
        sql_generation_max_attempts=settings.sql_generation_max_attempts,
    )

    try:
        yield
    finally:
        await http_client.aclose()
        await db_pool.close()


def create_app() -> FastAPI:
    settings = get_settings()
    _configure_logging(settings)

    app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
    app.state.settings = settings

    if settings.metrics_enabled:
        app.add_middleware(MetricsMiddleware)
    app.add_middleware(RequestIdMiddleware)
    register_exception_handlers(app)
    app.include_router(health.router)
    if settings.metrics_enabled:
        app.include_router(metrics.router)
    app.include_router(ask.router)
    return app


app = create_app()
