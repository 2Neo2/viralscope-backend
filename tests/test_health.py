import asyncio
import time

from fastapi.testclient import TestClient
from structlog.testing import capture_logs

from app.main import create_app
from tests.conftest import make_settings


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "env": "test", "version": "0.1.0"}


def test_request_id_and_timing_headers(client):
    response = client.get("/health")
    assert len(response.headers["X-Request-ID"]) == 32
    assert float(response.headers["X-Process-Time"]) >= 0


def test_incoming_request_id_is_kept(client):
    response = client.get("/health", headers={"X-Request-ID": "support-ticket-42"})
    assert response.headers["X-Request-ID"] == "support-ticket-42"


def test_bad_incoming_request_id_is_replaced(client):
    for bad in ("with space", "x" * 65, "<script>"):
        assert client.get("/health", headers={"X-Request-ID": bad}).headers["X-Request-ID"] != bad


def test_errors_get_request_id_too(client):
    response = client.get("/nope", headers={"X-Request-ID": "req-404"})
    assert response.status_code == 404
    assert response.headers["X-Request-ID"] == "req-404"
    assert response.json()["error"]["code"] == "not_found"


def test_docs_available_outside_prod(client):
    assert client.get("/docs").status_code == 200
    assert client.get("/openapi.json").status_code == 200


def test_docs_hidden_in_prod():
    client = TestClient(create_app(make_settings(env="prod")))
    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404
    assert client.get("/health").status_code == 200


def test_cors_allows_own_site_only(client):
    allowed = client.get("/health", headers={"Origin": "http://localhost:3000"})
    assert allowed.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert allowed.headers["access-control-allow-credentials"] == "true"
    assert "x-request-id" in allowed.headers["access-control-expose-headers"].lower()

    blocked = client.get("/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in blocked.headers


def test_cors_preflight_gets_request_id(client):
    response = client.options(
        "/health",
        headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "GET"},
    )
    assert response.status_code == 200
    assert response.headers["X-Request-ID"]


class FakeConnection:
    def __init__(self, delay: float = 0) -> None:
        self.delay = delay

    async def __aenter__(self) -> "FakeConnection":
        await asyncio.sleep(self.delay)
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def execute(self, statement: object) -> None:
        return None


class FakeEngine:
    """Вместо базы: тест проверяет логику /health/ready, а не PostgreSQL."""

    def __init__(self, delay: float = 0) -> None:
        self.delay = delay

    def connect(self) -> FakeConnection:
        return FakeConnection(self.delay)


def test_ready_ok_when_database_answers(app):
    app.state.engine = FakeEngine()
    response = TestClient(app).get("/health/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "checks": {"database": "ok"}}


def test_ready_503_when_database_is_down():
    # Порт 1 никто не слушает: соединение сразу отклоняется, как при остановленной базе
    app = create_app(make_settings(database_url="postgresql+asyncpg://u:secret@127.0.0.1:1/vs"))
    with capture_logs() as logs:
        response = TestClient(app).get("/health/ready")
    assert response.status_code == 503
    assert response.json() == {"status": "unavailable", "checks": {"database": "error"}}
    assert response.headers["X-Request-ID"]
    failed = next(entry for entry in logs if entry["event"] == "readiness_check_failed")
    assert failed["log_level"] == "warning"
    assert failed["check"] == "database"
    assert "secret" not in str(logs)


def test_ready_503_when_database_hangs():
    app = create_app(make_settings(db_health_timeout=0.05))
    app.state.engine = FakeEngine(delay=5)
    started = time.perf_counter()
    with capture_logs() as logs:
        response = TestClient(app).get("/health/ready")
    assert response.status_code == 503
    assert time.perf_counter() - started < 1
    failed = next(entry for entry in logs if entry["event"] == "readiness_check_failed")
    assert failed["error_type"] == "TimeoutError"


def test_ready_documented_with_503(client):
    responses = client.get("/openapi.json").json()["paths"]["/health/ready"]["get"]["responses"]
    assert {"200", "503"} <= responses.keys()


async def test_ready_ok_with_real_database(db_client):
    response = await db_client.get("/health/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "checks": {"database": "ok"}}
