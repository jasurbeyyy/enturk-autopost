"""ElevenLabs matndan nutq (TTS) mijozi."""
from __future__ import annotations

import asyncio
import logging

import httpx

log = logging.getLogger(__name__)
BASE = "https://api.elevenlabs.io"


class ElevenError(RuntimeError):
    pass


class ElevenClient:
    def __init__(self, api_key: str, model_id: str, timeout: float = 120.0):
        self.api_key = api_key
        self.model_id = model_id
        self.http = httpx.AsyncClient(timeout=timeout, headers={"xi-api-key": api_key})
        self._lang_code_ok = True

    async def aclose(self) -> None:
        await self.http.aclose()

    async def tts(self, text: str, voice_id: str, language_code: str | None = None) -> bytes:
        body: dict = {"text": text, "model_id": self.model_id}
        if language_code and self._lang_code_ok:
            body["language_code"] = language_code
        delay = 3.0
        for attempt in range(1, 6):
            try:
                r = await self.http.post(
                    f"{BASE}/v1/text-to-speech/{voice_id}",
                    params={"output_format": "mp3_44100_128"},
                    json=body,
                )
            except httpx.HTTPError as exc:
                if attempt == 5:
                    raise ElevenError(f"tarmoq xatosi: {exc}") from exc
                await asyncio.sleep(delay)
                delay *= 2
                continue
            if r.status_code == 200:
                return r.content
            msg = r.text[:400]
            if r.status_code in (400, 422) and "language" in msg.lower() and "language_code" in body:
                log.info("Model language_code'ni qo'llamaydi, usiz qayta urinish")
                self._lang_code_ok = False
                body.pop("language_code", None)
                continue
            if r.status_code in (429, 500, 502, 503) and attempt < 5:
                log.warning("ElevenLabs %s, qayta urinish: %s", r.status_code, msg)
                await asyncio.sleep(delay)
                delay *= 2
                continue
            raise ElevenError(f"ElevenLabs {r.status_code}: {msg}")
        raise ElevenError("urinishlar tugadi")

    async def list_voices(self) -> list[dict]:
        r = await self.http.get(f"{BASE}/v1/voices")
        r.raise_for_status()
        return r.json().get("voices", [])

    async def get_voice(self, voice_id: str) -> dict:
        r = await self.http.get(f"{BASE}/v1/voices/{voice_id}")
        if r.status_code != 200:
            raise ElevenError(f"ovoz topilmadi ({voice_id}): {r.status_code}")
        return r.json()

    async def subscription(self) -> dict:
        r = await self.http.get(f"{BASE}/v1/user/subscription")
        r.raise_for_status()
        return r.json()
