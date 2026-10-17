"""Telegram Bot API'ning oddiy HTTP mijozi (GitHub Actions rejimi uchun)."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import httpx

log = logging.getLogger(__name__)


class TelegramError(RuntimeError):
    pass


class TelegramAPI:
    def __init__(self, token: str):
        self.base = f"https://api.telegram.org/bot{token}"
        self.http = httpx.AsyncClient(timeout=httpx.Timeout(90.0, connect=20.0))

    async def aclose(self) -> None:
        await self.http.aclose()

    async def _call(self, method: str, data: dict | None = None, files: dict | None = None,
                    attempts: int = 4) -> Any:
        payload = {k: (json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v)
                   for k, v in (data or {}).items() if v is not None}
        delay = 3.0
        for attempt in range(1, attempts + 1):
            try:
                r = await self.http.post(f"{self.base}/{method}", data=payload, files=files)
                body = r.json()
            except (httpx.HTTPError, ValueError) as exc:
                if attempt == attempts:
                    raise TelegramError(f"{method}: {exc}") from exc
                await asyncio.sleep(delay)
                delay *= 2
                continue
            if body.get("ok"):
                return body["result"]
            retry_after = (body.get("parameters") or {}).get("retry_after")
            if (retry_after or r.status_code >= 500) and attempt < attempts:
                await asyncio.sleep(float(retry_after or delay))
                delay *= 2
                continue
            raise TelegramError(f"{method}: {body.get('description')}")
        raise TelegramError(f"{method}: urinishlar tugadi")

    async def send_message(self, chat_id, text: str, reply_markup: dict | None = None) -> dict:
        return await self._call("sendMessage", {"chat_id": chat_id, "text": text, "parse_mode": "HTML",
                                                "reply_markup": reply_markup,
                                                "link_preview_options": {"is_disabled": True}})

    async def send_photo(self, chat_id, photo: bytes, caption: str) -> dict:
        return await self._call("sendPhoto", {"chat_id": chat_id, "caption": caption, "parse_mode": "HTML"},
                                files={"photo": ("post.jpg", photo, "image/jpeg")})

    async def send_audio(self, chat_id, audio: bytes, title: str, performer: str = "EnTurk_CSR") -> dict:
        return await self._call("sendAudio", {"chat_id": chat_id, "title": title, "performer": performer},
                                files={"audio": ("enturk.mp3", audio, "audio/mpeg")})

    async def send_poll(self, chat_id, question: str, options: list[str], correct: int,
                        explanation: str = "", anonymous: bool = True) -> dict:
        """Quiz (viktorina) — QuizBot'dagi kabi: bitta to'g'ri javob va izoh."""
        base = {"chat_id": chat_id, "question": question, "options": [{"text": o} for o in options],
                "type": "quiz", "explanation": explanation or None, "is_anonymous": anonymous}
        # Bot API 10+: correct_option_ids; eski versiyalar: correct_option_id
        variants = [{"correct_option_ids": [correct]}, {"correct_option_id": correct}]
        if getattr(self, "_poll_variant", None) == 1:
            variants.reverse()
        last: TelegramError | None = None
        for i, v in enumerate(variants):
            try:
                res = await self._call("sendPoll", {**base, **v})
                self._poll_variant = 1 if "correct_option_id" in v else 0
                return res
            except TelegramError as exc:
                last = exc
                msg = str(exc).lower()
                if "correct" in msg or "option" in msg or "quiz" in msg:
                    log.info("sendPoll shakli #%s mos kelmadi: %s", i, exc)
                    continue
                raise
        raise last or TelegramError("sendPoll: yuborilmadi")

    async def edit_text(self, chat_id, message_id: int, text: str) -> None:
        try:
            await self._call("editMessageText", {"chat_id": chat_id, "message_id": message_id,
                                                 "text": text, "parse_mode": "HTML"})
        except TelegramError as exc:
            log.warning("Xabar tahrirlanmadi: %s", exc)

    async def answer_callback(self, callback_id: str, text: str = "", alert: bool = False) -> None:
        try:
            await self._call("answerCallbackQuery", {"callback_query_id": callback_id, "text": text,
                                                     "show_alert": alert}, attempts=1)
        except TelegramError as exc:
            log.info("Callback javobi yuborilmadi: %s", exc)

    async def get_updates(self, offset: int | None, timeout: int) -> list[dict]:
        return await self._call("getUpdates", {"offset": offset, "timeout": timeout,
                                               "allowed_updates": ["message", "callback_query"]})

    async def get_me(self) -> dict:
        return await self._call("getMe")

    async def get_chat_member(self, chat_id, user_id: int) -> dict:
        return await self._call("getChatMember", {"chat_id": chat_id, "user_id": user_id})
