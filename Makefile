SHELL := /bin/bash

.DEFAULT_GOAL := help

COMPOSE := docker compose
UV := uv

.PHONY: help env install seed lint typecheck test check db-up db-down up up-d start down logs logs-api logs-db dev ready clean

help:
	@echo "Доступные команды:"
	@echo "  make env           - создать .env из .env.example, если файла еще нет"
	@echo "  make install       - установить зависимости через uv"
	@echo "  make seed          - пересобрать db/02_seed.sql"
	@echo "  make lint          - запустить ruff"
	@echo "  make typecheck     - запустить mypy"
	@echo "  make test          - запустить pytest"
	@echo "  make check         - запустить lint + mypy + pytest"
	@echo "  make db-up         - поднять только PostgreSQL в Docker"
	@echo "  make start         - поднять весь стек и дождаться readiness"
	@echo "  make up            - поднять весь стек c OpenAI-compatible LLM"
	@echo "  make dev           - локально запустить API, БД поднять в Docker"
	@echo "  make ready         - проверить readiness API"
	@echo "  make down          - остановить контейнеры"

env:
	@if [[ ! -f .env ]]; then cp .env.example .env; echo "Создан .env из .env.example"; else echo ".env уже существует"; fi

install:
	$(UV) sync --extra dev --extra seed

seed:
	$(UV) run --extra seed python scripts/generate_seed.py

lint:
	$(UV) run ruff check .

typecheck:
	$(UV) run mypy src

test:
	$(UV) run pytest -q

check: lint typecheck test

db-up:
	$(COMPOSE) up -d db

db-down:
	$(COMPOSE) stop db

up: env
	$(COMPOSE) up --build

up-d: env
	$(COMPOSE) up --build -d

start: up -d ready

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f

logs-api:
	$(COMPOSE) logs -f api

logs-db:
	$(COMPOSE) logs -f db

dev: env db-up
	$(UV) run uvicorn src.main:app --reload

ready:
	curl -fsS --retry 30 --retry-delay 1 --retry-connrefused --retry-all-errors http://localhost:8000/health/ready

clean:
	$(COMPOSE) down -v