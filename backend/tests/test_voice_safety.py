import asyncio

from backend.services import voice_safety


class FakeResponse:
    def __init__(self, categories):
        self._categories = categories

    def raise_for_status(self):
        return None

    def json(self):
        return {"results": [{"categories": self._categories}]}


class FakeAsyncClient:
    def __init__(self, categories):
        self._categories = categories

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None

    async def post(self, *_args, **_kwargs):
        return FakeResponse(self._categories)


def test_voice_safety_requires_moderation_and_context_for_immediate_state(monkeypatch):
    monkeypatch.setattr(
        voice_safety.httpx,
        "AsyncClient",
        lambda **_: FakeAsyncClient({"self-harm/intent": True, "self-harm": True}),
    )
    assert (
        asyncio.run(voice_safety.classify_voice_text(
            "I want to end my life tonight", "test-only-key"
        ))
        == voice_safety.POTENTIAL_IMMEDIATE_DANGER
    )
    assert (
        asyncio.run(voice_safety.classify_voice_text(
            "My friend wrote a song about suicide", "test-only-key"
        ))
        == voice_safety.HEIGHTENED_CONCERN
    )


def test_voice_safety_moderation_failure_is_not_silently_normal(monkeypatch):
    class FailedAsyncClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def post(self, *_args, **_kwargs):
            raise voice_safety.httpx.TimeoutException("test timeout")

    monkeypatch.setattr(voice_safety.httpx, "AsyncClient", lambda **_: FailedAsyncClient())
    assert (
        asyncio.run(voice_safety.classify_voice_text(
            "I want to kill myself", "test-only-key"
        ))
        == voice_safety.HEIGHTENED_CONCERN
    )
