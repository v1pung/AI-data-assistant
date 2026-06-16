"""Liveness and readiness probes.

  GET /health        -> always 200 while the process is up (liveness).
  GET /health/ready  -> 200 only if the DB pool can serve a `SELECT 1` (readiness).

Readiness is what Docker/compose healthchecks and orchestrators should poll.

STATUS: /health is implemented; /health/ready body is specified for the
implementer.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter(tags=["health"])


@router.get("/health", summary="Liveness probe")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready", summary="Readiness probe (checks DB)")
async def ready(request: Request) -> JSONResponse:
    """Implement:
      - pool = request.app.state.db_pool
      - try: async with pool.connection() as conn: await conn.execute("SELECT 1")
             return JSONResponse(200, {"status": "ready"})
      - except Exception: return JSONResponse(503, {"status": "not_ready"})
    Never raise — this endpoint must always answer.
    """
    pool = request.app.state.db_pool
    try:
        async with pool.connection() as conn:
            await conn.execute("SELECT 1")
        return JSONResponse({"status": "ready"})
    except Exception:
        return JSONResponse(status_code=503, content={"status": "not_ready"})
