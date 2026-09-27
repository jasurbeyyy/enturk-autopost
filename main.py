"""Ishga tushirish nuqtasi.

  python main.py                 — botni ishga tushirish (doimiy ishlaydi)
  python main.py --check         — kalitlar, bot, kanal va ovozlarni tekshirish
  python main.py --dry-run TUR   — bitta postni tayyorlab out/ papkasiga saqlash (Telegram'ga yubormaydi)
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler

import httpx

from enturk.settings import ROOT, Settings, load_settings


def setup_logging(s: Settings) -> None:
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    fh = RotatingFileHandler(s.data_dir / "bot.log", maxBytes=5_000_000, backupCount=3, encoding="utf-8")
    fh.setFormatter(fmt)
    root.handlers = [sh, fh]
    logging.getLogger("httpx").setLevel(logging.WARNING)


def apply_mock(s: Settings) -> None:
    voices = s.cfg["elevenlabs"]["voices"]
    for k, v in list(voices.items()):
        if not v or v.startswith("PUT_"):
            voices[k] = f"mock-{k.split('_')[1]}"


def clients(s: Settings):
    if s.mock:
        from enturk.mock import FakeEleven, FakeGemini
        return FakeGemini(), FakeEleven()
    from enturk.eleven import ElevenClient
    from enturk.gemini import GeminiClient
    return (GeminiClient(s.gemini_key, s.cfg["models"]["text"], s.cfg["models"]["image"]),
            ElevenClient(s.eleven_key, s.cfg["elevenlabs"]["model_id"]))


async def dry_run(s: Settings, type_key: str) -> None:
    from enturk.db import DB
    from enturk.pipeline import Pipeline
    gemini, eleven = clients(s)
    db = DB(s.data_dir / "dryrun.db")
    try:
        r = await Pipeline(s, db, gemini, eleven).run(type_key, now=datetime.now(timezone.utc))
    finally:
        await gemini.aclose()
        await eleven.aclose()
    out = ROOT / "out"
    out.mkdir(exist_ok=True)
    stem = f"{type_key}_{datetime.now():%Y%m%d_%H%M%S}"
    (out / f"{stem}.jpg").write_bytes(r.image)
    (out / f"{stem}.mp3").write_bytes(r.audio)
    (out / f"{stem}.html.txt").write_text(r.caption_html, encoding="utf-8")
    print(f"\n✅ Tayyor: out/{stem}.jpg / .mp3 / .html.txt")
    print(f"Daraja: {r.level} | Uslub: {r.style_id} | QA: {r.qa}\n")
    print(r.caption_html)


async def check(s: Settings) -> None:
    ok = True

    def res(good: bool, msg: str) -> None:
        nonlocal ok
        ok &= good
        print(("✅ " if good else "❌ ") + msg)

    async with httpx.AsyncClient(timeout=30) as http:
        # Telegram
        if not s.bot_token:
            res(False, "TELEGRAM_BOT_TOKEN yo'q")
        else:
            r = (await http.get(f"https://api.telegram.org/bot{s.bot_token}/getMe")).json()
            res(r.get("ok", False), f"Bot: @{r.get('result', {}).get('username')}" if r.get("ok") else f"Bot: {r}")
            if r.get("ok"):
                bot_id = r["result"]["id"]
                m = (await http.get(f"https://api.telegram.org/bot{s.bot_token}/getChatMember",
                                    params={"chat_id": s.channel, "user_id": bot_id})).json()
                st = m.get("result", {})
                good = st.get("status") == "administrator" and st.get("can_post_messages", False)
                res(good, f"Kanal {s.channel}: bot admin va post yoza oladi" if good
                    else f"Kanal {s.channel}: bot admin emas yoki post yozish huquqi yo'q ({m})")
        res(bool(s.admin_ids), f"ADMIN_IDS: {s.admin_ids}" if s.admin_ids else "ADMIN_IDS bo'sh (botga /start yozib ID'ni oling)")

        # Gemini
        if s.gemini_key:
            from enturk.gemini import GeminiClient, GeminiError
            g = GeminiClient(s.gemini_key, s.cfg["models"]["text"], s.cfg["models"]["image"])
            try:
                txt, _ = await g.generate_text("Answer briefly.", "Say 'merhaba' in one word.", json_mode=False)
                res(True, f"Gemini matn modeli ({s.cfg['models']['text']}): {txt.strip()[:30]}")
                txt, src = await g.generate_text("Answer briefly.", "What is today's date? One line.",
                                                 search=True, json_mode=False)
                res(True, f"Gemini + Google Search: {txt.strip()[:60]}")
            except GeminiError as exc:
                res(False, f"Gemini: {exc}")
            finally:
                await g.aclose()
        else:
            res(False, "GEMINI_API_KEY yo'q")

        # ElevenLabs
        if s.eleven_key:
            from enturk.eleven import ElevenClient, ElevenError
            e = ElevenClient(s.eleven_key, s.cfg["elevenlabs"]["model_id"])
            try:
                sub = await e.subscription()
                left = sub.get("character_limit", 0) - sub.get("character_count", 0)
                res(True, f"ElevenLabs: tarif {sub.get('tier')}, qolgan belgilar: {left}")
                for k, vid in s.cfg["elevenlabs"]["voices"].items():
                    if not vid or vid.startswith("PUT_"):
                        res(False, f"Ovoz {k}: config.yaml'da ID kiritilmagan")
                        continue
                    try:
                        v = await e.get_voice(vid)
                        res(True, f"Ovoz {k}: {v.get('name')}")
                    except ElevenError as exc:
                        res(False, f"Ovoz {k}: {exc}")
            except Exception as exc:  # noqa: BLE001
                res(False, f"ElevenLabs: {exc}")
            finally:
                await e.aclose()
        else:
            res(False, "ELEVENLABS_API_KEY yo'q")
    print("\nHammasi tayyor! 🎉" if ok else "\nYuqoridagi ❌ bandlarni tuzating.")


async def run_slot(s: Settings, test_type: str | None) -> None:
    """GitHub Actions rejimi: navbatdagi post (yoki sinov posti) uchun to'liq sikl."""
    from enturk.db import DB
    from enturk.oneshot import SlotRunner
    from enturk.pipeline import Pipeline
    from enturk.telegram_api import TelegramAPI
    if not s.bot_token or not s.admin_ids:
        raise SystemExit("TELEGRAM_BOT_TOKEN va ADMIN_IDS kerak (GitHub Secrets)")
    if test_type and test_type not in s.cfg["post_types"]:
        raise SystemExit(f"Noma'lum tur: {test_type}. Turlar: {', '.join(s.cfg['post_types'])}")
    gemini, eleven = clients(s)
    tg = TelegramAPI(s.bot_token)
    db = DB(s.data_dir / "enturk.db")
    try:
        await SlotRunner(s, db, Pipeline(s, db, gemini, eleven), tg).run(test_type=test_type)
    finally:
        await gemini.aclose()
        await eleven.aclose()
        await tg.aclose()


