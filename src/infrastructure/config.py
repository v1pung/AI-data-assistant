"""Application configuration via environment variables (pydantic-settings).

All tunables live here. Nothing else in the codebase reads os.environ directly.
A single `Settings` instance is created once and injected through the DI layer.

The LLM settings satisfy the homework requirement: the endpoint, model and API
key are all configurable, and any OpenAI-compatible `/v1/chat/completions`
server works (OpenAI, vLLM, LM Studio, OpenRouter, ...).
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # App settings
    app_name: str = "AI Data Assistant"
    log_level: str = "INFO"
    metrics_enabled: bool = True

    # LLM settings (OpenAI-compatible)
    # Base URL of the OpenAI-compatible API, WITHOUT the trailing /chat/completions.
    # e.g. "https://api.openai.com/v1" or "http://host.docker.internal:11434/v1"
    llm_base_url: str = Field(default="https://api.openai.com/v1")
    llm_model: str = Field(default="gpt-4o-mini")
    llm_api_key: str = Field(default="")
    llm_timeout_seconds: float = 30.0
    llm_temperature: float = 0.0
    llm_max_tokens: int = 1024
    # Number of LLM attempts when generated SQL is rejected by the guard.
    sql_generation_max_attempts: int = 2

    # Database settings
    # The service connects with a READ-ONLY role (see db/01_schema.sql).
    database_url: str = Field(
        default="postgresql://assistant_ro:assistant_ro@db:5432/analytics",
    )
    db_pool_min_size: int = 1
    db_pool_max_size: int = 5
    # Hard ceiling enforced by PostgreSQL on every query (milliseconds).
    db_statement_timeout_ms: int = 10_000
    # Preflight plan checks (EXPLAIN FORMAT JSON) before executing SQL.
    db_explain_preflight_enabled: bool = True
    db_explain_strict: bool = False
    db_explain_max_total_cost: float = 500_000.0
    db_explain_max_plan_rows: int = 5_000_000

    # Query policy
    # Default and absolute maximum number of rows returned to the caller.
    default_max_rows: int = 100
    max_rows_limit: int = 1000
    # If True, the schema is introspected once at startup and cached; otherwise
    # it is re-introspected on each request (simpler, slightly slower).
    cache_schema: bool = True
    # Additional SQL quality controls on top of safety validation.
    sql_quality_strict: bool = False
    sql_quality_max_joins: int = 6
    sql_quality_max_subqueries: int = 8
    sql_quality_disallow_select_star_with_join: bool = True


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide cached Settings instance."""
    return Settings()
