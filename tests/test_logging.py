import json
import logging

import pytest
import structlog

from app.core.config import Settings
from app.core.logging import get_logger, mask_email, setup_logging


@pytest.fixture(autouse=True)
def reset_logging():
    yield
    structlog.contextvars.clear_contextvars()
    structlog.reset_defaults()
    logging.getLogger().handlers.clear()


def json_lines(text: str) -> list[dict]:
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def setup_json(**overrides) -> None:
    setup_logging(Settings(_env_file=None, env="test", service="api", version="1.2.3", **overrides))


def test_json_record_has_app_fields(capsys):
    setup_json()
    get_logger("test").info("seat_reserved", launch=3, seats_left=11)
    record = json_lines(capsys.readouterr().out)[-1]
    assert record["event"] == "seat_reserved"
    assert record["launch"] == 3
    assert record["level"] == "info"
    assert record["service"] == "api" and record["env"] == "test" and record["version"] == "1.2.3"
    assert record["time"].endswith("Z")


def test_request_context_is_added_automatically(capsys):
    setup_json()
    structlog.contextvars.bind_contextvars(request_id="abc123")
    get_logger().info("payment_succeeded", amount_rub=1743)
    assert json_lines(capsys.readouterr().out)[-1]["request_id"] == "abc123"


def test_secrets_and_emails_are_masked(capsys):
    setup_json()
    get_logger().info(
        "login_attempt",
        email="ivan.petrov@mail.ru",
        password="Secret123",
        code="482913",
        headers={"Authorization": "Bearer xyz", "accept": "json"},
    )
    output = capsys.readouterr().out
    record = json_lines(output)[-1]
    assert record["password"] == "***" and record["code"] == "***"
    assert record["headers"] == {"Authorization": "***", "accept": "json"}
    assert record["email"] == "i***@mail.ru"
    assert "Secret123" not in output and "482913" not in output and "xyz" not in output


def test_exception_is_logged_with_traceback(capsys):
    setup_json()
    try:
        raise RuntimeError("provider is down")
    except RuntimeError:
        get_logger().exception("collect_failed", niche="fitness")
    record = json_lines(capsys.readouterr().out)[-1]
    assert record["level"] == "error"
    assert "RuntimeError: provider is down" in record["exception"]


def test_stdlib_loggers_use_same_format(capsys):
    setup_json()
    structlog.contextvars.bind_contextvars(request_id="r1")
    logging.getLogger("uvicorn.error").warning("server is shutting down")
    record = json_lines(capsys.readouterr().out)[-1]
    assert record["event"] == "server is shutting down"
    assert record["level"] == "warning"
    assert record["service"] == "api" and record["request_id"] == "r1"


def test_uvicorn_color_message_is_dropped(capsys):
    setup_json()
    colored = "Started server process [\x1b[36m%d\x1b[0m]"
    uvicorn_logger = logging.getLogger("uvicorn.error")
    uvicorn_logger.info("Started server process [%d]", 42, extra={"color_message": colored})
    record = json_lines(capsys.readouterr().out)[-1]
    assert record["event"] == "Started server process [42]"
    assert "color_message" not in record


def test_uvicorn_access_log_is_disabled(capsys):
    setup_json()
    logging.getLogger("uvicorn.access").info('127.0.0.1 - "GET /health HTTP/1.1" 200')
    assert capsys.readouterr().out == ""


def test_level_filter(capsys):
    setup_json(log_level="WARNING")
    log = get_logger()
    log.info("hidden_event")
    log.warning("visible_event")
    events = [r["event"] for r in json_lines(capsys.readouterr().out)]
    assert events == ["visible_event"]


def test_dev_output_is_human_readable(capsys):
    setup_logging(Settings(_env_file=None, env="dev"))
    get_logger().info("server_started", port=8000)
    output = capsys.readouterr().out
    assert "server_started" in output
    with pytest.raises(json.JSONDecodeError):
        json.loads(output.strip().splitlines()[-1])


def test_mask_email_inside_text():
    assert mask_email("письмо отправлено на anna@mail.ru") == "письмо отправлено на a***@mail.ru"