async def list_voices(s: Settings) -> None:
    from enturk.eleven import ElevenClient
    e = ElevenClient(s.eleven_key, s.cfg["elevenlabs"]["model_id"])
    try:
        voices = await e.list_voices()
    finally:
        await e.aclose()
    print(f"{'NOMI':28} {'VOICE_ID':24} TAVSIF")
    for v in voices:
        lab = v.get("labels") or {}
        desc = ", ".join(str(x) for x in (lab.get("gender"), lab.get("accent"), lab.get("language"),
                                          lab.get("age")) if x)
        print(f"{v.get('name', '')[:27]:28} {v.get('voice_id', ''):24} {desc}")


def main() -> None:
    p = argparse.ArgumentParser(description="EnTurk_CSR avtopost")
    p.add_argument("--check", action="store_true", help="kalitlar va ulanishlarni tekshirish")
    p.add_argument("--dry-run", metavar="TUR", help="postni out/ ga saqlash, Telegram'siz")
    p.add_argument("--slot", action="store_true", help="GitHub rejimi: navbatdagi post")
    p.add_argument("--test", metavar="TUR", help="GitHub rejimi: sinov posti")
    p.add_argument("--voices", action="store_true", help="ElevenLabs ovozlari ro'yxati")
    a = p.parse_args()
    s = load_settings()
    setup_logging(s)
    if s.mock:
        apply_mock(s)
    if a.check:
        asyncio.run(check(s))
    elif a.dry_run:
        asyncio.run(dry_run(s, a.dry_run))
    elif a.slot or a.test:
        asyncio.run(run_slot(s, a.test))
    elif a.voices:
        asyncio.run(list_voices(s))
    else:
        from enturk.bot import run
        run(s)


if __name__ == "__main__":
    main()
