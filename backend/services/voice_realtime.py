"""Vendor-specific Realtime transport behind the MindGuard voice boundary."""

from contextlib import asynccontextmanager
from urllib.parse import quote, urlparse

import httpx
from websockets.asyncio.client import connect


class VoiceProviderError(RuntimeError):
    """A provider failure safe to report without exposing credentials/content."""


class OpenAIRealtimeProvider:
    """OpenAI Realtime transport; application policy stays outside this adapter."""

    def __init__(self, api_key: str):
        self._api_key = api_key

    async def create_client_secret(self, payload: dict, safety_id: str) -> dict:
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                response = await client.post(
                    "https://api.openai.com/v1/realtime/client_secrets",
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                        "OpenAI-Safety-Identifier": safety_id,
                    },
                    json=payload,
                )
            if response.status_code >= 400:
                raise VoiceProviderError("Unable to start voice support right now")
            result = response.json()
            result["value"] = result.get("value") or result.get("client_secret", {}).get("value")
            if not result.get("value"):
                raise VoiceProviderError("The voice provider did not return a session credential")
            return result
        except httpx.HTTPError as exc:
            raise VoiceProviderError("Unable to reach the voice support provider") from exc

    async def connect_webrtc(self, client_secret: str, offer_sdp: str) -> tuple[str, str]:
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                response = await client.post(
                    "https://api.openai.com/v1/realtime/calls",
                    content=offer_sdp,
                    headers={
                        "Authorization": f"Bearer {client_secret}",
                        "Content-Type": "application/sdp",
                    },
                )
            if response.status_code >= 400:
                raise VoiceProviderError("Unable to establish the encrypted voice connection")
            call_id = self._call_id_from_location(response.headers.get("Location", ""))
            return response.text, call_id
        except httpx.HTTPError as exc:
            raise VoiceProviderError("Unable to reach the voice support provider") from exc

    @staticmethod
    def _call_id_from_location(location: str) -> str:
        path = urlparse(location).path
        call_id = path.rstrip("/").rsplit("/", 1)[-1]
        if not call_id.startswith("rtc_") or not call_id[4:].replace("-", "").replace("_", "").isalnum():
            raise VoiceProviderError("The voice provider returned an invalid call reference")
        return call_id

    @asynccontextmanager
    async def sideband(self, call_id: str):
        url = f"wss://api.openai.com/v1/realtime?call_id={quote(call_id, safe='')}"
        async with connect(
            url,
            additional_headers={"Authorization": f"Bearer {self._api_key}"},
            open_timeout=10,
            close_timeout=3,
            ping_interval=10,
            max_size=1_048_576,
        ) as socket:
            yield socket
