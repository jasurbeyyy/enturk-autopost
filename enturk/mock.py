"""MOCK=1 rejimi uchun soxta Gemini va ElevenLabs (pul sarflamasdan oqimni sinash)."""
from __future__ import annotations

import io
import random
import re
from typing import Any

from PIL import Image, ImageDraw
from pydub.generators import Sine

SAMPLE_BODY = """🍳 <b>[{level}] OSHXONADA — 10 ta yangi so'z</b>

🥘 <b>tencere</b> — qozon
› Tencere ocakta.
🍳 <b>tava</b> — tova
› Tavada yumurta var.
🔪 <b>bıçak</b> — pichoq
› Bıçak çok keskin.
🥄 <b>kaşık</b> — qoshiq
› Bir kaşık şeker, lütfen.
🍴 <b>çatal</b> — sanchqi
› Çatal masada.
🍽 <b>tabak</b> — tarelka
› Tabaklar temiz.
🥛 <b>bardak</b> — stakan
› Bir bardak su içtim.
🔥 <b>ocak</b> — plita
› Ocağı kapat!
🍞 <b>fırın</b> — duxovka
› Ekmek fırında.
🧊 <b>buzdolabı</b> — muzlatkich
› Süt buzdolabında.

💡 buz (muz) + dolap (shkaf) = <b>buzdolabı</b>
🧩 "Qoshiq" turkchada qanday? → <tg-spoiler>kaşık</tg-spoiler>"""

WORDS = [("tencere", "Tencere ocakta."), ("tava", "Tavada yumurta var."), ("bıçak", "Bıçak çok keskin."),
         ("kaşık", "Bir kaşık şeker, lütfen."), ("çatal", "Çatal masada."), ("tabak", "Tabaklar temiz."),
         ("bardak", "Bir bardak su içtim."), ("ocak", "Ocağı kapat!"), ("fırın", "Ekmek fırında."),
         ("buzdolabı", "Süt buzdolabında.")]


class FakeGemini:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def aclose(self) -> None:
        pass

    async def generate_json(self, system: str, prompt: str, **kw: Any) -> tuple[Any, list[str]]:
        if "RESEARCH agent" in system:
            self.calls.append("research")
            return {"topic": "Oshxona buyumlari", "angle": "kundalik hayot",
                    "material": [w for w, _ in WORDS], "facts": [],
                    "image_idea": "a cozy Turkish kitchen with a copper pot and tea glasses"}, ["TDK | https://sozluk.gov.tr"]
        if "WRITER agent" in system:
            self.calls.append("writer")
            m = re.search(r"Level: ([A-C][12])", prompt)
            level = m.group(1) if m else "A1"
            audio = []
            for w, ex in WORDS:
                audio += [{"speaker": "female", "text": w}, {"speaker": "female", "text": ex}]
            return {"title": "Oshxonada", "topic": "Oshxona buyumlari",
                    "caption_html": SAMPLE_BODY.format(level=level), "audio": audio,
                    "audio_title": "Oshxonada — 10 ta yangi so'z", "items": [w for w, _ in WORDS],
                    "image_brief": "a bright Turkish kitchen with a copper pot, pan and tea glasses"}, []
        if "QUALITY CONTROL" in system:
            self.calls.append("qa")
            return {"verdict": "pass", "issues": [], "caption_html": None, "audio": None, "score": 9}, []
        self.calls.append("image_check")
        return {"has_text": False, "on_topic": True, "appropriate": True, "problems": ""}, []

    async def generate_image(self, prompt: str, aspect: str = "4:5", size: str = "1K") -> bytes:
        self.calls.append("image")
        W, H = 896, 1120
        img = Image.new("RGB", (W, H), "#FFF6EE")
        d = ImageDraw.Draw(img)
        for i in range(0, H, 8):
            shade = 246 - int(40 * i / H)
            d.line([(0, i), (W, i)], fill=(255, shade, shade - 10))
        rnd = random.Random(3)
        for _ in range(14):
            x, y, r = rnd.randint(40, W - 40), rnd.randint(60, H - 260), rnd.randint(30, 90)
            d.ellipse((x - r, y - r, x + r, y + r), fill=rnd.choice(["#E30A17", "#FFFFFF", "#F4C9A6", "#2B2B2B"]))
        d.ellipse((W / 2 - 170, 330, W / 2 + 170, 670), fill="#E30A17")
        d.ellipse((W / 2 - 110, 370, W / 2 + 150, 630), fill="#FFF6EE")
        b = io.BytesIO()
        img.save(b, "PNG")
        return b.getvalue()


class FakeEleven:
    async def aclose(self) -> None:
        pass

    async def tts(self, text: str, voice_id: str, language_code: str | None = None) -> bytes:
        freq = 440 if "female" in voice_id else 330
        seg = Sine(freq).to_audio_segment(duration=min(250 + 25 * len(text), 1800)).apply_gain(-12)
        b = io.BytesIO()
        seg.export(b, format="mp3")
        return b.getvalue()
