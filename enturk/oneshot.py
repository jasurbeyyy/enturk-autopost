"""GitHub Actions rejimi: bitta post uchun to'liq sikl bir marta ishga tushishda bajariladi.

  tayyorlash → (post vaqtidan 10 daqiqa oldin) adminga ko'rsatish → tugmalarni kutish
  → 🔄 bosilsa: yangi post, yana ko'rsatish, yana 10 daqiqa kutish
  → hech narsa bosilmasa yoki ✅ bosilsa: kanalga chiqarish
"""
from __future__ import annotations

import asyncio
import html
import json
import logging
import os
from datetime import datetime, timedelta, timezone

from . import planner
from .db import DB, parse_iso
from .pipeline import Pipeline
from .settings import Settings
from .telegram_api import TelegramAPI, TelegramError

log = logging.getLogger(__name__)

# GitHub kechiksa ham post yo'qolmasligi uchun: shu oraliqdagi chiqarilmagan post olinadi
WINDOW_BEFORE = timedelta(minutes=120)
WINDOW_AFTER = timedelta(minutes=60)
TEST_LISTEN = timedelta(minutes=30)


def _notice(msg: str) -> None:
    if os.getenv("GITHUB_ACTIONS") == "true":
        print(f"::notice title=EnTurk::{msg.replace(chr(10), ' ')}", flush=True)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def keyboard(draft_id: int, test: bool) -> dict:
    return {"inline_keyboard": [[
        {"text": "🔄 Qayta ishlash", "callback_data": f"regen:{draft_id}"},
        {"text": "✅ Kanalga chiqarish" if test else "✅ Hozir chiqarish", "callback_data": f"now:{draft_id}"},
    ]]}


