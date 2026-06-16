"""HTTP request/response models (the public API contract).

These pydantic models exist only at the presentation edge. The use case speaks
in domain entities; the router maps domain <-> these models. Fully implemented.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from src.domain.entities import AskOutcome


class AskRequest(BaseModel):
    question: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="Natural-language question about the data.",
        examples=["Top 30 countries by revenue"],
    )
    max_rows: int | None = Field(
        default=None,
        ge=1,
        description=(
            "Optional cap on returned rows. Clamped to the server's absolute "
            "limit (MAX_ROWS_LIMIT); larger values are silently lowered."
        ),
    )


class AskResponse(BaseModel):
    question: str
    sql: str = Field(description="The SQL that was actually executed (post-safety-guard).")
    explanation: str | None = None
    columns: list[str]
    rows: list[list[Any]]
    row_count: int
    truncated: bool
    execution_ms: float
    estimated_cost: float | None = None
    estimated_plan_rows: int | None = None
    warnings: list[str] = Field(default_factory=list)

    @classmethod
    def from_outcome(cls, outcome: AskOutcome) -> AskResponse:
        return cls(
            question=outcome.question,
            sql=outcome.generated_sql.sql,
            explanation=outcome.explanation,
            columns=list(outcome.result.columns),
            rows=[list(r) for r in outcome.result.rows],
            row_count=outcome.result.row_count,
            truncated=outcome.result.truncated,
            execution_ms=outcome.result.execution_ms,
            estimated_cost=outcome.result.estimated_cost,
            estimated_plan_rows=outcome.result.estimated_plan_rows,
            warnings=list(outcome.warnings),
        )


class ErrorBody(BaseModel):
    code: str = Field(description="Stable machine-readable error code.")
    message: str = Field(description="Human-readable, safe-to-display message.")
    detail: str | None = Field(default=None, description="Optional technical detail.")


class ErrorResponse(BaseModel):
    error: ErrorBody
