"""Security headers middleware tests (Delivery Brief §8).

Verifies the always-on headers on every response and that the strict CSP is
scoped to non-API HTML documents (the production SPA mount) while the
interactive docs stay exempt.
"""

from fastapi.testclient import TestClient

from backend.main import _build_security_headers, app


def test_always_on_headers_present_on_api_response():
    headers = _build_security_headers("application/json", "/api/v1/healthz")
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert headers["X-Frame-Options"] == "DENY"
    assert "Permissions-Policy" in headers
    assert "Content-Security-Policy" not in headers


def test_csp_applied_to_html_document():
    headers = _build_security_headers("text/html", "/")
    csp = headers["Content-Security-Policy"]
    assert "script-src 'self'" in csp
    assert "'unsafe-inline'" not in csp.split("script-src")[1].split(";")[0]
    assert "frame-ancestors 'none'" in csp
    assert "object-src 'none'" not in csp  # blob: pdfs are served via object-src


def test_csp_exempt_for_interactive_docs():
    for path in ("/docs", "/redoc", "/openapi.json"):
        headers = _build_security_headers("text/html", path)
        assert "Content-Security-Policy" not in headers


def test_csp_allows_required_assets():
    headers = _build_security_headers("text/html", "/")
    csp = headers["Content-Security-Policy"]
    assert "https://fonts.googleapis.com" in csp
    assert "https://cdn.jsdelivr.net" in csp
    assert "https://*.supabase.co" in csp
    assert "https://api.openai.com" in csp
    assert "blob:" in csp
    assert "microphone=(self)" in headers["Permissions-Policy"]


def test_hsts_emitted_only_over_https():
    with TestClient(app) as c:
        resp = c.get("/api/v1/healthz", headers={"X-Forwarded-Proto": "https"})
        assert resp.status_code == 200
        assert resp.headers["Strict-Transport-Security"] == "max-age=31536000; includeSubDomains"


def test_hsts_absent_over_plain_http():
    with TestClient(app) as c:
        resp = c.get("/api/v1/healthz", headers={"X-Forwarded-Proto": "http"})
        assert "Strict-Transport-Security" not in resp.headers
