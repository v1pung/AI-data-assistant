"""Exception handlers — turn domain failures into clean HTTP responses.

This is what makes the homework's "service must not crash on LLM or DB errors"
true at the edge. Every AssistantError subclass maps to a status code and a
structured ErrorResponse body; a catch-all handler guarantees even unexpected
exceptions become a 500 JSON payload instead of a crashed worker.

Fully implemented — wired in app/main.py via register_exception_handlers(app).
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from src.api.schemas import ErrorBody, ErrorResponse
from src.domain.exceptions import (
    AssistantError,
    DatabaseError,
    LLMError,
    LLMResponseError,
    QueryCostExceededError,
    QueryTimeoutError,
    SchemaUnavailableError,
    UnsafeSqlError,
)

logger = logging.getLogger(__name__)

# Domain exception -> HTTP status code.
_STATUS_MAP: dict[type[AssistantError], int] = {
    UnsafeSqlError: 422,           # model produced something we won't run
    QueryCostExceededError: 422,   # plan is too expensive under policy
    LLMResponseError: 502,         # bad gateway: LLM gave garbage
    LLMError: 503,                 # LLM unavailable/timeout
    QueryTimeoutError: 504,        # DB query timed out
    SchemaUnavailableError: 503,   # DB not ready
    DatabaseError: 422,            # query failed (e.g. hallucinated column)
}


def _status_for(exc: AssistantError) -> int:
    # Pick the most specific matching mapping (e.g. LLMResponseError before its
    # parent LLMError) by ranking candidates on how close they are in the MRO,
    # so the result does not depend on _STATUS_MAP's insertion order.
    matches = [
        (exc_type, status)
        for exc_type, status in _STATUS_MAP.items()
        if isinstance(exc, exc_type)
    ]
    if not matches:
        return 400
    best = min(matches, key=lambda item: type(exc).mro().index(item[0]))
    return best[1]


def _payload(exc: AssistantError) -> dict[str, object]:
    return ErrorResponse(
        error=ErrorBody(code=exc.code, message=exc.message, detail=exc.detail)
    ).model_dump()


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AssistantError)
    async def _handle_assistant_error(request: Request, exc: AssistantError) -> JSONResponse:
        status = _status_for(exc)
        logger.warning("Handled %s (%s): %s", exc.code, status, exc.message)
        return JSONResponse(status_code=status, content=_payload(exc))

    @app.exception_handler(Exception)
    async def _handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        # Last line of defense: log full trace, return a generic 500. The
        # process keeps serving subsequent requests.
        logger.exception("Unexpected error")
        return JSONResponse(
            status_code=500,
            content=ErrorResponse(
                error=ErrorBody(
                    code="internal_error",
                    message="An unexpected error occurred.",
                )
            ).model_dump(),
        )
