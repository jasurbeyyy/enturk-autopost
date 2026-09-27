"""Gemini API mijozi (REST): matn, Google Search bilan qidiruv, rasm (Nano Banana)."""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
from typing import Any

import httpx

log = logging.getLogger(__name__)
API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
RETRY_STATUSES = {429, 500, 502, 503, 504}


class GeminiError(RuntimeError):
    def __init__(self, status: int, message: str):
        super().__init__(f"Gemini {status}: {message}")
        self.status = status


def extract_json(text: str) -> Any:
    """Model javobidan JSON'ni ajratib olish (```json bloklari, ortiqcha matn va h.k.)."""
    t = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", t, re.S)
    if fence:
        t = fence.group(1).strip()
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        pass
    start = min([i for i in (t.find("{"), t.find("[")) if i >= 0], default=-1)
    if start < 0:
        raise ValueError(f"JSON topilmadi: {text[:200]}")
    closer = "}" if t[start] == "{" else "]"
    end = t.rfind(closer)
    return json.loads(t[start:end + 1])


class GeminiClient:
    def __init__(self, api_key: str, text_model: str, image_model: str,
                 timeout: float = 180.0):
        self.api_key = api_key
        self.text_model = text_model
        self.image_model = image_model
        self.http = httpx.AsyncClient(timeout=timeout)
        self._image_cfg_variant: int | None = None  # qaysi so'rov shakli ishlagani eslab qolinadi

    async def aclose(self) -> None:
        await self.http.aclose()

    async def _post(self, model: str, body: dict, attempts: int = 5) -> dict:
        delay = 3.0
        for attempt in range(1, attempts + 1):
            try:
                r = await self.http.post(
                    API.format(model=model),
                    headers={"x-goog-api-key": self.api_key, "Content-Type": "application/json"},
                    json=body,
                )
            except httpx.HTTPError as exc:
                if attempt == attempts:
                    raise GeminiError(0, f"tarmoq xatosi: {exc}") from exc
                log.warning("Gemini tarmoq xatosi (%s), qayta urinish %s", exc, attempt)
                await asyncio.sleep(delay)
                delay *= 2.5
                continue
            if r.status_code == 200:
                return r.json()
            msg = r.text[:500]
            if r.status_code == 429 and "quota" in msg.lower() and "billing" in msg.lower():
                # kunlik/tarif limiti — kutishdan foyda yo'q
                raise GeminiError(429, "QUOTA: " + msg)
            if r.status_code in RETRY_STATUSES and attempt < attempts:
                log.warning("Gemini %s, %.0fs dan so'ng qayta urinish: %s", r.status_code, delay, msg)
                await asyncio.sleep(delay)
                delay *= 2.5
                continue
            raise GeminiError(r.status_code, msg)
        raise GeminiError(0, "urinishlar tugadi")

    @staticmethod
    def _parts(resp: dict) -> list[dict]:
        cands = resp.get("candidates") or []
        if not cands:
            fb = resp.get("promptFeedback", {})
            raise GeminiError(200, f"javob bo'sh (blok: {fb})")
        return (cands[0].get("content") or {}).get("parts") or []

    async def generate_text(self, system: str, prompt: str, *, search: bool = False,
                            json_mode: bool = True, temperature: float = 0.8,
                            images: list[bytes] | None = None) -> tuple[str, list[str]]:
        """Matn qaytaradi va (search=True bo'lsa) manba havolalari ro'yxatini."""
        parts: list[dict] = [{"text": prompt}]
        for img in images or []:
            parts.append({"inline_data": {"mime_type": "image/jpeg",
                                          "data": base64.b64encode(img).decode()}})
        body: dict[str, Any] = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {"temperature": temperature},
        }
        if search:
            body["tools"] = [{"google_search": {}}]
        elif json_mode:
            body["generationConfig"]["responseMimeType"] = "application/json"

        try:
            resp = await self._post(self.text_model, body)
        except GeminiError as exc:
            if not (search and exc.status == 429):
                raise
            log.warning("Google Search limiti tugagan — qidiruvsiz davom etiladi")
            body.pop("tools", None)
            if json_mode:
                body["generationConfig"]["responseMimeType"] = "application/json"
            resp = await self._post(self.text_model, body)
        text = "".join(p.get("text", "") for p in self._parts(resp)
                       if not p.get("thought") and "text" in p)
        sources: list[str] = []
        gm = (resp.get("candidates") or [{}])[0].get("groundingMetadata") or {}
        for ch in gm.get("groundingChunks") or []:
            web = ch.get("web") or {}
            if web.get("uri"):
                sources.append(f"{web.get('title', '')} | {web['uri']}")
        return text, sources

    async def generate_json(self, system: str, prompt: str, **kw: Any) -> tuple[Any, list[str]]:
        last_err: Exception | None = None
        for _ in range(3):
            text, sources = await self.generate_text(system, prompt, **kw)
            try:
                return extract_json(text), sources
            except (ValueError, json.JSONDecodeError) as exc:
                last_err = exc
                log.warning("JSON o'qilmadi, qayta so'raladi: %s", exc)
                prompt += "\n\nIMPORTANT: reply with ONE valid JSON object only."
        raise GeminiError(200, f"JSON olinmadi: {last_err}")

    async def generate_image(self, prompt: str, aspect: str = "4:5", size: str = "1K") -> bytes:
        variants = [
            {"responseModalities": ["IMAGE"],
             "responseFormat": {"image": {"aspectRatio": aspect, "imageSize": size}}},
            {"responseModalities": ["IMAGE"],
             "imageConfig": {"aspectRatio": aspect, "imageSize": size}},
            {"responseModalities": ["TEXT", "IMAGE"]},
        ]
        order = list(range(len(variants)))
        if self._image_cfg_variant is not None:
            order.remove(self._image_cfg_variant)
            order.insert(0, self._image_cfg_variant)
        last: Exception | None = None
        for idx in order:
            body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
                    "generationConfig": variants[idx]}
            try:
                resp = await self._post(self.image_model, body)
            except GeminiError as exc:
                if exc.status == 400:
                    log.info("Rasm so'rovi shakli #%s mos kelmadi: %s", idx, exc)
                    last = exc
                    continue
                raise
            images = [p["inlineData"]["data"] if "inlineData" in p else p["inline_data"]["data"]
                      for p in self._parts(resp)
                      if ("inlineData" in p or "inline_data" in p) and not p.get("thought")]
            if not images:
                raise GeminiError(200, "rasm qaytmadi")
            self._image_cfg_variant = idx
            return base64.b64decode(images[-1])
        raise last or GeminiError(0, "rasm yaratilmadi")
