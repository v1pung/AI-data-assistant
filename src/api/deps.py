"""Dependency injection wiring.

Composition root for request handling. Long-lived singletons (settings, http
client, db pool, adapters, use case) are built ONCE during the lifespan startup
in app/main.py and stashed on `app.state`. These provider functions just hand
them to routers via FastAPI's `Depends`.

Keeping construction in one place is what makes the onion swappable: to use a
different LLM or a fake DB in tests, you replace an adapter here / in main.py,
not in the use case.

Fully implemented.
"""

from __future__ import annotations

from fastapi import Request

from src.application.use_cases.ask_question import AskQuestionUseCase


def get_use_case(request: Request) -> AskQuestionUseCase:
    """Return the singleton AskQuestionUseCase built during app startup."""
    use_case: AskQuestionUseCase = request.app.state.ask_use_case
    return use_case
