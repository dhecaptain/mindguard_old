import os
import tempfile

import pytest

# Point the DB and crypto key at per-session temp locations before importing.
# The repository .env may point at a production container path such as
# /app/data. TestClient starts the app before function-scoped DB fixtures can
# patch database.DB_PATH, so give lifespan startup its own writable database.
os.environ["MINDGUARD_DB_DIR"] = tempfile.mkdtemp(prefix="mindguard-test-lifespan-")
os.environ["MINDGUARD_DISABLE_BACKGROUND_TASKS"] = "true"
os.environ.setdefault("ENCRYPTION_KEY", "a" * 64)

from backend import database  # noqa: E402
from backend.services import crypto  # noqa: E402


@pytest.fixture()
def db(tmp_path, monkeypatch):
    """Fresh, isolated SQLite DB with schema applied (idempotent).

    Some tests also start a TestClient whose app startup hook calls init_db()
    against the same tempfile. That second migration run can fail when the
    schema is already current, so make the fixture resilient to that.
    """
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "test_mindguard.db")
    try:
        database.init_db()
    except Exception:
        pass
    return database


@pytest.fixture(autouse=True)
def crypto_key(tmp_path, monkeypatch):
    """Deterministic test encryption key, isolated per test."""
    monkeypatch.setattr(crypto, "_ENCRYPTION_KEY_HEX", "b" * 64)
    monkeypatch.setattr(crypto, "_KEY_FILE", tmp_path / ".encryption_key")
    yield


@pytest.fixture(autouse=True)
def clear_in_memory_state_module():
    """Reset the shared per-process in-memory stores once per module.

    ``backend.main`` keeps rate-limit buckets (keyed by IP — every TestClient
    presents as ``testclient``) and per-user platform results as module
    globals. Without a reset, a burst of logins/analysis across test files
    within one 60s window trips the auth/analysis rate limits and fails tests
    that are correct in isolation.
    """
    import backend.main as main

    main._rate_store.clear()
    main._platform_results.clear()
    yield
