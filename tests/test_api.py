"""FastAPI endpoint tests using in-memory fakes — no DB or LLM needed."""

from __future__ import annotations

from fastapi.testclient import TestClient

from src.api.deps import get_use_case
from src.application.use_cases.ask_question import AskQuestionUseCase
from src.domain.exceptions import LLMUnavailableError, QueryCostExceededError, QueryExecutionError
from src.infrastructure.sql.guard import SqlGlotGuard
from src.main import app
from tests.conftest import FakeSchemaProvider, FakeSqlExecutor, FakeSqlGenerator


def _make_use_case(
    schema,
    *,
    generator: FakeSqlGenerator,
    executor: FakeSqlExecutor,
) -> AskQuestionUseCase:
    return AskQuestionUseCase(
        schema_provider=FakeSchemaProvider(schema),
        sql_generator=generator,
        sql_guard=SqlGlotGuard(),
        sql_executor=executor,
        default_max_rows=100,
        max_rows_limit=1000,
    )


def test_ask_happy_path(sample_schema) -> None:
    generator = FakeSqlGenerator(sql="SELECT name FROM countries")
    executor = FakeSqlExecutor()
    use_case = _make_use_case(sample_schema, generator=generator, executor=executor)

    app.dependency_overrides[get_use_case] = lambda: use_case
    try:
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post("/api/v1/ask", json={"question": "list countries"})
    finally:
        app.dependency_overrides = {}

    assert resp.status_code == 200
    body = resp.json()
    assert "sql" in body
    assert "rows" in body
    assert "columns" in body


def test_ask_llm_unavailable_returns_503(sample_schema) -> None:
    generator = FakeSqlGenerator(error=LLMUnavailableError("LLM down"))
    executor = FakeSqlExecutor()
    use_case = _make_use_case(sample_schema, generator=generator, executor=executor)

    app.dependency_overrides[get_use_case] = lambda: use_case
    try:
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post("/api/v1/ask", json={"question": "list countries"})
    finally:
        app.dependency_overrides = {}

    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "llm_unavailable"


def test_ask_query_execution_error_returns_422(sample_schema) -> None:
    generator = FakeSqlGenerator(sql="SELECT name FROM countries")
    executor = FakeSqlExecutor(error=QueryExecutionError("column does not exist"))
    use_case = _make_use_case(sample_schema, generator=generator, executor=executor)

    app.dependency_overrides[get_use_case] = lambda: use_case
    try:
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post("/api/v1/ask", json={"question": "bad query"})
    finally:
        app.dependency_overrides = {}

    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "query_execution_failed"


def test_ask_query_cost_exceeded_returns_422(sample_schema) -> None:
    generator = FakeSqlGenerator(sql="SELECT name FROM countries")
    executor = FakeSqlExecutor(error=QueryCostExceededError("over budget"))
    use_case = _make_use_case(sample_schema, generator=generator, executor=executor)

    app.dependency_overrides[get_use_case] = lambda: use_case
    try:
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post("/api/v1/ask", json={"question": "expensive query"})
    finally:
        app.dependency_overrides = {}

    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "query_cost_exceeded"


def test_ask_missing_question_returns_422(sample_schema) -> None:
    app.dependency_overrides[get_use_case] = lambda: None
    try:
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post("/api/v1/ask", json={})
    finally:
        app.dependency_overrides = {}

    assert resp.status_code == 422


def test_health_liveness() -> None:
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_metrics_endpoint_available() -> None:
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert "assistant_http_requests_total" in resp.text
