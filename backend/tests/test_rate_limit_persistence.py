from starlette.requests import Request

from backend import database
from backend.main import _client_ip


def _request(headers=None, client_host="10.0.0.5"):
    raw_headers = [
        (key.lower().encode(), value.encode()) for key, value in (headers or {}).items()
    ]
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": raw_headers,
            "client": (client_host, 1234),
            "query_string": b"",
            "server": ("testserver", 80),
            "scheme": "http",
        }
    )


def test_rate_limit_is_atomic_and_persisted(db):
    assert database.consume_rate_limit("login:10.0.0.5", 2, 60)
    assert database.consume_rate_limit("login:10.0.0.5", 2, 60)
    assert not database.consume_rate_limit("login:10.0.0.5", 2, 60)


def test_forwarded_ip_is_used_only_when_proxy_is_trusted(monkeypatch):
    request = _request({"x-forwarded-for": "198.51.100.7, 10.0.0.1"})

    monkeypatch.delenv("TRUSTED_PROXY", raising=False)
    assert _client_ip(request) == "10.0.0.5"

    monkeypatch.setenv("TRUSTED_PROXY", "true")
    assert _client_ip(request) == "198.51.100.7"
