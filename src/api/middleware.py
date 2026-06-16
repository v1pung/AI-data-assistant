"""Request correlation: attach a request id to every request.

Each request gets an `X-Request-ID` (reused if the client sent one). The id is
stored in a contextvar so log records and error handlers can include it, which
makes "the service answered 500, why?" traceable across log lines.
"""

from __future__ import annotations

import logging
import time
import uuid
from contextvars import ContextVar

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from src.infrastructure.observability.metrics import (
    http_request_duration_seconds,
    http_requests_total,
)

_HEADER = "x-request-id"

# Readable by anyone (e.g. the exception handlers) during a request.
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")


class RequestIdMiddleware:
    """Pure-ASGI middleware: set the request-id contextvar, echo the header."""

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        headers = dict(scope.get("headers") or [])
        incoming = headers.get(_HEADER.encode())
        request_id = incoming.decode() if incoming else uuid.uuid4().hex
        token = request_id_var.set(request_id)

        async def send_with_header(message: Message) -> None:
            if message["type"] == "http.response.start":
                raw_headers = list(message.get("headers") or [])
                raw_headers.append((_HEADER.encode(), request_id.encode()))
                message["headers"] = raw_headers
            await send(message)

        try:
            await self._app(scope, receive, send_with_header)
        finally:
            request_id_var.reset(token)


class RequestIdLogFilter(logging.Filter):
    """Inject the current request id into every log record as `%(request_id)s`."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


class MetricsMiddleware:
    """Pure-ASGI middleware for request count and latency metrics."""

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        method = scope.get("method", "UNKNOWN")
        path = scope.get("path", "unknown")
        status_code = 500
        started = time.perf_counter()

        async def send_with_metrics(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message.get("status", 500))
            await send(message)

        try:
            await self._app(scope, receive, send_with_metrics)
        finally:
            elapsed = time.perf_counter() - started
            http_requests_total.labels(
                method=method,
                path=path,
                status=str(status_code),
            ).inc()
            http_request_duration_seconds.labels(
                method=method,
                path=path,
            ).observe(elapsed)
