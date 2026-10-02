import os
import asyncio
import json
from contextlib import asynccontextmanager

os.environ.setdefault("JWT_SECRET", "voice-realtime-test-secret")

from backend.routes import voice_support
from backend.services.voice_realtime import deepgram_voice_settings


def test_nonproduction_testing_bypasses_only_review_gate(monkeypatch):
    for name in (
        "VOICE_CLINICAL_REVIEW_COMPLETE",
        "VOICE_CHILD_SAFEGUARDING_REVIEW_COMPLETE",
        "VOICE_PRIVACY_REVIEW_COMPLETE",
        "VOICE_ACCESSIBILITY_REVIEW_COMPLETE",
    ):
        monkeypatch.setenv(name, "false")
    monkeypatch.setenv("VOICE_NON_PRODUCTION_TESTING_ENABLED", "true")
    monkeypatch.setenv("MINDGUARD_ENV", "staging")

    assert voice_support._production_review_complete() is False
    assert voice_support._non_production_testing() is True
    assert voice_support._launch_ready() is True

    monkeypatch.setenv("MINDGUARD_ENV", "production")
    assert voice_support._non_production_testing() is False
    assert voice_support._launch_ready() is False
    monkeypatch.setenv("MINDGUARD_ENV", "prod-like-unknown")
    assert voice_support._non_production_testing() is False


def test_deepgram_voice_settings_keep_function_execution_server_side(monkeypatch):
    monkeypatch.setenv("DEEPGRAM_STT_MODEL", "flux-general-multi")
    monkeypatch.setenv("DEEPGRAM_TTS_VERSION", "v2")
    monkeypatch.setenv("DEEPGRAM_TTS_MODEL", "flux-alexis-en")
    monkeypatch.setenv("DEEPGRAM_LLM_PROVIDER", "open_ai")
    monkeypatch.setenv("DEEPGRAM_LLM_MODEL", "gpt-4o-mini")
    tools = [{
        "name": "propose_private_summary",
        "description": "Stage a note for confirmation.",
        "parameters": {"type": "object", "properties": {"summary": {"type": "string"}}},
    }]

    settings = deepgram_voice_settings("MindGuard instructions", tools)
    agent = settings["agent"]
    assert agent["listen"]["provider"]["model"] == "flux-general-multi"
    assert agent["think"]["provider"]["model"] == "gpt-4o-mini"
    assert agent["speak"]["provider"] == {"type": "deepgram", "version": "v2", "model": "flux-alexis-en"}
    assert agent["think"]["functions"][0]["client_side"] is True
    assert settings["flags"]["history"] is False
    assert settings["mip_opt_out"] is True


def test_deepgram_session_uses_authenticated_server_relay(db, monkeypatch):
    from fastapi.testclient import TestClient
    from backend.auth import hash_password
    from backend.main import app

    user = db.create_user(
        "voice-deepgram@example.org",
        "Voice Test User",
        hash_password("voice-test-password"),
        role_type="student",
    )
    conn = db.get_db()
    conn.execute("UPDATE users SET status='approved',user_category='adult' WHERE id=?", (user["id"],))
    conn.commit()
    conn.close()
    for name in (
        "VOICE_SUPPORT_ENABLED",
        "VOICE_SERVER_SIDE_CONTROLS_ENABLED",
        "VOICE_CLINICAL_REVIEW_COMPLETE",
        "VOICE_CHILD_SAFEGUARDING_REVIEW_COMPLETE",
        "VOICE_PRIVACY_REVIEW_COMPLETE",
        "VOICE_ACCESSIBILITY_REVIEW_COMPLETE",
    ):
        monkeypatch.setenv(name, "true")
    monkeypatch.setenv("MINDGUARD_ENV", "staging")
    monkeypatch.setenv("MINDGUARD_DISABLE_BACKGROUND_TASKS", "false")
    monkeypatch.setenv("VOICE_REALTIME_PROVIDER", "deepgram")
    monkeypatch.setenv("DEEPGRAM_API_KEY", "test-deepgram-key")
    monkeypatch.setenv("OPENAI_API_KEY", "test-moderation-key")
    monkeypatch.setenv("VOICE_SAFETY_SALT", "voice-test-safety-salt-with-at-least-32-chars")

    class FakeSocket:
        def __init__(self):
            self.closed = asyncio.Event()

        async def send(self, message):
            self.settings = json.loads(message)

        async def recv(self):
            if not getattr(self, "welcomed", False):
                self.welcomed = True
                return json.dumps({"type": "Welcome"})
            if not getattr(self, "settings", None):
                await asyncio.sleep(0.01)
                return json.dumps({"type": "Welcome"})
            if not getattr(self, "settings_acknowledged", False):
                self.settings_acknowledged = True
                return json.dumps({"type": "SettingsApplied"})
            await asyncio.sleep(0.02)
            return json.dumps({"type": "AgentAudioDone"})

        async def close(self):
            self.closed.set()

    class FakeProvider:
        def __init__(self, _key):
            self.socket = FakeSocket()

        @asynccontextmanager
        async def connect(self):
            yield self.socket

    monkeypatch.setattr(voice_support, "DeepgramVoiceAgentProvider", FakeProvider)
    with TestClient(app) as client:
        login = client.post("/api/auth/login", json={"email": user["email"], "password": "voice-test-password"})
        assert login.status_code == 200
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        session = client.post("/api/v1/voice/sessions", headers=headers, json={"accepted_notice": True})
        assert session.status_code == 201, session.text
        session_id = session.json()["session_id"]
        with client.websocket_connect(f"/api/v1/voice/sessions/{session_id}/stream") as websocket:
            websocket.send_json({"type": "auth", "token": login.json()["access_token"]})
            assert websocket.receive_json()["type"] == "MindGuardReady"
            conn = db.get_db()
            row = conn.execute("SELECT status,provider_call_id,sideband_connected_at FROM voice_support_sessions WHERE id=?", (session_id,)).fetchone()
            conn.close()
            assert row["status"] == "active"
            assert row["provider_call_id"] == f"deepgram_{session_id}"
            assert row["sideband_connected_at"]
            client.post(f"/api/v1/voice/sessions/{session_id}/close", headers=headers, json={})
