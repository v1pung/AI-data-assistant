# AGENTS.md

Instruction file for AI coding agents working in this repository (the
cross-tool equivalent of `CLAUDE.md`; the homework asks that all such files be
committed).

**The authoritative instructions live in [CLAUDE.md](CLAUDE.md) and the ordered
task list in [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md). Read both before
writing code.** This file is a short summary.

## TL;DR for agents

- Stack: **Python 3.12 + FastAPI + uv + PostgreSQL**, OpenAI-compatible LLM API.
- Architecture: **onion**. `api → application → domain ← infrastructure`.
  `domain` is dependency-free; the use case depends only on **ports** (Protocols).
- The repo is the project's working codebase.
  Keep contracts stable, follow existing architecture decisions, and evolve
  behavior through small, test-backed changes.
- **Resilience is mandatory:** the service must never crash on LLM/DB errors;
  translate failures into domain exceptions (handled centrally in
  `app/api/errors.py`).
- **Security is layered:** SQL guard (single read-only SELECT) + read-only
  transaction + read-only DB role. Never bypass any layer.
- Tooling: `uv` for deps; `ruff`, `mypy src`, `pytest` must all pass.

## Project provenance

This project follows a
deliberate clean/onion architecture with explicit boundaries, safety guardrails,
and reliability constraints. Future edits should preserve those principles
instead of introducing ad-hoc coupling between layers.
