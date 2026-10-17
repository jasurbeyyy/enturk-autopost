"""GitHub Actions rejimi: kunlik testlar uchun to'liq sikl.

  tayyorlash → (vaqtidan 10 daqiqa oldin) adminga savol-javoblar → tugmalarni kutish
  → 🔄 bosilsa: yangi testlar → yana ko'rsatish
  → hech narsa bosilmasa yoki ✅ bosilsa: kanalga kirish posti + 10 ta quiz
"""
from __future__ import annotations

import asyncio
import html
import logging
import os
from datetime import datetime, timedelta

from . import oneshot, planner
from .db import DB, parse_iso
from .gemini import GeminiClient
from .oneshot import SlotRunner, keyboard
from .quiz import (QUIZ_LANG, QUIZ_TYPE, QuizSet, make_quiz_set, poll_explanation, poll_options,
                   poll_question, preview_chunks, quiz_cfg)
from .settings import Settings
from .telegram_api import TelegramAPI, TelegramError

log = logging.getLogger(__name__)


class QuizRunner(SlotRunner):
    def __init__(self, s: Settings, db: DB, gemini: GeminiClient, tg: TelegramAPI):
        super().__init__(s, db, None, tg)  # type: ignore[arg-type]
        self.gemini = gemini
        self.qc = quiz_cfg(s)
        self.sleep = asyncio.sleep

    # ---------- qaysi kun? ----------
    def find_slot(self, now: datetime) -> datetime | None:  # type: ignore[override]
        if not self.qc.get("enabled", True):
            return None
        t = planner.parse_hhmm(str(self.qc["time"]))
        cands = []
        for day_shift in (-1, 0, 1):
            local = (now + timedelta(days=day_shift)).astimezone(self.s.tz)
            slot = datetime.combine(local.date(), t, tzinfo=self.s.tz)
            if not (now - oneshot.WINDOW_AFTER <= slot <= now + oneshot.WINDOW_BEFORE):
                continue
            if planner.DAYS[slot.weekday()] not in self.qc["days"]:
                continue
            done = [d for d in self.db.for_slot(slot)
                    if d["post_type"] == QUIZ_TYPE and d["status"] in ("published", "expired")]
            if not done:
                cands.append(slot)
        return min(cands) if cands else None

    # ---------- matnlar ----------
    def quiz_control_text(self, d: dict, qs: QuizSet, pub: datetime | None, note: str = "") -> str:
        slot = parse_iso(d["slot_at"]).astimezone(self.s.tz)
        head = "🧪 <b>SINOV TESTLARI</b> — avtomatik chiqmaydi" if d["is_test"] else "🧠 <b>Kunlik testlar</b>"
        lines = [head,
                 f"🗓 {planner.DAY_NAMES_UZ[slot.weekday()]}, {slot:%H:%M} · {qs.level} · "
                 f"{len(qs.questions)} ta savol",
                 f"📘 {html.escape(qs.grammar_focus or 'grammatika')}",
                 f"📗 {html.escape(qs.vocab_theme or 'kelime bilgisi')}",
                 "🧐 Sifat nazorati: ✅ har bir savol 4 bosqichdan o'tdi "
                 "(kod, muharrir, tekshiruvchi, mustaqil yechuvchi)"]
        if pub and not d["is_test"]:
            lines += ["", f"⏰ Kanalga chiqish: <b>{pub.astimezone(self.s.tz):%H:%M}</b>",
                      "Ko'rib chiqish shart emas: hech narsa bosmasangiz, testlar shu vaqtda o'zi chiqadi."]
        elif d["is_test"]:
            lines += ["", "Tugmalar 30 daqiqa ishlaydi."]
        if note:
            lines += ["", note]
        return "\n".join(lines)

    # ---------- asosiy sikl ----------
    async def run(self, *, test: bool = False) -> bool:  # type: ignore[override]
        if not test and (os.getenv("PAUSED", "0") == "1" or self.db.get_kv("paused", "0") == "1"):
            log.info("Pauza yoqilgan")
            return False
        now = oneshot.utcnow()
        if test:
            slot = now
        else:
            slot = self.find_slot(now)
            if slot is None:
                log.info("Yaqin orada chiqarilmagan test yo'q")
                return False
        log.info("Kunlik testlar, vaqti %s", slot.astimezone(self.s.tz))
        await self._skip_old_updates()

        parent: int | None = None
        avoid: list[str] = []
        level: str | None = None
        failures = 0
        while True:
            did = self.db.create_draft(slot_at=slot, post_type=QUIZ_TYPE, lang=QUIZ_LANG, is_test=test,
                                       parent_id=parent)
            try:
                qs = await make_quiz_set(self.s, self.db, self.gemini, now=oneshot.utcnow(),
                                         avoid_questions=avoid, level=level)
            except Exception as exc:  # noqa: BLE001
                log.exception("Testlarni tayyorlashda xato")
                failures += 1
                self.db.update(did, status="failed", error=str(exc)[:1000])
                await self.tg.send_message(
                    self.admin,
                    f"⚠️ <b>{slot.astimezone(self.s.tz):%H:%M} testlari tayyorlanmadi</b>\n"
                    f"<code>{html.escape(str(exc)[:500])}</code>\n\n"
                    + ("Yana bir marta urinib ko'raman…" if failures < 2 else
                       "Bugungi testlar o'tkazib yuborildi. Ertaga jadval bo'yicha tayyorlanadi."))
                if failures >= 2:
                    return True
                continue
            level = qs.level
            self.db.update(did, level=qs.level, topic=f"{qs.grammar_focus} | {qs.vocab_theme}",
                           title="Kunlik test", caption=qs.intro_caption, items=qs.keys, qa=qs.to_json(),
                           status="ready")
            d = self.db.get(did)

            # 1) ko'rsatish vaqtini kutish
            if parent is None and not test:
                await self.listen(None, planner.preview_at(slot, self.prev_before, oneshot.utcnow()))

            # 2) adminga ko'rsatish
            await self.tg.send_photo(self.admin, qs.image, qs.intro_caption)
            if test:
                await self.send_polls(self.admin, qs, admin=True)
            else:
                for chunk in preview_chunks(qs):
                    await self.tg.send_message(self.admin, chunk)
            pub = None if test else planner.publish_at(slot, oneshot.utcnow(), self.prev_before)
            ctrl = await self.tg.send_message(self.admin, self.quiz_control_text(d, qs, pub), keyboard(did, test))
            self.db.update(did, status="previewed", publish_at=pub, control_chat_id=ctrl["chat"]["id"],
                           control_msg_id=ctrl["message_id"])
            oneshot._notice(f"Testlar adminga ko'rsatildi: #{did} {qs.level}")

            # 3) tugmalarni kutish
            action = await self.listen(did, pub or oneshot.utcnow() + oneshot.TEST_LISTEN)
            d = self.db.get(did)
            if action == "regen":
                self.db.update(did, status="cancelled")
                await self.tg.edit_text(ctrl["chat"]["id"], ctrl["message_id"], self.quiz_control_text(
                    d, qs, None, "🔄 <b>Qayta ishlanmoqda…</b>\nYangi testlar tayyor bo'lgach sizga yuboriladi."))
                parent = did
                avoid += [q["question"] for q in qs.questions]
                continue
            if test and action == "timeout":
                self.db.update(did, status="cancelled")
                await self.tg.edit_text(ctrl["chat"]["id"], ctrl["message_id"],
                                        self.quiz_control_text(d, qs, None, "⌛️ Sinov tugadi."))
                return True

            # 4) kanalga chiqarish
            await self.publish_quiz(did, qs, ctrl)
            return True

    async def send_polls(self, chat_id, qs: QuizSet, *, admin: bool = False) -> int:
        """Quizlarni ketma-ket yuboradi. Yuborilganlar sonini qaytaradi."""
        total = len(qs.questions)
        gap = float(self.qc.get("poll_interval_seconds", 3))
        sent = 0
        for i, q in enumerate(qs.questions, 1):
            for attempt in range(3):
                try:
                    await self.tg.send_poll(chat_id, poll_question(q, i, total), poll_options(q),
                                            q["correct_index"], poll_explanation(q), anonymous=True)
                    break
                except TelegramError as exc:
                    if admin and "anonym" in str(exc).lower():
                        await self.tg.send_poll(chat_id, poll_question(q, i, total), poll_options(q),
                                                q["correct_index"], poll_explanation(q), anonymous=False)
                        break
                    log.warning("Quiz %s yuborilmadi (%s): %s", i, attempt + 1, exc)
                    if attempt == 2:
                        raise
                    await self.sleep(20)
            sent += 1
            if i < total:
                await self.sleep(gap)
        return sent

    async def publish_quiz(self, did: int, qs: QuizSet, ctrl: dict) -> None:
        self.db.update(did, status="publishing")
        try:
            m = None
            for attempt in range(3):
                try:
                    m = await self.tg.send_photo(self.s.channel, qs.image, qs.intro_caption)
                    break
                except TelegramError as exc:
                    log.warning("Kirish posti chiqmadi (%s): %s", attempt + 1, exc)
                    if attempt == 2:
                        raise
                    await self.sleep(60)
            await self.sleep(2)
            sent = 0
            try:
                sent = await self.send_polls(self.s.channel, qs)
            except TelegramError as exc:
                self.db.update(did, status="published", published_at=oneshot.utcnow(),
                               channel_msg_id=m["message_id"], error=f"polls: {exc}")
                await self.tg.send_message(self.admin, f"⚠️ Testlarning bir qismi kanalga chiqmadi: "
                                                       f"{html.escape(str(exc))}")
                return
        except TelegramError as exc:
            self.db.update(did, status="failed", error=f"publish: {exc}")
            await self.tg.send_message(self.admin, f"⚠️ Testlar kanalga chiqmadi: {html.escape(str(exc))}\n"
                                                   "Bot kanalda admin ekanini tekshiring.")
            return
        self.db.update(did, status="published", published_at=oneshot.utcnow(), channel_msg_id=m["message_id"])
        d = self.db.get(did)
        await self.tg.edit_text(ctrl["chat"]["id"], ctrl["message_id"], self.quiz_control_text(
            d, qs, None, f"✅ <b>Kanalga chiqdi</b> — {oneshot.utcnow().astimezone(self.s.tz):%H:%M}, "
                         f"{sent} ta test"))
        log.info("Testlar kanalga chiqdi: #%s", did)
        oneshot._notice(f"Testlar kanalga chiqdi: #{did} {qs.level}, {sent} ta")
