"""Prometheus metrics endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Response

from src.infrastructure.observability.metrics import render_metrics

router = APIRouter(tags=["observability"])


@router.get("/metrics", summary="Prometheus metrics")
async def metrics() -> Response:
    return Response(content=render_metrics(), media_type="text/plain; version=0.0.4")
