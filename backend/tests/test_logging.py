"""Tests for structured JSON logging and request correlation (Brief §9)."""

import io
import json
import logging

import pytest

from backend.logging_setup import (
    RequestContextFilter,
    StructuredFormatter,
    generate_request_id,
    set_request_context,
    setup_logging,
)


@pytest.fixture()
def capture():
    buf = io.StringIO()
    root = logging.getLogger()
    old = list(root.handlers)
    handler = logging.StreamHandler(buf)
    handler.setFormatter(StructuredFormatter())
    handler.addFilter(RequestContextFilter())
    root.handlers[:] = [handler]
    root.setLevel(logging.INFO)
    yield buf
    root.handlers[:] = old


def test_record_is_json_with_request_fields(capture):
    set_request_context(
        request_id="abc123",
        method="POST",
        path="/api/x",
        status_code=201,
        duration_ms=12.5,
        user_id="u1",
        ip="1.2.3.4",
    )
    logging.getLogger("backend.main").info("boom")
    set_request_context()

    line = capture.getvalue().strip()
    assert line.count("\n") == 0  # one JSON object per line
    payload = json.loads(line)
    assert payload["level"] == "INFO"
    assert payload["logger"] == "backend.main"
    assert payload["message"] == "boom"
    assert payload["request_id"] == "abc123"
    assert payload["method"] == "POST"
    assert payload["status_code"] == 201
    assert payload["duration_ms"] == 12.5
    assert payload["user_id"] == "u1"
    assert payload["ip"] == "1.2.3.4"
    assert "ts" in payload


def test_fields_cleared_after_request(capture):
    set_request_context(request_id="abc", user_id="u1")
    logging.getLogger("x").info("first")
    set_request_context()
    logging.getLogger("x").info("second")

    lines = [json.loads(line) for line in capture.getvalue().strip().splitlines()]
    assert len(lines) == 2
    assert "request_id" in lines[0]
    assert "request_id" not in lines[1]


def test_request_id_format():
    rid = generate_request_id()
    assert len(rid) == 12
    assert all(c in "0123456789abcdef" for c in rid)


def test_exc_info_included(capture):
    try:
        raise ValueError("kapow")
    except ValueError:
        logging.getLogger("x").exception("failed")
    payload = json.loads(capture.getvalue().strip())
    assert "ValueError: kapow" in payload["exc_info"]


def test_setup_logging_replaces_handlers(monkeypatch):
    monkeypatch.setattr("backend.logging_setup.sys.stdout", io.StringIO())
    setup_logging()
    setup_logging()  # idempotent
    root = logging.getLogger()
    assert len(root.handlers) == 1
    handler = root.handlers[0]
    assert isinstance(handler.formatter, StructuredFormatter)
    assert any(isinstance(f, RequestContextFilter) for f in handler.filters)
