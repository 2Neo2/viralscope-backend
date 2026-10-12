from fastapi.testclient import TestClient

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
