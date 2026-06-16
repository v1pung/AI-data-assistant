# CLAUDE.md — guidance for implementing this repository

You are maintaining and extending a FastAPI service.

## What this service does

Accepts a natural-language question, asks an LLM (OpenAI-compatible API) to
write a PostgreSQL `SELECT`, validates that SQL, executes it read-only against a
seeded analytics database, and returns the rows. See
[README.md](README.md) for the user-facing view.

## Architecture rules (non-negotiable)

- **Onion / clean architecture.** Dependencies point inward:
  `api → application → domain ← infrastructure`.
- `app/domain/` imports only the stdlib. No `fastapi`, `httpx`, `psycopg`,
  `sqlglot` there — ever.
- `app/application/` imports only from `app/domain/`. The use case talks to
  **ports** (Protocols), never to concrete adapters.
- Concrete adapters live in `app/infrastructure/` and implement the ports
  structurally (they don't subclass them).
- All wiring happens in `app/main.py` (composition root) and is handed to
  routers via `app/api/deps.py`. Don't construct adapters anywhere else.

## How to implement changes

Keep the existing contracts and architecture stable. Prefer incremental,
test-backed improvements over broad redesigns. If you think a contract should
change, document the reason and update callers/tests in the same change.

## Resilience is a hard requirement

The service **must not crash** on LLM or DB errors.
- Adapters translate every foreseeable failure into a domain exception from
  `app/domain/exceptions.py` (`LLMUnavailableError`, `QueryTimeoutError`, …).
- `app/api/errors.py` already maps those to HTTP status codes, plus a catch-all
  that turns anything unexpected into a 500 JSON body.
- Never `print`; use `logging`. Never let a raw `httpx`/`psycopg` exception
  escape an adapter.

## Security is layered — don't weaken any layer

1. `SqlGlotGuard` — only a single read-only `SELECT`/CTE passes; LIMIT is capped.
2. Read-only transaction in `sql_executor` (`SET TRANSACTION READ ONLY`).
3. Read-only DB role `assistant_ro` (see `db/01_schema.sql`).

Do not run LLM SQL outside the guard. Do not connect as the DB owner.

## Conventions

- Python 3.12, full type hints, `from __future__ import annotations`.
- Async everywhere for I/O (httpx, psycopg async pool).
- Format/lint with `ruff`; type-check with `mypy src` (strict). Both must pass.
- Tests with `pytest` (`asyncio_mode=auto`). Prefer the in-memory fakes in
  `tests/conftest.py` over hitting real services.
- Dependencies via `uv` only: `uv add <pkg>`, run with `uv run <cmd>`.

## Commands

```bash
uv sync --extra dev --extra seed          # install
uv run --extra seed python scripts/generate_seed.py   # (re)generate db/02_seed.sql
uv run uvicorn src.main:app --reload      # run locally
uv run ruff check . && uv run mypy src && uv run pytest -q
docker compose up --build                 # full stack
```

## Out of scope (don't add)

Auth, multi-DB dialects, query history/persistence, a frontend, streaming
responses, or an ORM. Keep raw SQL + psycopg. The goal is a clean, resilient
text-to-SQL service, not a BI tool.
