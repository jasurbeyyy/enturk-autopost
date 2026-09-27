"""6-agent: Admin bot — jadval, adminga ko'rsatish, "Qayta ishlash" tugmasi va kanalga chiqarish."""
from __future__ import annotations

import asyncio
import html
import json
import logging
from datetime import datetime, timedelta, timezone

from telegram import (BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update)
from telegram.constants import ParseMode
from telegram.error import TelegramError
from telegram.ext import (Application, ApplicationBuilder, CallbackQueryHandler, CommandHandler,
                          ContextTypes, Defaults)

from . import planner
from .db import DB, parse_iso
from .pipeline import Pipeline
from .settings import Settings

log = logging.getLogger(__name__)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Coordinator:
    def __init__(self, s: Settings, db: DB, pipeline: Pipeline):
        self.s, self.db, self.pipeline = s, db, pipeline
        self.app: Application | None = None
        self.gen_before = int(s.cfg.get("generation_minutes_before", 40))
        self.prev_before = int(s.cfg.get("preview_minutes_before", 10))
        self.grace = int(s.cfg.get("late_publish_grace_minutes", 180))
        self._pub_lock = asyncio.Lock()
        self._publish_retries: dict[int, int] = {}

    # ================= ilova =================
    def build_app(self) -> Application:
        app = (ApplicationBuilder().token(self.s.bot_token)
               .defaults(Defaults(tzinfo=self.s.tz))
               .read_timeout(30).write_timeout(90).connect_timeout(20)
               .concurrent_updates(True)
               .post_init(self._post_init).build())
        app.add_handler(CommandHandler("start", self.cmd_start))
        app.add_handler(CommandHandler("holat", self.cmd_status))
        app.add_handler(CommandHandler("sinov", self.cmd_test))
        app.add_handler(CommandHandler("jadval", self.cmd_schedule))
        app.add_handler(CommandHandler("pauza", self.cmd_pause))
        app.add_handler(CommandHandler("davom", self.cmd_resume))
        app.add_handler(CallbackQueryHandler(self.on_button, pattern=r"^(regen|now):\d+$"))
        app.add_error_handler(self.on_error)
        self.app = app
        return app

    @property
    def admin(self) -> int:
        return self.s.admin_ids[0]

    async def _post_init(self, app: Application) -> None:
        await app.bot.set_my_commands([
            BotCommand("holat", "Bugungi postlar holati"),
            BotCommand("jadval", "Haftalik jadval"),
            BotCommand("sinov", "Sinov posti: /sinov yangi_sozlar"),
            BotCommand("pauza", "Avtomatik postlarni to'xtatish"),
            BotCommand("davom", "Avtomatik postlarni davom ettirish"),
        ])
        for hhmm in planner.slot_times(self.s.cfg):
            t = planner.generation_time(hhmm, self.gen_before, self.s.tz)
            app.job_queue.run_daily(self.job_generate, time=t, data=hhmm, name=f"gen-{hhmm}")
            log.info("Jadval: %s posti %s da tayyorlanadi", hhmm, t.strftime("%H:%M"))
        # tiklash bot to'liq ishga tushgandan keyin bajariladi
        app.job_queue.run_once(self._job_recover, when=3, name="recover")

    async def _job_recover(self, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        await self._recover()

    # ================= jadval bo'yicha =================
    def _paused(self) -> bool:
        return self.db.get_kv("paused", "0") == "1"

    async def job_generate(self, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        await self._start_slot(ctx.job.data)

    async def _start_slot(self, hhmm: str) -> None:
        slot = planner.next_slot_after(utcnow(), hhmm, self.s.tz)
        if self._paused():
            log.info("Pauza: %s o'tkazib yuborildi", slot)
            return
        entry = planner.entry_for(self.s.cfg, slot)
        if not entry:
            return
        if self.db.active_for_slot(slot):
            log.info("%s uchun post allaqachon bor", slot)
            return
        pt = self.s.post_type(entry["type"])
        draft_id = self.db.create_draft(slot_at=slot, post_type=entry["type"], lang=pt.get("lang", "tr"))
        log.info("Tayyorlash boshlandi: #%s %s %s", draft_id, entry["type"], slot)
        self.app.create_task(self.produce(draft_id))

    async def produce(self, draft_id: int, avoid: list[str] | None = None,
                      exclude_style: str | None = None) -> None:
        d = self.db.get(draft_id)
        try:
            r = await self.pipeline.run(d["post_type"], now=utcnow(), avoid_topics=avoid,
                                        exclude_style=exclude_style)
        except Exception as exc:  # noqa: BLE001
            log.exception("Post #%s tayyorlanmadi", draft_id)
            self.db.update(draft_id, status="failed", error=str(exc)[:1000])
            await self._notify_failure(draft_id, exc)
            return
        img = self.s.media_dir / f"{draft_id}.jpg"
        aud = self.s.media_dir / f"{draft_id}.mp3"
        img.write_bytes(r.image)
        if r.audio:
            aud.write_bytes(r.audio)
        self.db.update(draft_id, level=r.level, style_id=r.style_id, topic=r.topic, title=r.title,
                       caption=r.caption_html, image_path=str(img), audio_path=str(aud) if r.audio else None,
                       audio_title=r.audio_title, items=r.items, sources=r.sources, qa=r.qa,
                       status="ready")
        d = self.db.get(draft_id)
        if d["is_test"] or d["parent_id"]:
            when = utcnow()
        else:
            when = planner.preview_at(parse_iso(d["slot_at"]), self.prev_before, utcnow())
        self._schedule(self.job_preview, when, draft_id, f"prev-{draft_id}")

    def _schedule(self, cb, when: datetime, draft_id: int, name: str) -> None:
        for j in self.app.job_queue.get_jobs_by_name(name):
            j.schedule_removal()
        if when <= utcnow() + timedelta(seconds=2):
            when = utcnow() + timedelta(seconds=2)
        self.app.job_queue.run_once(cb, when=when, data=draft_id, name=name)

    def _unschedule(self, *names: str) -> None:
        for name in names:
            for j in self.app.job_queue.get_jobs_by_name(name):
                j.schedule_removal()

    # ================= adminga ko'rsatish =================
    async def job_preview(self, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        await self.send_preview(ctx.job.data)

    def _control_text(self, d: dict, pub: datetime | None, note: str = "") -> str:
        tz = self.s.tz
        slot = parse_iso(d["slot_at"]).astimezone(tz)
        pt = self.s.post_type(d["post_type"])
        style = next((st["name"] for st in self.s.styles if st["id"] == d.get("style_id")), d.get("style_id"))
        qa = json.loads(d.get("qa_json") or "{}")
        score = qa.get("score")
        head = "🧪 <b>SINOV POSTI</b> — avtomatik chiqmaydi" if d["is_test"] else "📋 <b>Navbatdagi post</b>"
        lines = [head,
                 f"🗓 {planner.DAY_NAMES_UZ[slot.weekday()]}, {slot:%H:%M} · {html.escape(pt['title'])} · {d.get('level') or ''}",
                 f"📚 Mavzu: {html.escape(d.get('topic') or '')}",
                 f"🎨 Uslub: {html.escape(str(style))}",
                 f"🧐 Sifat nazorati: ✅ o'tdi" + (f" ({score}/10)" if score else "")]
        if qa.get("exam"):
            lines.append(f"📝 Imtihon: {html.escape(qa['exam'])}")
        if pub and not d["is_test"]:
            lines += ["", f"⏰ Kanalga chiqish: <b>{pub.astimezone(tz):%H:%M}</b>",
                      "Hech narsa bosmasangiz, post shu vaqtda o'zi chiqadi."]
        if note:
            lines += ["", note]
        return "\n".join(lines)

    def _keyboard(self, d: dict) -> InlineKeyboardMarkup:
        now_label = "✅ Kanalga chiqarish" if d["is_test"] else "✅ Hozir chiqarish"
        return InlineKeyboardMarkup([[
            InlineKeyboardButton("🔄 Qayta ishlash", callback_data=f"regen:{d['id']}"),
            InlineKeyboardButton(now_label, callback_data=f"now:{d['id']}"),
        ]])

    async def send_preview(self, draft_id: int) -> None:
        d = self.db.get(draft_id)
        if not d or d["status"] != "ready":
            return
        bot = self.app.bot
        try:
            with open(d["image_path"], "rb") as f:
                await bot.send_photo(self.admin, photo=f, caption=d["caption"], parse_mode=ParseMode.HTML)
            if d.get("audio_path"):
                with open(d["audio_path"], "rb") as f:
                    await bot.send_audio(self.admin, audio=f, title=d["audio_title"] or "Talaffuz",
                                         performer="EnTurk_CSR", filename=f"enturk_{draft_id}.mp3")
        except TelegramError as exc:
            log.exception("Preview yuborilmadi #%s", draft_id)
            self.db.update(draft_id, status="failed", error=f"preview: {exc}")
            await self._notify_failure(draft_id, exc)
            return
        pub = None if d["is_test"] else planner.publish_at(parse_iso(d["slot_at"]), utcnow(), self.prev_before)
        msg = await bot.send_message(self.admin, self._control_text(d, pub),
                                     parse_mode=ParseMode.HTML, reply_markup=self._keyboard(d))
        self.db.update(draft_id, status="previewed", publish_at=pub, control_chat_id=msg.chat_id,
                       control_msg_id=msg.message_id)
        if pub:
            self._schedule(self.job_publish, pub, draft_id, f"pub-{draft_id}")
            log.info("#%s adminga ko'rsatildi, chiqish: %s", draft_id, pub.astimezone(self.s.tz))

    # ================= kanalga chiqarish =================
    async def job_publish(self, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        await self.publish(ctx.job.data)

    async def publish(self, draft_id: int) -> bool:
        async with self._pub_lock:
            if not self.db.set_status_if(draft_id, ("previewed",), "publishing"):
                return False
        d = self.db.get(draft_id)
        bot = self.app.bot
        try:
            with open(d["image_path"], "rb") as f:
                m = await bot.send_photo(self.s.channel, photo=f, caption=d["caption"],
                                         parse_mode=ParseMode.HTML)
            if d.get("audio_path"):
                with open(d["audio_path"], "rb") as f:
                    await bot.send_audio(self.s.channel, audio=f, title=d["audio_title"] or "Talaffuz",
                                         performer="EnTurk_CSR", filename=f"enturk_{draft_id}.mp3")
        except TelegramError as exc:
            log.exception("Kanalga chiqmadi #%s", draft_id)
            self.db.update(draft_id, status="previewed", error=f"publish: {exc}")
            n = self._publish_retries.get(draft_id, 0) + 1
            self._publish_retries[draft_id] = n
            if n <= 3:
                self._schedule(self.job_publish, utcnow() + timedelta(minutes=2), draft_id, f"pub-{draft_id}")
            await self._safe_send(self.admin, f"⚠️ Post #{draft_id} kanalga chiqmadi: {html.escape(str(exc))}\n"
                                  + ("2 daqiqadan so'ng qayta urinaman." if n <= 3 else
                                     "Bot kanalda admin ekanini tekshiring."))
            return False
        self.db.update(draft_id, status="published", published_at=utcnow(), channel_msg_id=m.message_id)
        await self._edit_control(d, f"✅ <b>Kanalga chiqdi</b> — {utcnow().astimezone(self.s.tz):%H:%M}")
        log.info("#%s kanalga chiqdi", draft_id)
        return True

    # ================= tugmalar =================
    async def on_button(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        q = update.callback_query
        if q.from_user.id not in self.s.admin_ids:
            await q.answer("Ruxsat yo'q", show_alert=True)
            return
        action, sid = q.data.split(":")
        draft_id = int(sid)
        if action == "now":
            d = self.db.get(draft_id)
            if not d or d["status"] != "previewed":
                await q.answer("Bu post allaqachon chiqqan yoki almashtirilgan", show_alert=True)
                return
            await q.answer("Chiqarilmoqda…")
            await self.publish(draft_id)
        elif action == "regen":
            msg = await self.regenerate(draft_id)
            await q.answer(msg)

    async def regenerate(self, draft_id: int) -> str:
        d = self.db.get(draft_id)
        if not d:
            return "Post topilmadi"
        if d["status"] in ("published", "publishing"):
            return "Bu post allaqachon kanalga chiqqan"
        if d["status"] == "generating":
            return "Bu post hozir tayyorlanmoqda"
        if not self.db.set_status_if(draft_id, ("previewed", "ready", "failed"), "cancelled"):
            return "Bu postni qayta ishlab bo'lmaydi"
        self._unschedule(f"pub-{draft_id}", f"prev-{draft_id}")
        await self._edit_control(d, "🔄 <b>Qayta ishlanmoqda…</b>\nYangi post tayyor bo'lgach sizga yuboriladi.")
        new_id = self.db.create_draft(slot_at=parse_iso(d["slot_at"]), post_type=d["post_type"],
                                      lang=d["lang"], is_test=bool(d["is_test"]), parent_id=draft_id)
        avoid = self._topic_chain(draft_id)
        self.app.create_task(self.produce(new_id, avoid=avoid, exclude_style=d.get("style_id")))
        return "Qayta ishlanmoqda…"

    def _topic_chain(self, draft_id: int | None) -> list[str]:
        topics: list[str] = []
        while draft_id:
            d = self.db.get(draft_id)
            if not d:
                break
            if d.get("topic"):
                topics.append(d["topic"])
            draft_id = d.get("parent_id")
        return topics

    async def _edit_control(self, d: dict, note: str) -> None:
        if not d.get("control_msg_id"):
            return
        fresh = self.db.get(d["id"]) or d
        try:
            await self.app.bot.edit_message_text(
                chat_id=d["control_chat_id"], message_id=d["control_msg_id"],
                text=self._control_text(fresh, None, note), parse_mode=ParseMode.HTML, reply_markup=None)
        except TelegramError as exc:
            log.warning("Boshqaruv xabari tahrirlanmadi: %s", exc)

    async def _notify_failure(self, draft_id: int, exc: Exception) -> None:
        d = self.db.get(draft_id)
        slot = parse_iso(d["slot_at"]).astimezone(self.s.tz)
        pt = self.s.post_type(d["post_type"])
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Qayta urinish", callback_data=f"regen:{draft_id}")]])
        await self._safe_send(
            self.admin,
            f"⚠️ <b>{slot:%H:%M} posti tayyorlanmadi</b> ({html.escape(pt['title'])})\n"
            f"<code>{html.escape(str(exc)[:600])}</code>", reply_markup=kb)

    async def _safe_send(self, chat_id: int, text: str, **kw) -> None:
        try:
            await self.app.bot.send_message(chat_id, text, parse_mode=ParseMode.HTML, **kw)
        except TelegramError as exc:
            log.warning("Xabar yuborilmadi: %s", exc)

    # ================= qayta ishga tushganda tiklash =================
    async def _recover(self) -> None:
        now = utcnow()
        for d in self.db.by_status("generating"):
            log.info("Tiklash: #%s qayta tayyorlanadi", d["id"])
            self.app.create_task(self.produce(d["id"], avoid=self._topic_chain(d.get("parent_id"))))
        for d in self.db.by_status("ready"):
            when = now if (d["is_test"] or d["parent_id"]) else \
                planner.preview_at(parse_iso(d["slot_at"]), self.prev_before, now)
            self._schedule(self.job_preview, when, d["id"], f"prev-{d['id']}")
        for d in self.db.by_status("previewed"):
            if d["is_test"] or not d.get("publish_at"):
                continue
            pub = parse_iso(d["publish_at"])
            if pub < now - timedelta(minutes=self.grace):
                self.db.update(d["id"], status="expired")
                await self._edit_control(d, "⌛️ Bot o'chiq bo'lgani uchun vaqti o'tib ketdi — chiqarilmadi.")
                continue
            self._schedule(self.job_publish, pub, d["id"], f"pub-{d['id']}")
        for d in self.db.by_status("publishing"):
            self.db.update(d["id"], status="previewed")
            await self._safe_send(self.admin, f"⚠️ Post #{d['id']} chiqarilayotganda bot to'xtadi. "
                                  "Kanalni tekshiring; kerak bo'lsa pastdagi tugmani bosing.",
                                  reply_markup=self._keyboard(d))
        # ishga tushgan payt tayyorlash oynasiga to'g'ri kelgan postlar
        for hhmm in planner.slot_times(self.s.cfg):
            slot = planner.next_slot_after(now, hhmm, self.s.tz)
            if slot - now <= timedelta(minutes=self.gen_before):
                await self._start_slot(hhmm)

    # ================= buyruqlar =================
    def _is_admin(self, update: Update) -> bool:
        return bool(update.effective_user and update.effective_user.id in self.s.admin_ids)

    async def cmd_start(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        uid = update.effective_user.id
        if uid not in self.s.admin_ids:
            await update.message.reply_text(
                f"Salom! Sizning Telegram ID: <code>{uid}</code>\n"
                f"Admin bo'lish uchun bu raqamni .env fayldagi ADMIN_IDS ga yozing.", parse_mode=ParseMode.HTML)
            return
        await update.message.reply_text(
            "👋 EnTurk_CSR avtopost boti ishlayapti.\n\n"
            "/holat — bugungi postlar\n/jadval — haftalik jadval\n"
            "/sinov yangi_sozlar — sinov posti (kanalga chiqmaydi)\n"
            "/pauza, /davom — avtomatik rejimni to'xtatish / davom ettirish")

    async def cmd_status(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_admin(update):
            return
        tz = self.s.tz
        now = utcnow()
        lines = ["⏸ <b>Pauza yoqilgan</b>" if self._paused() else "▶️ Avtomatik rejim yoqilgan", ""]
        icons = {"generating": "⏳ tayyorlanmoqda", "ready": "🕓 tayyor", "previewed": "👀 sizda",
                 "published": "✅ chiqdi", "failed": "⚠️ xato", "cancelled": "🔄 almashtirildi",
                 "expired": "⌛️ o'tib ketdi", "publishing": "📤 chiqmoqda"}
        for hhmm in planner.slot_times(self.s.cfg):
            local = now.astimezone(tz)
            slot = datetime.combine(local.date(), planner.parse_hhmm(hhmm), tzinfo=tz)
            e = planner.entry_for(self.s.cfg, slot)
            if not e:
                continue
            rows = self.db.for_slot(slot)
            st = icons.get(rows[-1]["status"], rows[-1]["status"]) if rows else "—"
            lines.append(f"{hhmm} · {html.escape(self.s.post_type(e['type'])['title'])} · {st}")
        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)

    async def cmd_schedule(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_admin(update):
            return
        out = []
        for i, day in enumerate(planner.DAYS):
            items = self.s.cfg["weekly"].get(day, [])
            out.append(f"<b>{planner.DAY_NAMES_UZ[i]}</b>")
            for e in items:
                out.append(f"  {e['time']} — {html.escape(self.s.post_type(e['type'])['title'])}")
        await update.message.reply_text("\n".join(out), parse_mode=ParseMode.HTML)

    async def cmd_test(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_admin(update):
            return
        types = list(self.s.cfg["post_types"])
        if not ctx.args or ctx.args[0] not in types:
            await update.message.reply_text("Qaysi tur? Masalan: /sinov yangi_sozlar\n\nTurlar:\n" + "\n".join(types))
            return
        key = ctx.args[0]
        draft_id = self.db.create_draft(slot_at=utcnow(), post_type=key,
                                        lang=self.s.post_type(key).get("lang", "tr"), is_test=True)
        await update.message.reply_text("⏳ Sinov posti tayyorlanmoqda (2–5 daqiqa)…")
        self.app.create_task(self.produce(draft_id))

    async def cmd_pause(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_admin(update):
            return
        self.db.set_kv("paused", "1")
        await update.message.reply_text("⏸ Avtomatik postlar to'xtatildi. Davom ettirish: /davom\n"
                                        "(Allaqachon sizga ko'rsatilgan post baribir o'z vaqtida chiqadi.)")

    async def cmd_resume(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_admin(update):
            return
        self.db.set_kv("paused", "0")
        await update.message.reply_text("▶️ Avtomatik postlar davom etadi.")

    async def on_error(self, update: object, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        log.error("Bot xatosi", exc_info=ctx.error)


def run(s: Settings) -> None:
    from .eleven import ElevenClient
    from .gemini import GeminiClient
    if not s.bot_token or not s.admin_ids:
        raise SystemExit(".env: TELEGRAM_BOT_TOKEN va ADMIN_IDS to'ldirilishi kerak")
    db = DB(s.data_dir / "enturk.db")
    if s.mock:
        from .mock import FakeEleven, FakeGemini
        gemini, eleven = FakeGemini(), FakeEleven()
        log.warning("MOCK rejim: Gemini va ElevenLabs o'rniga soxta javoblar ishlatiladi")
    else:
        gemini = GeminiClient(s.gemini_key, s.cfg["models"]["text"], s.cfg["models"]["image"])
        eleven = ElevenClient(s.eleven_key, s.cfg["elevenlabs"]["model_id"])
    coord = Coordinator(s, db, Pipeline(s, db, gemini, eleven))
    app = coord.build_app()
    app.run_polling(allowed_updates=["message", "callback_query"])
