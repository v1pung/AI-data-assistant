# syntax=docker/dockerfile:1
# Build & run the service with uv. The uv base image ships Python + uv.
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /src

# 1) Install dependencies first (cached unless pyproject/uv.lock change).
#    README is referenced by pyproject ([project].readme), so it must exist.
COPY pyproject.toml README.md ./
COPY uv.lock* ./
RUN uv sync --no-dev --no-install-project

# 2) Copy the application source and install the project itself.
COPY src ./src
RUN uv sync --no-dev

EXPOSE 8000

# Run via uv so the project's virtualenv is used.
CMD ["uv", "run", "--no-dev", "uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
