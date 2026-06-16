"""Prometheus metrics registry and helpers.

Infrastructure-only module: adapters and middleware can record metrics without
pulling observability dependencies into domain/application layers.
"""

from __future__ import annotations

from prometheus_client import Counter, Histogram, generate_latest

http_requests_total = Counter(
    "assistant_http_requests_total",
    "Total HTTP requests",
    labelnames=("method", "path", "status"),
)

http_request_duration_seconds = Histogram(
    "assistant_http_request_duration_seconds",
    "HTTP request latency in seconds",
    labelnames=("method", "path"),
)

llm_requests_total = Counter(
    "assistant_llm_requests_total",
    "Total LLM completion attempts",
    labelnames=("outcome",),
)

llm_latency_seconds = Histogram(
    "assistant_llm_latency_seconds",
    "LLM completion latency in seconds",
)

llm_tokens_total = Counter(
    "assistant_llm_tokens_total",
    "LLM token usage by type",
    labelnames=("kind",),
)

sql_exec_latency_seconds = Histogram(
    "assistant_sql_exec_latency_seconds",
    "SQL execution latency in seconds",
    labelnames=("outcome",),
)

sql_preflight_explain_total = Counter(
    "assistant_sql_preflight_explain_total",
    "Preflight EXPLAIN attempts",
    labelnames=("outcome",),
)

sql_cost_exceeded_total = Counter(
    "assistant_sql_cost_exceeded_total",
    "Queries that exceeded configured cost budget",
)


def render_metrics() -> bytes:
    return generate_latest()
