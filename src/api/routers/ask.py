"""POST /api/v1/ask — the one endpoint that matters.

Thin: validate input, call the use case, map the outcome to AskResponse. All
error handling is centralized in app/api/errors.py, so this stays clean and
never try/excepts domain failures itself.

Fully implemented.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from src.api.deps import get_use_case
from src.api.schemas import AskRequest, AskResponse, ErrorResponse
from src.application.use_cases.ask_question import AskQuestionUseCase

router = APIRouter(prefix="/api/v1", tags=["ask"])


@router.post(
    "/ask",
    response_model=AskResponse,
    responses={
        422: {"model": ErrorResponse, "description": "Unsafe SQL or query failed"},
        502: {"model": ErrorResponse, "description": "LLM returned an unusable response"},
        503: {"model": ErrorResponse, "description": "LLM or database unavailable"},
        504: {"model": ErrorResponse, "description": "Query timed out"},
    },
    summary="Ask a question about the data in natural language",
)
async def ask(
    payload: AskRequest,
    use_case: AskQuestionUseCase = Depends(get_use_case),  # noqa: B008
) -> AskResponse:
    outcome = await use_case.execute(payload.question, max_rows=payload.max_rows)
    return AskResponse.from_outcome(outcome)