class SlotRunner:
    def __init__(self, s: Settings, db: DB, pipeline: Pipeline, tg: TelegramAPI):
        self.s, self.db, self.pipeline, self.tg = s, db, pipeline, tg
        self.prev_before = int(s.cfg.get("preview_minutes_before", 10))
        self.offset: int | None = None

    @property
    def admin(self) -> int:
        return self.s.admin_ids[0]

    # ---------- qaysi post? ----------
    def find_slot(self, now: datetime) -> tuple[datetime, dict] | None:
        cands = []
        for hhmm in planner.slot_times(self.s.cfg):
            for day_shift in (-1, 0, 1):
                local = (now + timedelta(days=day_shift)).astimezone(self.s.tz)
                slot = datetime.combine(local.date(), planner.parse_hhmm(hhmm), tzinfo=self.s.tz)
                if not (now - WINDOW_AFTER <= slot <= now + WINDOW_BEFORE):
                    continue
                entry = planner.entry_for(self.s.cfg, slot)
                if not entry:
                    continue
                done = [d for d in self.db.for_slot(slot) if d["status"] in ("published", "expired")]
                if done:
                    continue
                cands.append((slot, entry))
        cands.sort(key=lambda x: x[0])
        return cands[0] if cands else None

    # ---------- Telegram tugmalari ----------
    async def _skip_old_updates(self) -> None:
        ups = await self.tg.get_updates(offset=-1, timeout=0)
        if ups:
            self.offset = ups[-1]["update_id"] + 1

    async def listen(self, draft_id: int | None, until: datetime) -> str:
        """`until` gacha tugmani kutadi. Qaytaradi: 'regen' | 'now' | 'timeout'."""
        while True:
            remaining = (until - utcnow()).total_seconds()
            if remaining <= 0:
                return "timeout"
            try:
                ups = await self.tg.get_updates(self.offset, timeout=int(min(50, max(1, remaining))))
            except TelegramError as exc:
                log.warning("getUpdates xatosi: %s", exc)
                await asyncio.sleep(5)
                continue
            for u in ups:
                self.offset = u["update_id"] + 1
                msg = u.get("message")
                if msg and (msg.get("text") or "").startswith("/start"):
                    await self.tg.send_message(msg["chat"]["id"],
                                               f"Sizning Telegram ID: <code>{msg['from']['id']}</code>")
                    continue
                cq = u.get("callback_query")
                if not cq:
                    continue
                if cq["from"]["id"] not in self.s.admin_ids:
                    await self.tg.answer_callback(cq["id"], "Ruxsat yo'q", alert=True)
                    continue
                try:
                    action, sid = cq.get("data", "").split(":")
                    target = int(sid)
                except ValueError:
                    continue
                if draft_id is None or target != draft_id:
                    await self.tg.answer_callback(cq["id"], "Bu post eskirgan yoki allaqachon hal bo'lgan",
                                                  alert=True)
                    continue
                await self.tg.answer_callback(cq["id"], "Qayta ishlanmoqda…" if action == "regen"
                                              else "Chiqarilmoqda…")
                return action

    # ---------- matnlar ----------
    def control_text(self, d: dict, pub: datetime | None, note: str = "") -> str:
        tz = self.s.tz
        slot = parse_iso(d["slot_at"]).astimezone(tz)
        pt = self.s.post_type(d["post_type"])
        style = next((st["name"] for st in self.s.styles if st["id"] == d.get("style_id")), d.get("style_id"))
        qa = json.loads(d.get("qa_json") or "{}")
        head = "🧪 <b>SINOV POSTI</b> — avtomatik chiqmaydi" if d["is_test"] else "📋 <b>Navbatdagi post</b>"
        lines = [head,
                 f"🗓 {planner.DAY_NAMES_UZ[slot.weekday()]}, {slot:%H:%M} · {html.escape(pt['title'])} · "
                 f"{d.get('level') or ''}",
                 f"📚 Mavzu: {html.escape(d.get('topic') or '')}",
                 f"🎨 Uslub: {html.escape(str(style))}",
                 "🧐 Sifat nazorati: ✅ o'tdi" + (f" ({qa['score']}/10)" if qa.get("score") else "")]
        if qa.get("exam"):
            lines.append(f"📝 Imtihon: {html.escape(qa['exam'])}")
        if pub and not d["is_test"]:
            lines += ["", f"⏰ Kanalga chiqish: <b>{pub.astimezone(tz):%H:%M}</b>",
                      "Hech narsa bosmasangiz, post shu vaqtda o'zi chiqadi."]
        elif d["is_test"]:
            lines += ["", "Tugmalar 30 daqiqa ishlaydi."]
        if note:
            lines += ["", note]
        return "\n".join(lines)

    # ---------- asosiy sikl ----------
    async def run(self, *, test_type: str | None = None) -> None:
        if not test_type and (os.getenv("PAUSED", "0") == "1" or self.db.get_kv("paused", "0") == "1"):
            log.info("Pauza yoqilgan")
            return
        now = utcnow()
        if test_type:
            slot, post_type, test = now, test_type, True
        else:
            found = self.find_slot(now)
            if not found:
                log.info("Yaqin orada chiqarilmagan post yo'q — tugadi")
                return
            slot, entry = found
            post_type, test = entry["type"], False
        pt = self.s.post_type(post_type)
        log.info("Post: %s, vaqti %s", post_type, slot.astimezone(self.s.tz))
        await self._skip_old_updates()

        parent: int | None = None
        avoid: list[str] = []
        exclude_style: str | None = None
        failures = 0
        while True:
            did = self.db.create_draft(slot_at=slot, post_type=post_type, lang=pt.get("lang", "tr"),
                                       is_test=test, parent_id=parent)
            try:
                r = await self.pipeline.run(post_type, now=utcnow(), avoid_topics=avoid,
                                            exclude_style=exclude_style)
            except Exception as exc:  # noqa: BLE001
                log.exception("Tayyorlashda xato")
                failures += 1
                self.db.update(did, status="failed", error=str(exc)[:1000])
                await self.tg.send_message(
                    self.admin,
                    f"⚠️ <b>{slot.astimezone(self.s.tz):%H:%M} posti tayyorlanmadi</b> "
                    f"({html.escape(pt['title'])})\n<code>{html.escape(str(exc)[:500])}</code>\n\n"
                    + ("Yana bir marta urinib ko'raman…" if failures < 2 else
                       "Bu post o'tkazib yuborildi. Keyingisi jadval bo'yicha tayyorlanadi."))
                if failures >= 2:
                    return
                continue
            self.db.update(did, level=r.level, style_id=r.style_id, topic=r.topic, title=r.title,
                           caption=r.caption_html, audio_title=r.audio_title, items=r.items,
                           sources=r.sources, qa=r.qa, status="ready")
            d = self.db.get(did)

            # 1) adminga ko'rsatish vaqtini kutish (birinchi post uchun)
            if parent is None and not test:
                await self.listen(None, planner.preview_at(slot, self.prev_before, utcnow()))

            # 2) ko'rsatish
            await self.tg.send_photo(self.admin, r.image, r.caption_html)
            if r.audio:
                await self.tg.send_audio(self.admin, r.audio, r.audio_title)
            pub = None if test else planner.publish_at(slot, utcnow(), self.prev_before)
            ctrl = await self.tg.send_message(self.admin, self.control_text(d, pub), keyboard(did, test))
            self.db.update(did, status="previewed", publish_at=pub, control_chat_id=ctrl["chat"]["id"],
                           control_msg_id=ctrl["message_id"])
            _notice(f"Adminga ko'rsatildi: #{did} {post_type} | {r.level} | {r.style_id} | {r.topic}")

            # 3) tugmalarni kutish
            action = await self.listen(did, pub or utcnow() + TEST_LISTEN)
            d = self.db.get(did)
            if action == "regen":
                self.db.update(did, status="cancelled")
                await self.tg.edit_text(ctrl["chat"]["id"], ctrl["message_id"], self.control_text(
                    d, None, "🔄 <b>Qayta ishlanmoqda…</b>\nYangi post tayyor bo'lgach sizga yuboriladi."))
                parent, exclude_style = did, r.style_id
                avoid.append(r.topic)
                continue
            if test and action == "timeout":
                self.db.update(did, status="cancelled")
                await self.tg.edit_text(ctrl["chat"]["id"], ctrl["message_id"],
                                        self.control_text(d, None, "⌛️ Sinov tugadi."))
                return

            # 4) kanalga chiqarish
            await self.publish(did, r, ctrl)
            return

    async def publish(self, did: int, r, ctrl: dict) -> None:
        self.db.update(did, status="publishing")
        for attempt in range(3):
            try:
                m = await self.tg.send_photo(self.s.channel, r.image, r.caption_html)
                if r.audio:
                    await self.tg.send_audio(self.s.channel, r.audio, r.audio_title)
                break
            except TelegramError as exc:
                log.warning("Kanalga chiqmadi (%s): %s", attempt + 1, exc)
                if attempt == 2:
                    self.db.update(did, status="failed", error=f"publish: {exc}")
                    await self.tg.send_message(self.admin, f"⚠️ Post kanalga chiqmadi: {html.escape(str(exc))}\n"
                                                           "Bot kanalda admin ekanini tekshiring.")
                    return
                await asyncio.sleep(60)
        self.db.update(did, status="published", published_at=utcnow(), channel_msg_id=m["message_id"])
        d = self.db.get(did)
        await self.tg.edit_text(ctrl["chat"]["id"], ctrl["message_id"], self.control_text(
            d, None, f"✅ <b>Kanalga chiqdi</b> — {utcnow().astimezone(self.s.tz):%H:%M}"))
        log.info("Kanalga chiqdi: #%s", did)
        _notice(f"Kanalga chiqdi: #{did} {d['post_type']} — {d.get('topic')}")
