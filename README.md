# AI Data Assistant

Сервис принимает вопрос на естественном языке, передает в LLM описание схемы PostgreSQL, получает SQL `SELECT`, проверяет его на безопасность, выполняет в режиме `read-only` и возвращает результат.

Пример:

```text
Top N countries by revenue
```

## Что умеет сервис

- работает с любым OpenAI-compatible API через `/v1/chat/completions`;
- подключается к PostgreSQL с синтетической аналитической схемой;
- ограничивает качество и стоимость SQL (guard + EXPLAIN preflight policy);
- отдает Prometheus-метрики на `/metrics`;
- не должен падать при ошибках LLM, SQL или базы данных;
- запускается локально через `uv` и целиком через Docker Compose.

## Требования

- Docker и Docker Compose;
- `make` (Linux/WSL);
- для локальной разработки: `uv`.

## Быстрый старт

### Запуск со своим OpenAI-compatible LLM API

1. Создайте `.env`:

```bash
make env
```

2. Откройте `.env` и заполните как минимум:

```dotenv
LLM_BASE_URL=https://openrouter.ai/api/v1
LLM_MODEL=openai/gpt-oss-120b:free
LLM_API_KEY=ваш ключ
```

3. Поднимите весь стек одной командой и дождитесь readiness:

```bash
make start
```

### Что поднимется

- `db` на `localhost:5432`;
- `api` на `localhost:8000`;
- Swagger UI на `http://localhost:8000/docs`.

## Команды Makefile

Основные команды:

```bash
make help
make env
make install
make check
make start
make up
make down
```

Назначение:

- `make install` — установить зависимости через `uv sync --extra dev --extra seed`;
- `make check` — прогнать `ruff`, `mypy` и `pytest`;
- `make start` — поднять БД и API в Docker со значениями LLM из `.env` и дождаться readiness;
- `make up` — поднять БД и API в Docker в foreground-режиме со значениями LLM из `.env`;
- `make dev` — поднять БД в Docker и запустить API локально через `uvicorn`;
- `make down` — остановить контейнеры;
- `make seed` — пересобрать `db/02_seed.sql`.

## Как подключить и инициализировать базу данных

Инициализация базы происходит автоматически при первом старте Docker Compose.

PostgreSQL запускает SQL-файлы из каталога `db/` по порядку:

1. `db/01_schema.sql` — создает таблицы, индексы и read-only роль `assistant_ro`.
2. `db/02_seed.sql` — загружает синтетические данные.

Для обычного запуска достаточно:

```bash
make start
```

Если нужен только PostgreSQL:

```bash
make db-up
```

Если нужно полностью пересоздать базу с нуля:

```bash
make clean
make up
```

Локальное подключение к базе:

```text
postgresql://assistant_ro:assistant_ro@localhost:5432/analytics
```

Этот DSN уже указан в `.env.example` для локального запуска API.

## Примеры запросов

После запуска можно проверить сервис так:

```bash
curl -s localhost:8000/api/v1/ask \
  -H 'content-type: application/json' \
  -d '{"question":"Top 30 countries by revenue","max_rows":30}'
```

Еще примеры вопросов:

- `Top 10 products by units sold`
- `Monthly revenue trend in 2024`
- `Average order value by customer segment`
- `Revenue share by sales channel`
- `Which categories have the worst average review rating?`

Проверка health endpoints:

```bash
curl http://localhost:8000/health
curl http://localhost:8000/health/ready
curl http://localhost:8000/metrics
```

## Как устроено решение

Проект построен по принципу onion architecture:

```text
api -> application -> domain <- infrastructure
```

Слои:

- `app/api` — FastAPI-роутеры, схемы запросов и централизованная обработка ошибок;
- `app/application` — use case, который оркестрирует весь сценарий вопроса;
- `app/domain` — доменные сущности, порты и типизированные исключения;
- `app/infrastructure` — адаптеры для LLM, PostgreSQL и SQL guard.

Пайплайн обработки запроса:

1. API принимает вопрос.
2. `SchemaProvider` получает схему БД.
3. LLM строит SQL на основе вопроса и схемы.
4. При unsafe SQL use case делает retry (до `SQL_GENERATION_MAX_ATTEMPTS`) с validation feedback.
5. `SqlGlotGuard` проверяет, что это одиночный безопасный `SELECT`, и применяет quality policy.
6. `SqlExecutor` делает preflight `EXPLAIN (FORMAT JSON)` и проверяет budget.
7. `SqlExecutor` выполняет запрос в `read-only` транзакции с `statement_timeout`.
8. API возвращает SQL, колонки и строки результата.

## Observability

- structured logging в key=value формате по стадиям (`event=...`), включая pipeline/LLM/SQL шаги;
- correlation через `X-Request-ID` и лог-фильтр request id;
- Prometheus-метрики на `/metrics`:
  - HTTP request count/latency,
  - LLM request outcomes + latency,
  - LLM token usage,
  - SQL execution latency,
  - preflight EXPLAIN outcomes,
  - query cost exceeded counter;
- в ответе `/api/v1/ask` возвращаются диагностические поля `execution_ms`, `estimated_cost`, `estimated_plan_rows`.

## Безопасность и устойчивость

Безопасность обеспечивается тремя уровнями:

1. SQL guard пропускает только один `SELECT`/CTE и ограничивает `LIMIT`.
2. Исполнение идет в `SET TRANSACTION READ ONLY`.
3. Приложение подключается read-only пользователем `assistant_ro`.

Ошибки LLM и базы не должны падать наружу необработанными: они переводятся в доменные исключения и возвращаются как структурированный JSON-ответ.

Дополнительные policy-переменные (см. `.env.example`):

- `SQL_GENERATION_MAX_ATTEMPTS` — число попыток генерации SQL, если guard отклонил запрос;
- `SQL_QUALITY_STRICT`, `SQL_QUALITY_MAX_JOINS`, `SQL_QUALITY_MAX_SUBQUERIES`, `SQL_QUALITY_DISALLOW_SELECT_STAR_WITH_JOIN` — контроль качества SQL;
- `DB_EXPLAIN_PREFLIGHT_ENABLED`, `DB_EXPLAIN_STRICT`, `DB_EXPLAIN_MAX_TOTAL_COST`, `DB_EXPLAIN_MAX_PLAN_ROWS` — preflight cost guard;
- `METRICS_ENABLED` — включение endpoint `/metrics`.
