"""Chiqmay qolgan postni qayta chiqarish (masalan, kanal nomi o'zgarganda "chat not found" bo'lsa).

Matn bazada saqlangan, shuning uchun post qayta yozilmaydi: rasm o'sha maket, sahna, rang va
tasma bilan qaytadan chiziladi (yangi logo bilan), imzo esa config.yaml'dagi yangi imzoga almashtiriladi.
"""
from __future__ import annotations

import html
import io
import json
import logging
import re
import zlib

from . import graphics
from .agents import illustrator
from .db import DB, parse_iso
from .oneshot import _notice, utcnow
from .settings import ROOT, Settings
from .telegram_api import TelegramAPI

log = logging.getLogger(__name__)

OLD_HANDLES = ["@EnTurk_CSR"]


def pick_draft(s: Settings, db: DB, draft_id: int | None) -> dict:
    if draft_id:
        d = db.get(draft_id)
        if not d:
            raise SystemExit(f"#{draft_id} raqamli post topilmadi")
        return d
    # Bugungi (Toshkent vaqti) chiqmay qolgan oxirgi post: har bir vaqt uchun eng oxirgi qoralama
    today = utcnow().astimezone(s.tz).date()
    rows = [r for r in db.by_status("failed")
            if not r["is_test"] and r["post_type"] != "kunlik_test" and r.get("caption")
            and parse_iso(r["slot_at"]).astimezone(s.tz).date() == today]
    published_slots = {r["slot_at"] for r in db.by_status("published")}
    rows = [r for r in rows if r["slot_at"] not in published_slots]
    if not rows:
        raise SystemExit("Bugun chiqmay qolgan post topilmadi")
    return max(rows, key=lambda r: (r["slot_at"], r["id"]))


def fix_caption(caption: str, signature: str) -> str:
    lines = caption.split("\n")
    for i, line in enumerate(lines):
        plain = re.sub(r"<[^>]+>", "", line).strip()
        if any(h in plain for h in OLD_HANDLES) and len(plain) < 40:
            lines[i] = signature
    out = "\n".join(lines)
    new_handle = (re.search(r"@\w+", signature) or [""])[0]
    for h in OLD_HANDLES:
        out = out.replace(h, new_handle)
    return out


def rebuild_image(s: Settings, d: dict) -> bytes:
    pt = s.post_type(d["post_type"])
    qa = json.loads(d.get("qa_json") or "{}")
    items = json.loads(d.get("items_json") or "[]")
    lang = d.get("lang") or pt.get("lang", "tr")
    title = graphics.clean_title(d.get("title") or d.get("topic") or "") or pt["title"].title()
    label = pt["title"].upper()
    sublabel = f"{d.get('level') or ''}  ·  TÜRKÇE"
    layout, scene, theme = qa.get("layout"), qa.get("scene"), qa.get("theme")
    img = None
    if layout in graphics.LAYOUTS and scene in graphics.SCENE_FUNCS and theme in graphics.THEMES:
        ctx = graphics.Ctx(
            title=title, label=label, sublabel=sublabel, items=[str(i) for i in items],
            emojis=graphics.valid_emojis(None, graphics.DEFAULT_EMOJIS.get(d["post_type"], ["📚", "💡", "✏️"])),
            scene=scene, lang=lang, seed=zlib.crc32(f"{title}|{d['post_type']}|{d.get('style_id')}".encode()),
            t=graphics.THEMES[theme])
        try:
            img = graphics.LAYOUTS[layout](ctx)
        except Exception:  # noqa: BLE001 — maket ma'lumot yetishmasa, oddiy yo'l bilan chiziladi
            log.warning("Asl maket chizilmadi, yangisi tanlanadi", exc_info=True)
            img = None
    if img is None:
        img, meta = graphics.render_post(post_type=d["post_type"], style_id=d.get("style_id") or "",
                                         lang=lang, title=title, label=label, sublabel=sublabel, items=items)
        theme = meta["theme"]
    b = io.BytesIO()
    img.save(b, "PNG")
    return illustrator.compose(b.getvalue(), logo_path=ROOT / "assets" / "logo_white.png", label=label,
                               sublabel=sublabel, band=int(s.cfg["brand"].get("band_height", 150)),
                               theme=theme or "red", footer=qa.get("footer") or "solid")


async def republish(s: Settings, db: DB, tg: TelegramAPI, draft_id: int | None) -> None:
    d = pick_draft(s, db, draft_id)
    if d["status"] == "published":
        raise SystemExit(f"#{d['id']} allaqachon kanalga chiqqan")
    caption = fix_caption(d["caption"], s.cfg["signature"])
    image = rebuild_image(s, d)
    slot = parse_iso(d["slot_at"]).astimezone(s.tz)
    log.info("Qayta chiqariladi: #%s (%s, %s) → %s", d["id"], d["post_type"], slot, s.channel)
    m = await tg.send_photo(s.channel, image, caption)
    db.update(d["id"], caption=caption, status="published", published_at=utcnow(),
              channel_msg_id=m["message_id"], error=None)
    note = (f"✅ <b>{slot:%H:%M} posti kanalga chiqdi</b> (qayta chiqarildi)\n"
            f"📚 {html.escape(d.get('topic') or '')}")
    for admin in s.admin_ids:
        try:
            await tg.send_message(admin, note)
        except Exception:  # noqa: BLE001
            log.warning("Adminga xabar yuborilmadi", exc_info=True)
    _notice(f"Qayta chiqarildi: #{d['id']} {d['post_type']} — {d.get('topic')}")
    print(f"Kanalga chiqdi: #{d['id']} → {s.channel} (xabar {m['message_id']})")

