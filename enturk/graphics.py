"""Gemini'siz grafika: har bir post uchun turi va mavzusiga mos maket, rang temasi, emoji va Turkiya sahnasi.

Maketlar: card, hero, chat, quiz, poster, stickers, notebook, tiles.
Rang temalari: red, blue, teal, green, orange, purple, navy, pink, coffee — har birining o'z naqshi bor.
Sahnalar: skyline, bosphorus, balloons, tulips, tea.
Pastki qism (logo tasmasi): 8 xil uslub — solid, wave, split, float, light, zigzag, ribbon, center.
Emoji, sahna va rangni yozuvchi agent mavzuga qarab tanlaydi (draft["visual"]).
"""
from __future__ import annotations

import math
import random
import re
import zlib
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ASSETS = Path(__file__).resolve().parent.parent / "assets"
W, H, BAND = 1080, 1350, 150
WH = H - BAND                      # tasmadan yuqoridagi ish maydoni

RED, INK, WHITE = "#E30A17", "#1F1F1F", "#FFFFFF"
CLEAR = (0, 0, 0, 0)

FONT_FILES = {"sans": "font-bold.ttf", "sans_r": "font-regular.ttf",
              "display": "Carlito-Bold.ttf", "serif": "Caladea-Bold.ttf"}
EMOJI_PATHS = [ASSETS / "NotoColorEmoji.ttf",
               Path("/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf"),
               Path("/usr/share/fonts/noto/NotoColorEmoji.ttf")]

SCENES = ["skyline", "bosphorus", "balloons", "tulips", "tea"]
SCENES_TR = SCENES                 # eski nom (moslik uchun)
DIALOG_TYPES = {"haqiqiy_diolog"}

LAYOUTS_BY_TYPE = {
    "yangi_sozlar": ["card", "hero", "stickers", "poster", "tiles"],
    "kunlik_iboralar": ["hero", "poster", "stickers", "tiles", "card"],
    "mavzuli_lugat": ["card", "tiles", "stickers", "poster", "notebook"],
    "haqiqiy_diolog": ["chat", "poster", "hero"],
    "hayotiy_maslahat": ["notebook", "poster", "hero", "card"],
    "imtihon": ["notebook", "quiz", "hero", "tiles"],
    "haftalik_takrorlash": ["quiz", "notebook", "stickers"],
}
DEFAULT_EMOJIS = {
    "yangi_sozlar": ["📚", "✏️", "💡", "📝"], "kunlik_iboralar": ["💬", "🗣️", "👋", "😊"],
    "mavzuli_lugat": ["📖", "🔤", "🧩", "📌"], "haqiqiy_diolog": ["💬", "👩", "👨", "☕"],
    "hayotiy_maslahat": ["💡", "✅", "⚠️", "🧭"], "imtihon": ["📝", "🎯", "⏱️", "🏆"],
    "haftalik_takrorlash": ["🔁", "🧠", "✅", "🏆"],
}


# ====================================================================== ranglar
def _rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _hex(rgb) -> str:
    return "#%02X%02X%02X" % tuple(max(0, min(255, round(v))) for v in rgb)


def mix(a: str, b: str, t: float) -> str:
    """a rangdan b rangga t ulush (0..1) siljitadi."""
    return _hex([x + (y - x) * t for x, y in zip(_rgb(a), _rgb(b))])


def make_theme(name: str, main: str, accent: str, pattern: str) -> dict:
    black, white, paper = "#000000", "#FFFFFF", "#FFFBF6"
    return {
        "name": name, "main": main, "accent": accent, "pattern": pattern,
        "deep": mix(main, black, 0.27), "dark": mix(main, black, 0.55),
        "ray": mix(main, white, 0.07), "dots": mix(main, black, 0.09),
        "on_pattern": mix(main, white, 0.10), "scene_hi": mix(main, white, 0.28),
        "light": mix(main, white, 0.88), "pale": mix(main, white, 0.82),
        "shadow": mix(main, white, 0.72), "soft": mix(main, white, 0.66),
        "on_main": mix(main, white, 0.84), "bg": mix(paper, main, 0.03),
        "chat_bg": mix(paper, main, 0.05), "accent_light": mix(accent, white, 0.85),
        "shade": (*_rgb(mix(main, black, 0.6)), 70),
    }


THEMES = {t["name"]: t for t in (
    make_theme("red", "#E30A17", "#13807F", "tulip"),
    make_theme("blue", "#1E63C4", "#F2A93B", "wave"),
    make_theme("teal", "#0E7F86", "#E2533A", "diamond"),
    make_theme("green", "#2A8A3E", "#F2B33D", "leaf"),
    make_theme("orange", "#D9560F", "#1F6E8C", "dot"),
    make_theme("purple", "#6B3FB8", "#F2B33D", "star"),
    make_theme("navy", "#1E3A6E", "#E5A823", "plus"),
    make_theme("pink", "#D23B7C", "#2C8C82", "heart"),
    make_theme("coffee", "#7B4A2B", "#E6A23C", "bean"),
)}
# Yozuvchi agent uchun: qaysi rang qaysi mavzuga mos
THEME_GUIDE = ("red (Türkiye, national culture, holidays, general topics), "
               "blue (sea, travel, transport, airport, weather, city, technology), "
               "teal (art, home, house, Ottoman/Iznik culture, hobbies, shopping), "
               "green (nature, health, doctor, sport, body, fruit and vegetables, ecology, spring), "
               "orange (food, cooking, restaurant, market, autumn, energy), "
               "purple (feelings, character, music, dreams, cinema, culture events), "
               "navy (work, business, bank, money, law, exams, formal letters, education), "
               "pink (family, love, friendship, clothes, beauty, weddings, celebrations), "
               "coffee (tea, coffee, breakfast, café, home comfort, winter)")
THEME_RELATED = {"red": ["pink", "orange"], "blue": ["teal", "navy"], "teal": ["blue", "green"],
                 "green": ["teal", "coffee"], "orange": ["red", "coffee"], "purple": ["pink", "navy"],
                 "navy": ["blue", "purple"], "pink": ["purple", "red"], "coffee": ["orange", "green"]}
EMOJI_THEME = {
    "navy": "🏦💳💸💰💵💶📈📉💼🏢⚖️📝🎓🏫📑🗂️📊🧾✉️📨🏛️",
    "blue": "🌊⛴️🚢✈️🛫🚌🚕🚗🚆🚇🚲🗺️🧳🌧️☔❄️🌦️⛅💻📱🌉🏖️",
    "green": "🌳🌿🌱🍀🍎🥗🥦🥕⚽🏃🚴🩺💊🏥🧘🏋️🌲🦋🐶🐱🍏",
    "coffee": "☕🍵🫖🥐🍪🥯🧇🛋️🧣🧤🔥🍞",
    "orange": "🍕🍲🍰🍊🛒🍳🥘🍽️🍝🍅🌶️🧆🥙🍂🎃🍔",
    "pink": "❤️💕💐👗👠💄💍👨‍👩‍👧👪👶🎂🎁🎉🌸💒👚",
    "purple": "🎵🎶🎸🎹🎨🎭🎬😊😢😡😍🤔💭🌙✨🔮",
    "teal": "🕌🧿🏠🏡🖼️🧵🧶🛍️🏺🗝️🪴",
}


@lru_cache(maxsize=1)
def _emoji_theme_map() -> dict[str, str]:
    out: dict[str, str] = {}
    for theme, chars in EMOJI_THEME.items():
        for ch in chars:
            if ch not in "‍️":
                out.setdefault(ch, theme)
    return out


def guess_theme(emojis: list[str]) -> str | None:
    m = _emoji_theme_map()
    for e in emojis or []:
        for ch in str(e):
            if ch in m:
                return m[ch]
    return None


# ====================================================================== yordamchilar
@lru_cache(maxsize=96)
def font(name: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(ASSETS / FONT_FILES[name]), size)


@lru_cache(maxsize=1)
def _emoji_font() -> ImageFont.FreeTypeFont | None:
    for p in EMOJI_PATHS:
        if p.exists():
            try:
                return ImageFont.truetype(str(p), 109)
            except OSError:
                continue
    return None


@lru_cache(maxsize=256)
def _emoji_raw(ch: str) -> Image.Image | None:
    f = _emoji_font()
    if f is None or not ch:
        return None
    canvas = Image.new("RGBA", (420, 200), CLEAR)
    try:
        ImageDraw.Draw(canvas).text((14, 24), ch, font=f, embedded_color=True)
    except Exception:  # noqa: BLE001
        return None
    box = canvas.getbbox()
    if not box:
        return None
    im = canvas.crop(box)
    if im.width > im.height * 1.45 or im.height < 60:   # bir nechta belgiga bo'linib ketgan
        return None
    return im


def emoji(ch: str, px: int) -> Image.Image | None:
    raw = _emoji_raw(ch)
    if raw is None:
        return None
    s = px / max(raw.size)
    return raw.resize((max(1, round(raw.width * s)), max(1, round(raw.height * s))), Image.LANCZOS)


def valid_emojis(cands, fallback) -> list[str]:
    out: list[str] = []
    for c in list(cands or []) + list(fallback or []):
        c = str(c).strip()
        if c and c not in out and _emoji_raw(c) is not None:
            out.append(c)
    return out


def paste_c(img: Image.Image, im: Image.Image | None, cx: float, cy: float) -> None:
    if im is not None:
        img.paste(im, (round(cx - im.width / 2), round(cy - im.height / 2)), im)


def put_emoji(img, ch, px, cx, cy, rot=0.0, sticker=False, shade=None):
    im = emoji(ch, px)
    if im is None:
        return
    if sticker:
        im = make_sticker(im, border=max(6, px // 16), shade=shade)
    if rot:
        im = im.rotate(rot, expand=True, resample=Image.BICUBIC)
    paste_c(img, im, cx, cy)


def make_sticker(im: Image.Image, border: int = 10, shade=None) -> Image.Image:
    """Oq kontur va yumshoq soya — stiker ko'rinishi."""
    pad = border * 3
    base = Image.new("RGBA", (im.width + pad * 2, im.height + pad * 2), CLEAR)
    alpha = Image.new("L", base.size, 0)
    alpha.paste(im.split()[3], (pad, pad))
    grown = alpha.filter(ImageFilter.MaxFilter(border * 2 + 1)).point(lambda v: 255 if v > 40 else 0)
    shadow = grown.filter(ImageFilter.GaussianBlur(border))
    base.paste(Image.new("RGBA", base.size, tuple(shade or (90, 10, 15, 70))), (border // 2, border), shadow)
    base.paste(Image.new("RGBA", base.size, (255, 255, 255, 255)), (0, 0), grown)
    base.paste(im, (pad, pad), im)
    return base


def clean_title(t: str) -> str:
    t = re.sub(r"\[[A-C][12][^\]]*\]", "", t or "")
    for a in "ʻʼ’‘`´":
        t = t.replace(a, "'")
    t = "".join(ch for ch in t if ord(ch) < 0x2000 or ch in "—–…«»")
    return re.sub(r"\s+", " ", t).strip(" -—:|•")


def wrap(d: ImageDraw.ImageDraw, text: str, f, max_w: float) -> list[str]:
    lines, cur = [], ""
    for w in text.split():
        test = f"{cur} {w}".strip()
        if d.textlength(test, font=f) <= max_w or not cur:
            cur = test
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def fit_text(d, text, fname, max_w, max_h, start=88, minimum=40, spacing=1.16, max_lines=4):
    size = start
    while True:
        f = font(fname, size)
        lines = wrap(d, text, f, max_w)
        lh = size * spacing
        fits_w = all(d.textlength(ln, font=f) <= max_w for ln in lines)
        if (len(lines) <= max_lines and len(lines) * lh <= max_h and fits_w) or size <= minimum:
            break
        size -= 2 if size <= 48 else 4
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1].rstrip(".,") + "…"
    return f, lines, size * spacing


def draw_lines(d, lines, f, x, y, fill, lh, anchor="ma"):
    for ln in lines:
        d.text((x, y), ln, font=f, fill=fill, anchor=anchor)
        y += lh
    return y


def pill(d, text, cx, cy, *, fname="sans", size=36, fill=RED, color=WHITE, outline=None, pad=36):
    f = font(fname, size)
    w = d.textlength(text, font=f) + pad * 2
    h = size + 34
    d.rounded_rectangle((cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2), radius=h / 2, fill=fill,
                        outline=outline, width=3 if outline else 0)
    d.text((cx, cy), text, font=f, fill=color, anchor="mm")
    return w


def plan_chips(d, items, max_w, *, fname="sans", size=34, max_rows=2, gap=16, max_chars=24):
    f = font(fname, size)
    rows, row, rw = [], [], 0.0
    for it in [i.strip() for i in items or [] if i and 0 < len(i.strip()) <= max_chars][:8]:
        w = d.textlength(it, font=f) + 52
        if w > max_w:
            continue
        if row and rw + w > max_w:
            rows.append(row)
            row, rw = [], 0.0
        row.append((it, w))
        rw += w + gap
    if row:
        rows.append(row)
    return rows[:max_rows]


def draw_chips(d, rows, cx, y, *, fname="sans", size=34, fill="#FDECEC", outline=RED, color=RED, gap=16, h=58):
    f = font(fname, size)
    for row in rows:
        total = sum(w for _, w in row) + gap * (len(row) - 1)
        x = cx - total / 2
        for it, w in row:
            d.rounded_rectangle((x, y, x + w, y + h), radius=h / 2, fill=fill, outline=outline,
                                width=3 if outline else 0)
            d.text((x + w / 2, y + h / 2), it, font=f, fill=color, anchor="mm")
            x += w + gap
        y += h + 16
    return y


def chips_h(rows, h=58):
    return len(rows) * (h + 16)


# ---------------------------------------------------------------- naqshlar
def _tulip(d, x, y, c, s=1.0):
    d.ellipse((x - 12 * s, y - 20 * s, x + 12 * s, y + 8 * s), fill=c)
    d.polygon([(x - 16 * s, y - 6 * s), (x - 5 * s, y - 27 * s), (x, y - 10 * s)], fill=c)
    d.polygon([(x + 16 * s, y - 6 * s), (x + 5 * s, y - 27 * s), (x, y - 10 * s)], fill=c)
    d.line((x, y + 8 * s, x, y + 30 * s), fill=c, width=max(2, round(4 * s)))


def _leaf(d, x, y, c, flip=False):
    a = -0.8 if flip else 0.8
    pts = []
    for i in range(25):
        t = math.pi * 2 * i / 24
        px, py = 24 * math.cos(t), 10 * math.sin(t) * abs(math.cos(t / 2)) * 1.4
        pts.append((x + px * math.cos(a) - py * math.sin(a), y + px * math.sin(a) + py * math.cos(a)))
    d.polygon(pts, fill=c)
    d.line((x - 22 * math.cos(a), y - 22 * math.sin(a), x - 34 * math.cos(a), y - 34 * math.sin(a)),
           fill=c, width=3)


def _star(d, x, y, c, r=20):
    k = 0.28
    d.polygon([(x, y - r), (x + r * k, y - r * k), (x + r, y), (x + r * k, y + r * k), (x, y + r),
               (x - r * k, y + r * k), (x - r, y), (x - r * k, y - r * k)], fill=c)


def _heart(d, x, y, c, r=11):
    d.ellipse((x - 2 * r, y - r, x, y + r), fill=c)
    d.ellipse((x, y - r, x + 2 * r, y + r), fill=c)
    d.polygon([(x - 2 * r + 1, y + 3), (x + 2 * r - 1, y + 3), (x, y + 2.3 * r)], fill=c)


def _bean(d, x, y, c, flip=False):
    a = -0.6 if flip else 0.6
    pts = [(x + 20 * math.cos(t) * math.cos(a) - 13 * math.sin(t) * math.sin(a),
            y + 20 * math.cos(t) * math.sin(a) + 13 * math.sin(t) * math.cos(a))
           for t in (math.pi * 2 * i / 24 for i in range(24))]
    d.polygon(pts, fill=c)


def pattern(d, kind: str, color, height=WH + 60, step=120):
    """Fon naqshi (tema bo'yicha): tulip, wave, leaf, dot, star, plus, heart, diamond, bean."""
    if kind == "wave":
        for yi, y in enumerate(range(40, height, 70)):
            off = 45 if yi % 2 else 0
            for x in range(-90 + off, W + 90, 90):
                d.arc((x, y - 16, x + 90, y + 16), 200, 340, fill=color, width=6)
        return
    for yi, y in enumerate(range(30, height, step)):
        for xi, x in enumerate(range(-40 + (step // 2 if yi % 2 else 0), W + 60, step)):
            flip = (xi + yi) % 2 == 1
            if kind == "tulip":
                _tulip(d, x, y, color)
            elif kind == "leaf":
                _leaf(d, x, y, color, flip)
            elif kind == "dot":
                d.ellipse((x - 11, y - 11, x + 11, y + 11), fill=color)
                d.ellipse((x + step / 2 - 5, y + step / 2 - 5, x + step / 2 + 5, y + step / 2 + 5), fill=color)
            elif kind == "star":
                _star(d, x, y, color, 22 if flip else 14)
            elif kind == "plus":
                d.rectangle((x - 16, y - 5, x + 16, y + 5), fill=color)
                d.rectangle((x - 5, y - 16, x + 5, y + 16), fill=color)
            elif kind == "heart":
                _heart(d, x, y, color)
            elif kind == "diamond":
                d.polygon([(x, y - 22), (x + 16, y), (x, y + 22), (x - 16, y)], fill=color)
            elif kind == "bean":
                _bean(d, x, y, color, flip)
            else:
                d.ellipse((x - 6, y - 6, x + 6, y + 6), fill=color)


def tulip_pattern(d, color, step=120, height=WH + 60):
    pattern(d, "tulip", color, height=height, step=step)


def dot_grid(d, color, step=42, r=3, height=WH):
    for y in range(step // 2, height, step):
        for x in range(step // 2, W, step):
            d.ellipse((x - r, y - r, x + r, y + r), fill=color)


def tile_image(w, h, s=120, red=RED, turq="#13807F", bg=WHITE, line="#F8DEDF") -> Image.Image:
    """Iznik uslubidagi koshin naqshi."""
    im = Image.new("RGB", (w, h), bg)
    d = ImageDraw.Draw(im)
    for yy in range(0, h + s, s):
        for xx in range(0, w + s, s):
            d.rectangle((xx, yy, xx + s, yy + s), outline=line, width=2)
            cx, cy = xx + s / 2, yy + s / 2
            for dx, dy in ((0, -1), (1, 0), (0, 1), (-1, 0)):
                px, py = cx + dx * s * 0.23, cy + dy * s * 0.23
                d.ellipse((px - s * 0.12, py - s * 0.12, px + s * 0.12, py + s * 0.12), fill=red)
            d.ellipse((cx - s * 0.11, cy - s * 0.11, cx + s * 0.11, cy + s * 0.11), fill=turq)
            for qx, qy in ((xx, yy), (xx + s, yy), (xx, yy + s), (xx + s, yy + s)):
                d.ellipse((qx - s * 0.15, qy - s * 0.15, qx + s * 0.15, qy + s * 0.15), fill=turq)
    return im


# ====================================================================== sahnalar
def _skyline(d, base, c, accent=None):
    def minaret(x, h, w=16):
        d.rectangle((x - w // 2, base - h, x + w // 2, base), fill=c)
        d.rectangle((x - w // 2 - 5, base - int(h * 0.62), x + w // 2 + 5, base - int(h * 0.62) + 8), fill=c)
        d.polygon([(x - w // 2, base - h), (x + w // 2, base - h), (x, base - h - 46)], fill=c)

    def mosque(cx, r):
        d.rectangle((cx - int(r * 1.5), base - r, cx + int(r * 1.5), base), fill=c)
        d.pieslice((cx - r, base - int(r * 1.7), cx + r, base - int(r * 0.3)), 180, 360, fill=c)
        for sx in (-1, 1):
            c2 = cx + sx * int(r * 1.05)
            d.pieslice((c2 - r // 2, base - int(r * 1.05), c2 + r // 2, base - int(r * 0.2)), 180, 360, fill=c)
        d.rectangle((cx - 3, base - int(r * 1.7) - 26, cx + 3, base - r), fill=c)
        minaret(cx - int(r * 1.75), int(r * 2.5))
        minaret(cx + int(r * 1.75), int(r * 2.5))

    d.rectangle((0, base - 22, W, base), fill=c)
    mosque(int(W * 0.26), 78)
    x = int(W * 0.62)                                   # Galata minorasi
    d.rectangle((x - 34, base - 190, x + 34, base), fill=c)
    d.rectangle((x - 44, base - 200, x + 44, base - 186), fill=c)
    d.polygon([(x - 40, base - 200), (x + 40, base - 200), (x, base - 290)], fill=c)
    for wy in (base - 150, base - 95):
        d.rectangle((x - 8, wy, x + 8, wy + 26), fill=CLEAR)
    mosque(int(W * 0.84), 58)
    for bx, h in ((int(W * 0.05), 60), (int(W * 0.46), 90), (int(W * 0.72), 70), (int(W * 0.97), 55)):
        d.rectangle((bx - 30, base - h, bx + 30, base), fill=c)


def _bosphorus(d, base, c, accent=None):
    wl = base - 34
    d.rectangle((0, wl, W, base), fill=c)
    for x in range(0, W + 80, 80):
        d.arc((x - 40, wl - 24, x + 40, wl + 16), 200, 340, fill=c, width=6)
    t1, t2, end = int(W * 0.10), int(W * 0.50), int(W * 0.66)
    deck, top = base - 115, base - 335
    d.rectangle((0, deck - 6, end, deck + 6), fill=c)
    for tx in (t1, t2):
        d.rectangle((tx - 14, top, tx + 14, wl), fill=c)
        d.rectangle((tx - 24, top + 40, tx + 24, top + 54), fill=c)
    pts = []
    for i in range(41):
        t = i / 40
        pts.append((t1 + (t2 - t1) * t, top + (deck - 24 - top) * (1 - (2 * t - 1) ** 2)))
    d.line(pts, fill=c, width=6)
    for i in range(2, 40, 3):
        x, y = pts[i]
        d.line((x, y, x, deck), fill=c, width=2)
    d.line([(t1, top), (0, deck - 70)], fill=c, width=6)
    d.line([(t2, top), (end, deck - 16)], fill=c, width=6)
    x = int(W * 0.84)                                   # vapur (paroxod)
    d.polygon([(x - 140, wl - 46), (x + 130, wl - 46), (x + 100, wl + 4), (x - 118, wl + 4)], fill=c)
    d.rectangle((x - 100, wl - 92, x + 70, wl - 46), fill=c)
    for wx in range(x - 88, x + 60, 34):
        d.rectangle((wx, wl - 80, wx + 20, wl - 62), fill=CLEAR)
    d.rectangle((x - 60, wl - 122, x + 30, wl - 92), fill=c)
    d.rectangle((x + 4, wl - 162, x + 24, wl - 122), fill=c)
    for gx, gy, s in ((int(W * 0.30), base - 300, 26), (int(W * 0.37), base - 345, 18),
                      (int(W * 0.78), base - 290, 22)):
        d.arc((gx - s, gy - s // 2, gx, gy + s // 2), 200, 340, fill=c, width=5)
        d.arc((gx, gy - s // 2, gx + s, gy + s // 2), 200, 340, fill=c, width=5)


def _balloons(d, base, c, accent=None):
    for cx, h, w in ((70, 170, 90), (190, 230, 110), (330, 150, 80), (760, 200, 100), (900, 250, 120),
                     (1030, 160, 90)):
        d.polygon([(cx - w // 2, base), (cx + w // 2, base), (cx + w // 6, base - h), (cx - w // 6, base - h)],
                  fill=c)
        d.ellipse((cx - w // 4, base - h - w // 4, cx + w // 4, base - h + w // 6), fill=c)
        d.ellipse((cx - 9, base - h * 0.55, cx + 9, base - h * 0.55 + 22), fill=CLEAR)
    d.rectangle((0, base - 30, W, base), fill=c)
    stripe = accent or CLEAR
    for bx, by, r in ((540, base - 260, 95), (300, base - 330, 62), (820, base - 375, 72)):
        d.ellipse((bx - r, by - r, bx + r, by + int(r * 0.9)), fill=c)
        d.polygon([(bx - int(r * 0.78), by + int(r * 0.5)), (bx + int(r * 0.78), by + int(r * 0.5)),
                   (bx + int(r * 0.25), by + int(r * 1.22)), (bx - int(r * 0.25), by + int(r * 1.22))], fill=c)
        d.ellipse((bx - int(r * 0.38), by - r + 4, bx + int(r * 0.38), by + int(r * 0.86)), outline=stripe,
                  width=max(3, r // 11))
        d.line((bx - int(r * 0.2), by + int(r * 1.22), bx - int(r * 0.18), by + int(r * 1.48)), fill=c, width=3)
        d.line((bx + int(r * 0.2), by + int(r * 1.22), bx + int(r * 0.18), by + int(r * 1.48)), fill=c, width=3)
        d.rectangle((bx - int(r * 0.22), by + int(r * 1.48), bx + int(r * 0.22), by + int(r * 1.74)), fill=c)


def _tulips(d, base, c, accent=None):
    leaf = accent or c
    d.rectangle((0, base - 24, W, base), fill=leaf)
    for i, x in enumerate(range(40, W, 78)):
        h = 120 + (i * 37) % 110
        top = base - 24 - h
        d.line((x, base - 24, x, top), fill=leaf, width=7)
        d.polygon([(x, base - 40), (x - 46, base - 110 - (i % 3) * 15), (x - 6, base - 70)], fill=leaf)
        d.polygon([(x, base - 50), (x + 40, base - 120), (x + 6, base - 80)], fill=leaf)
        d.ellipse((x - 28, top - 40, x + 28, top + 12), fill=c)
        d.polygon([(x - 28, top - 14), (x - 22, top - 62), (x - 6, top - 30)], fill=c)
        d.polygon([(x + 28, top - 14), (x + 22, top - 62), (x + 6, top - 30)], fill=c)
        d.polygon([(x - 10, top - 30), (x, top - 70), (x + 10, top - 30)], fill=c)


def _tea(d, base, c, accent=None):
    table = base - 26
    d.rectangle((0, table, W, base), fill=c)
    x = 230                                             # ikki qavatli choynak (çaydanlık)
    d.ellipse((x - 115, table - 175, x + 115, table + 5), fill=c)
    d.polygon([(x + 80, table - 110), (x + 190, table - 205), (x + 205, table - 190), (x + 100, table - 70)],
              fill=c)
    d.arc((x - 175, table - 165, x - 75, table - 55), 90, 270, fill=c, width=16)
    d.ellipse((x - 72, table - 285, x + 72, table - 165), fill=c)
    d.ellipse((x - 16, table - 312, x + 16, table - 280), fill=c)
    x, h = 560, 240                                     # lola shaklidagi choy stakani
    keys = [(0.0, 64), (0.45, 36), (0.82, 56), (1.0, 46)]
    top = table - 40 - h

    def hw(t):
        for (t0, w0), (t1, w1) in zip(keys, keys[1:]):
            if t <= t1:
                k = (t - t0) / (t1 - t0)
                return w0 + (w1 - w0) * (1 - math.cos(math.pi * k)) / 2
        return keys[-1][1]
    left = [(x - hw(i / 30), top + h * i / 30) for i in range(31)]
    right = [(x + hw(i / 30), top + h * i / 30) for i in range(31)][::-1]
    d.polygon(left + right, fill=c)
    d.rectangle((x - 62, top + 18, x + 62, top + 28), fill=CLEAR)
    d.ellipse((x - 120, table - 46, x + 120, table + 2), fill=c)
    for sx in (-28, 0, 28):
        d.arc((x + sx - 16, top - 110, x + sx + 16, top - 60), 90, 270, fill=c, width=6)
        d.arc((x + sx - 16, top - 64, x + sx + 16, top - 14), 270, 90, fill=c, width=6)
    x = 860                                             # simit
    d.ellipse((x - 115, table - 170, x + 115, table + 4), fill=c)
    d.ellipse((x - 44, table - 112, x + 44, table - 54), fill=CLEAR)
    rng = random.Random(5)
    for _ in range(40):
        a, rr = rng.uniform(0, 2 * math.pi), rng.uniform(58, 100)
        px, py = x + math.cos(a) * rr, table - 83 + math.sin(a) * rr * 0.72
        d.ellipse((px - 4, py - 2, px + 4, py + 2), fill=CLEAR)


SCENE_FUNCS = {"skyline": _skyline, "bosphorus": _bosphorus, "balloons": _balloons, "tulips": _tulips,
               "tea": _tea}


def scene_layer(name: str, color: str, accent: str | None = None, height: int = 540) -> Image.Image:
    layer = Image.new("RGBA", (W, height), CLEAR)
    SCENE_FUNCS.get(name, _skyline)(ImageDraw.Draw(layer), height, color, accent)
    return layer


def paste_scene(img, name, color, accent=None, base=WH, scale=1.0, alpha=255):
    layer = scene_layer(name, color, accent)
    if scale != 1.0:
        layer = layer.resize((round(W * scale), round(layer.height * scale)), Image.LANCZOS)
    if alpha < 255:
        a = layer.split()[3].point(lambda v: v * alpha // 255)
        layer.putalpha(a)
    img.paste(layer, (round((W - layer.width) / 2), base - layer.height), layer)


# ====================================================================== maketlar
@dataclass
class Ctx:
    title: str
    label: str
    sublabel: str
    items: list[str]
    emojis: list[str]
    scene: str
    lang: str = "tr"
    lines: list[dict] = field(default_factory=list)
    seed: int = 0
    t: dict = field(default_factory=lambda: THEMES["red"])

    @property
    def rng(self) -> random.Random:
        return random.Random(self.seed)

    def e(self, i: int) -> str:
        return self.emojis[i % len(self.emojis)] if self.emojis else ""


def lay_card(c: Ctx) -> Image.Image:
    t = c.t
    img = Image.new("RGB", (W, H), t["bg"])
    d = ImageDraw.Draw(img)
    pattern(d, t["pattern"], t["pale"])
    paste_scene(img, c.scene, t["main"], accent=WHITE)
    m, top, bottom = 80, 120, WH - 345
    d.rounded_rectangle((m + 10, top + 14, W - m + 10, bottom + 14), radius=44, fill=t["shadow"])
    d.rounded_rectangle((m, top, W - m, bottom), radius=44, fill=WHITE, outline=t["main"], width=7)
    d.rounded_rectangle((m + 22, bottom - 18, W - m - 22, bottom - 10), radius=4, fill=t["accent"])
    pill(d, c.label, W / 2, top, size=36, fill=t["main"])
    for i, x in enumerate((W / 2 - 170, W / 2, W / 2 + 170)[:max(1, min(3, len(c.emojis)))]):
        put_emoji(img, c.e(i), 118 if i != 1 else 140, x if len(c.emojis) >= 3 else W / 2, top + 140)
        if len(c.emojis) < 3:
            break
    rows = plan_chips(d, c.items, W - 2 * m - 80)
    t_top, t_bot = top + 225, bottom - 84 - chips_h(rows) - 26
    f, lines, lh = fit_text(d, c.title, "sans", W - 2 * m - 100, t_bot - t_top, start=76, max_lines=3)
    draw_lines(d, lines, f, W / 2, t_top + (t_bot - t_top - len(lines) * lh) / 2, INK, lh)
    draw_chips(d, rows, W / 2, t_bot + 26, fill=t["light"], outline=t["main"], color=t["main"])
    d.text((W / 2, bottom - 48), c.sublabel, font=font("sans_r", 32), fill=t["deep"], anchor="mm")
    return img


def lay_hero(c: Ctx) -> Image.Image:
    t = c.t
    img = Image.new("RGB", (W, H), t["main"])
    d = ImageDraw.Draw(img)
    cx, cy = W / 2, 360
    for k in range(24):                                  # quyosh nurlari
        if k % 2:
            continue
        a0, a1 = k * 15, k * 15 + 15
        d.pieslice((cx - 1300, cy - 1300, cx + 1300, cy + 1300), a0, a1, fill=t["ray"])
    paste_scene(img, c.scene, t["deep"], accent=None, scale=0.82)
    d.ellipse((cx - 228 + 14, cy - 228 + 18, cx + 228 + 14, cy + 228 + 18), fill=t["deep"])
    d.ellipse((cx - 228, cy - 228, cx + 228, cy + 228), fill=WHITE)
    d.ellipse((cx - 212, cy - 212, cx + 212, cy + 212), outline=t["accent"], width=6)
    put_emoji(img, c.e(0), 290, cx, cy)
    for i, ang in enumerate((-35, 215, 145)[:max(0, len(c.emojis) - 1)]):
        ex = cx + math.cos(math.radians(ang)) * 300
        ey = cy + math.sin(math.radians(ang)) * 260
        d.ellipse((ex - 82 + 6, ey - 82 + 8, ex + 82 + 6, ey + 82 + 8), fill=t["deep"])
        d.ellipse((ex - 82, ey - 82, ex + 82, ey + 82), fill=WHITE)
        put_emoji(img, c.e(i + 1), 104, ex, ey)
    pill(d, c.label, W / 2, 680, fill=WHITE, color=t["main"], size=34)
    rows = plan_chips(d, c.items, W - 160, max_rows=1)
    t_top, t_bot = 740, 960 - chips_h(rows)
    f, lines, lh = fit_text(d, c.title, "display", W - 140, t_bot - t_top, start=96, minimum=48)
    draw_lines(d, lines, f, W / 2, t_top + (t_bot - t_top - len(lines) * lh) / 2, WHITE, lh)
    draw_chips(d, rows, W / 2, t_bot + 4, fill=t["deep"], outline=WHITE, color=WHITE)
    d.text((W / 2, 1010), c.sublabel, font=font("sans_r", 30), fill=t["on_main"], anchor="mm")
    return img


def lay_chat(c: Ctx) -> Image.Image:
    t = c.t
    img = Image.new("RGB", (W, H), t["chat_bg"])
    d = ImageDraw.Draw(img)
    dot_grid(d, t["pale"])
    paste_scene(img, c.scene, t["soft"], accent=None)
    pill(d, c.label, W / 2, 90, size=34, fill=t["main"])
    f, lines, lh = fit_text(d, c.title, "sans", W - 160, 170, start=64, minimum=40, max_lines=3)
    draw_lines(d, lines, f, W / 2, 150 + (170 - len(lines) * lh) / 2, INK, lh)
    speakers = [str(x.get("speaker", "female")) for x in c.lines]
    alternate = len(set(speakers)) < 2
    y = 360
    fb = font("sans_r", 36)
    female_e = "👩" if _emoji_raw("👩") else ""
    male_e = "👨" if _emoji_raw("👨") else ""
    for i, ln in enumerate(c.lines[:4]):
        text = clean_title(str(ln.get("text", "")))
        if not text:
            continue
        right = (i % 2 == 1) if alternate else speakers[i] == "male"
        bl = wrap(d, text, fb, 600)
        if len(bl) > 2:
            bl = bl[:2]
            bl[-1] = bl[-1].rstrip(".,!?") + "…"
        bw = max(d.textlength(x, font=fb) for x in bl) + 64
        bh = len(bl) * 48 + 40
        if y + bh > 1020:
            break
        ax = W - 110 if right else 110
        d.ellipse((ax - 58, y - 4, ax + 58, y + 112), fill=WHITE,
                  outline=t["main"] if right else t["accent"], width=4)
        put_emoji(img, male_e if right else female_e, 76, ax, y + 54)
        x0 = ax - 80 - bw if right else ax + 80
        fill, col = (t["main"], WHITE) if right else (WHITE, INK)
        d.rounded_rectangle((x0 + 6, y + 8, x0 + bw + 6, y + bh + 8), radius=30, fill=t["shadow"])
        d.rounded_rectangle((x0, y, x0 + bw, y + bh), radius=30, fill=fill,
                            outline=None if right else t["main"], width=0 if right else 3)
        tx = x0 + bw if right else x0
        d.polygon([(tx, y + 30), (tx + (22 if right else -22), y + 40), (tx, y + 58)], fill=fill)
        draw_lines(d, bl, fb, x0 + 32, y + 20, col, 48, anchor="la")
        y += max(bh, 116) + 34
    for i in range(min(3, len(c.emojis))):
        put_emoji(img, c.e(i), 74, W / 2 + (i - 1) * 110, 1080, rot=(i - 1) * -10, sticker=True, shade=t["shade"])
    d.text((W / 2, 1160), c.sublabel, font=font("sans_r", 30), fill=t["deep"], anchor="mm")
    return img


def lay_quiz(c: Ctx) -> Image.Image:
    t = c.t
    img = Image.new("RGB", (W, H), WHITE)
    d = ImageDraw.Draw(img)
    rng = c.rng
    fq = font("display", 240)
    for _ in range(9):
        layer = Image.new("RGBA", (220, 300), CLEAR)
        ImageDraw.Draw(layer).text((110, 150), "?", font=fq, fill=t["pale"], anchor="mm")
        layer = layer.rotate(rng.uniform(-30, 30), expand=True)
        img.paste(layer, (rng.randint(-60, W - 120), rng.randint(-60, WH - 260)), layer)
    cx, cy = W / 2, 250
    d.ellipse((cx - 160 + 10, cy - 160 + 14, cx + 160 + 10, cy + 160 + 14), fill=t["soft"])
    d.ellipse((cx - 160, cy - 160, cx + 160, cy + 160), fill=t["main"])
    put_emoji(img, c.e(0), 190, cx, cy)
    bx, by = cx + 125, cy + 110
    d.ellipse((bx - 52, by - 52, bx + 52, by + 52), fill=WHITE, outline=t["accent"], width=6)
    d.text((bx, by + 4), "?", font=font("display", 84), fill=t["accent"], anchor="mm")
    pill(d, c.label, W / 2, 470, size=34, fill=t["main"])
    f, lines, lh = fit_text(d, c.title, "sans", W - 180, 170, start=66, minimum=40, max_lines=3)
    draw_lines(d, lines, f, W / 2, 530 + (170 - len(lines) * lh) / 2, INK, lh)
    opts = [i for i in c.items if i and len(i) <= 32][:3]
    fo = font("sans", 40)
    y = 720
    for k, it in enumerate(opts):
        d.rounded_rectangle((110 + 6, y + 8, W - 110 + 6, y + 96 + 8), radius=26, fill=t["shadow"])
        d.rounded_rectangle((110, y, W - 110, y + 96), radius=26, fill=WHITE, outline=t["main"], width=4)
        d.ellipse((132, y + 14, 200, y + 82), fill=t["main"])
        d.text((166, y + 48), "ABC"[k], font=font("sans", 38), fill=WHITE, anchor="mm")
        txt = it
        while d.textlength(txt, font=fo) > W - 360 and len(txt) > 4:
            txt = txt[:-2]
        d.text((230, y + 48), txt if txt == it else txt.rstrip() + "…", font=fo, fill=INK, anchor="lm")
        y += 110
    if rng.random() < 0.5:
        img.paste(tile_image(W, 70, s=70, red=t["main"], turq=t["accent"], line=t["pale"]), (0, WH - 70))
    else:
        for x in range(0, W, 60):
            d.polygon([(x, WH), (x + 30, WH - 50), (x + 60, WH)], fill=t["main"] if (x // 60) % 2 else t["pale"])
    d.text((W / 2, WH - 100), c.sublabel, font=font("sans_r", 30), fill=t["deep"], anchor="mm")
    return img


def lay_poster(c: Ctx) -> Image.Image:
    t = c.t
    img = Image.new("RGB", (W, H), t["bg"])
    d = ImageDraw.Draw(img)
    split = 640
    layer = Image.new("RGBA", (W, H), CLEAR)
    ImageDraw.Draw(layer).polygon([(0, 0), (W, 0), (W, split - 60), (0, split + 40)], fill=t["main"])
    img.paste(layer, (0, 0), layer)
    pattern(d, t["pattern"], t["on_pattern"], height=split - 120)
    paste_scene(img, c.scene, t["deep"], accent=t["scene_hi"], base=split - 10, scale=0.95)
    d.polygon([(0, split + 40), (W, split - 60), (W, split - 44), (0, split + 56)], fill=t["accent"])
    d.polygon([(0, split + 56), (W, split - 44), (W, split + 4), (0, split + 104)], fill=t["bg"])
    cx, cy = W / 2, 560
    d.ellipse((cx - 178, cy - 178, cx + 178, cy + 178), fill=t["main"])
    d.ellipse((cx - 164, cy - 164, cx + 164, cy + 164), fill=WHITE)
    put_emoji(img, c.e(0), 220, cx, cy)
    for i, (ex, ey, rot) in enumerate(((cx - 250, cy + 70, 14), (cx + 250, cy + 60, -12))):
        if len(c.emojis) > i + 1:
            put_emoji(img, c.e(i + 1), 120, ex, ey, rot=rot, sticker=True, shade=t["shade"])
    pill(d, c.label, W / 2, 800, fill=t["light"], color=t["main"], outline=t["main"], size=32)
    rows = plan_chips(d, c.items, W - 160, max_rows=1)
    t_top, t_bot = 850, 1150 - chips_h(rows)
    f, lines, lh = fit_text(d, c.title, "serif", W - 160, t_bot - t_top, start=84, minimum=46)
    draw_lines(d, lines, f, W / 2, t_top + (t_bot - t_top - len(lines) * lh) / 2, INK, lh)
    draw_chips(d, rows, W / 2, t_bot, fill=t["main"], outline=None, color=WHITE)
    return img


def lay_stickers(c: Ctx) -> Image.Image:
    t = c.t
    img = Image.new("RGB", (W, H), t["bg"])
    d = ImageDraw.Draw(img)
    pattern(d, t["pattern"], t["light"], height=WH)
    rng = c.rng
    slots = [(170, 190), (900, 200), (540, 150), (160, 1030), (920, 1020), (540, 1070)]
    rng.shuffle(slots)
    n = min(len(c.emojis), 6) if c.emojis else 0
    for i in range(n):
        sx, sy = slots[i]
        put_emoji(img, c.e(i), rng.randint(130, 175), sx + rng.randint(-25, 25), sy + rng.randint(-20, 20),
                  rot=rng.uniform(-18, 18), sticker=True, shade=t["shade"])
    pw, ph = 860, 520
    panel = Image.new("RGBA", (pw + 30, ph + 30), CLEAR)
    pd = ImageDraw.Draw(panel)
    pd.rounded_rectangle((16, 20, pw + 16, ph + 20), radius=40, fill=t["shadow"])
    pd.rounded_rectangle((0, 0, pw, ph), radius=40, fill=WHITE, outline=t["main"], width=8)
    pill(pd, c.label, pw / 2, 80, size=34, fill=t["main"])
    rows = plan_chips(pd, c.items, pw - 80, max_rows=2)
    t_top, t_bot = 140, ph - 50 - chips_h(rows)
    f, lines, lh = fit_text(pd, c.title, "display", pw - 90, t_bot - t_top, start=92, minimum=46)
    draw_lines(pd, lines, f, pw / 2, t_top + (t_bot - t_top - len(lines) * lh) / 2, t["main"], lh)
    draw_chips(pd, rows, pw / 2, t_bot, fill=t["accent_light"], outline=t["accent"], color=t["deep"])
    panel = panel.rotate(rng.choice((-2.5, 2.0, -1.5)), expand=True, resample=Image.BICUBIC)
    paste_c(img, panel, W / 2, 610)
    d.text((W / 2, WH - 44), c.sublabel, font=font("sans_r", 28), fill=t["deep"], anchor="mm")
    return img


def lay_notebook(c: Ctx) -> Image.Image:
    t = c.t
    img = Image.new("RGB", (W, H), t["main"])
    d = ImageDraw.Draw(img)
    dot_grid(d, t["dots"], step=46, r=4)
    pw, ph = 880, 1000
    paper = Image.new("RGBA", (pw + 30, ph + 30), CLEAR)
    p = ImageDraw.Draw(paper)
    p.rectangle((14, 18, pw + 14, ph + 18), fill=(*_rgb(t["dark"]), 120))
    p.rectangle((0, 0, pw, ph), fill=WHITE)
    for ly in range(250, ph - 30, 66):
        p.line((0, ly, pw, ly), fill=t["pale"], width=3)
    p.line((110, 0, 110, ph), fill=t["accent"], width=4)
    for hy in (180, ph // 2, ph - 180):
        p.ellipse((36, hy - 18, 72, hy + 18), fill="#E9E5E2")
    p.text((150, 70), c.label, font=font("sans", 32), fill=t["main"], anchor="la")
    f, lines, lh = fit_text(p, c.title, "serif", pw - 330, 240, start=70, minimum=42, max_lines=4)
    draw_lines(p, lines, f, 150, 128, INK, lh, anchor="la")
    y = max(250 + 66 * 3, 128 + len(lines) * lh + 70)
    y = 250 + 66 * math.ceil((y - 250) / 66)
    fi = font("serif", 44)
    for it in [i for i in c.items if i][:5]:
        if y > ph - 120:
            break
        txt = it if len(it) <= 34 else it[:33].rstrip() + "…"
        p.rounded_rectangle((150, y - 50, 192, y - 8), radius=6, outline=t["main"], width=4)
        p.line((158, y - 30, 170, y - 16, 186, y - 44), fill=t["main"], width=5)
        p.text((214, y - 12), txt, font=fi, fill=INK, anchor="ls")
        y += 66
    p.text((pw - 40, ph - 40), c.sublabel, font=font("sans_r", 28), fill=t["deep"], anchor="rs")
    paper = paper.rotate(-1.2, expand=True, resample=Image.BICUBIC)
    paste_c(img, paper, W / 2, 590)
    put_emoji(img, c.e(0), 170, W - 190, 210, rot=12, sticker=True, shade=t["shade"])
    if len(c.emojis) > 1:
        put_emoji(img, c.e(1), 120, 150, 1050, rot=-14, sticker=True, shade=t["shade"])
    cx = 700
    d.rounded_rectangle((cx - 22, 60, cx + 22, 170), radius=22, outline="#9A9A9A", width=8)
    d.rounded_rectangle((cx - 10, 80, cx + 10, 150), radius=10, outline="#9A9A9A", width=6)
    return img


def lay_tiles(c: Ctx) -> Image.Image:
    t = c.t
    img = Image.new("RGB", (W, H), t["bg"])
    s = 110
    img.paste(tile_image(W, WH, s=s, red=t["main"], turq=t["accent"], line=t["pale"]))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((s - 14, s - 14, W - s + 14, WH - s + 14), radius=30, fill=t["main"])
    d.rounded_rectangle((s, s, W - s, WH - s), radius=24, fill=t["bg"])
    cx, cy = W / 2, 370
    d.ellipse((cx - 190, cy - 190, cx + 190, cy + 190), fill=t["main"])
    d.ellipse((cx - 176, cy - 176, cx + 176, cy + 176), fill=WHITE)
    d.ellipse((cx - 160, cy - 160, cx + 160, cy + 160), outline=t["accent"], width=5)
    put_emoji(img, c.e(0), 220, cx, cy)
    for i, (ex, ey) in enumerate(((cx - 260, cy + 60), (cx + 260, cy + 60))):
        if len(c.emojis) > i + 1:
            put_emoji(img, c.e(i + 1), 100, ex, ey)
    pill(d, c.label, W / 2, 620, size=34, fill=t["main"])
    rows = plan_chips(d, c.items, W - 2 * s - 80, max_rows=2)
    t_top, t_bot = 680, WH - s - 90 - chips_h(rows)
    f, lines, lh = fit_text(d, c.title, "serif", W - 2 * s - 80, t_bot - t_top, start=82, minimum=44)
    draw_lines(d, lines, f, W / 2, t_top + (t_bot - t_top - len(lines) * lh) / 2, t["main"], lh)
    draw_chips(d, rows, W / 2, t_bot, fill=WHITE, outline=t["accent"], color=t["deep"])
    d.text((W / 2, WH - s - 40), c.sublabel, font=font("sans_r", 30), fill=t["deep"], anchor="mm")
    return img


LAYOUTS = {"card": lay_card, "hero": lay_hero, "chat": lay_chat, "quiz": lay_quiz, "poster": lay_poster,
           "stickers": lay_stickers, "notebook": lay_notebook, "tiles": lay_tiles}


# ====================================================================== pastki qism (logo tasmasi)
FOOTERS = ["solid", "wave", "split", "float", "light", "zigzag", "ribbon", "center"]


@lru_cache(maxsize=8)
def _logo_mask(path: str) -> Image.Image:
    im = Image.open(path).convert("RGBA")
    return im.crop(im.getbbox()).split()[3]


def logo_image(path: Path, height: int, color: str) -> Image.Image:
    """Bir rangli logoni istalgan rangga bo'yab, kerakli balandlikka keltiradi."""
    mask = _logo_mask(str(path))
    w = max(1, round(mask.width * height / mask.height))
    mask = mask.resize((w, height), Image.LANCZOS)
    im = Image.new("RGBA", (w, height), (*_rgb(color), 255))
    im.putalpha(mask)
    return im


def _label_block(d, label, sublabel, x, y_mid, max_w, color, sub_color, anchor_x="r", size=46):
    f, lines, lh = fit_text(d, label, "sans", max_w, 92, start=size, minimum=26, spacing=1.08, max_lines=2)
    fs = font("sans_r", 28)
    total = len(lines) * lh + 10 + 30
    y = y_mid - total / 2
    a = {"r": "ra", "l": "la", "m": "ma"}[anchor_x]
    y = draw_lines(d, lines, f, x, y, color, lh, anchor=a)
    d.text((x, y + 8), sublabel, font=fs, fill=sub_color, anchor=a)


def draw_footer(img: Image.Image, t: dict, style: str, label: str, sublabel: str, logo_path: Path,
                band: int = BAND) -> None:
    """Pastki tasmani tanlangan uslub va tema rangida chizadi (img joyida o'zgaradi)."""
    d = ImageDraw.Draw(img)
    top, m = H - band, 40
    mid = top + band / 2
    style = style if style in FOOTERS else "solid"

    def logo_left(color, h=band - 46, x=m, y_mid=mid):
        lg = logo_image(logo_path, h, color)
        img.paste(lg, (round(x), round(y_mid - h / 2)), lg)
        return lg.width

    def logo_right(color, h=band - 46, x=W - m, y_mid=mid):
        lg = logo_image(logo_path, h, color)
        img.paste(lg, (round(x - lg.width), round(y_mid - h / 2)), lg)
        return lg.width

    if style == "solid":
        d.rectangle((0, top, W, H), fill=t["main"])
        d.rectangle((0, top, W, top + 6), fill=t["accent"])
        lw = logo_left(WHITE, y_mid=mid + 3)
        _label_block(d, label, sublabel, W - m, mid + 3, W - lw - 3 * m, WHITE, t["on_main"])
    elif style == "wave":
        def wave(y0, amp, ph):
            return [(x, y0 + amp * math.sin(2 * math.pi * x / 360 + ph)) for x in range(0, W + 10, 10)]
        d.polygon(wave(top - 4, 11, 1.2) + [(W, H), (0, H)], fill=t["accent"])
        d.polygon(wave(top + 8, 11, 0.0) + [(W, H), (0, H)], fill=t["main"])
        lw = logo_left(WHITE, y_mid=mid + 8)
        _label_block(d, label, sublabel, W - m, mid + 8, W - lw - 3 * m, WHITE, t["on_main"])
    elif style == "split":
        d.rectangle((0, top, W, H), fill=t["main"])
        d.polygon([(0, top), (400, top), (350, H), (0, H)], fill=t["deep"])
        d.polygon([(400, top), (418, top), (368, H), (350, H)], fill=t["accent"])
        logo_left(WHITE, h=band - 54, x=46)
        _label_block(d, label, sublabel, W - m, mid, W - 420 - 2 * m, WHITE, t["on_main"])
    elif style == "float":
        x0, y0, x1, y1 = 28, top + 12, W - 28, H - 22
        d.rounded_rectangle((x0 + 8, y0 + 10, x1 + 8, y1 + 10), radius=34, fill=t["shadow"])
        d.rounded_rectangle((x0, y0, x1, y1), radius=34, fill=WHITE, outline=t["main"], width=4)
        d.rounded_rectangle((x0 + 18, y0 + 22, x0 + 30, y1 - 22), radius=6, fill=t["accent"])
        cm = (y0 + y1) / 2
        lw = logo_left(t["main"], h=78, x=x0 + 52, y_mid=cm)
        d.line((x0 + 52 + lw + 30, y0 + 24, x0 + 52 + lw + 30, y1 - 24), fill=t["pale"], width=3)
        _label_block(d, label, sublabel, x1 - 34, cm, x1 - x0 - lw - 160, t["main"], t["deep"], size=42)
    elif style == "light":
        d.rectangle((0, top, W, H), fill=t["light"])
        d.rectangle((0, top, W, top + 8), fill=t["main"])
        for i, x in enumerate(range(24, W, 48)):
            d.ellipse((x - 4, H - 16, x + 4, H - 8), fill=t["accent"] if i % 2 else t["pale"])
        lw = logo_left(t["main"], h=band - 60, y_mid=mid)
        _label_block(d, label, sublabel, W - m, mid - 2, W - lw - 3 * m, t["deep"], t["main"])
    elif style == "zigzag":
        teeth = 36
        pts = [(0, top + 4)]
        for x in range(0, W + teeth, teeth):
            pts += [(x + teeth / 2, top - 14), (x + teeth, top + 4)]
        d.polygon(pts + [(W, H), (0, H)], fill=t["deep"])
        d.rectangle((0, top + 10, W, H), fill=t["main"])
        d.rectangle((0, H - 12, W, H), fill=t["accent"])
        lw = logo_right(WHITE, y_mid=mid + 2)
        _label_block(d, label, sublabel, m, mid + 2, W - lw - 3 * m, WHITE, t["on_main"], anchor_x="l")
    elif style == "ribbon":
        d.rectangle((0, top, W, H), fill=t["dark"])
        d.rectangle((0, top, W, top + 8), fill=t["accent"])
        lw = logo_right(WHITE, h=band - 56, y_mid=mid + 4)
        f, lines, lh = fit_text(d, label, "sans", W - lw - 280, 60, start=42, minimum=26, max_lines=1)
        tw = d.textlength(lines[0], font=f)
        ty0, ty1 = top + 30, top + 98
        d.polygon([(0, ty0), (m + tw + 40, ty0), (m + tw + 70, (ty0 + ty1) / 2), (m + tw + 40, ty1), (0, ty1)],
                  fill=t["main"])
        d.text((m, (ty0 + ty1) / 2), lines[0], font=f, fill=WHITE, anchor="lm")
        d.text((m, ty1 + 24), sublabel, font=font("sans_r", 26), fill=t["on_main"], anchor="lm")
    elif style == "center":
        pts = [(x, top + 14 - 30 * (1 - ((x - W / 2) / (W / 2)) ** 2)) for x in range(0, W + 10, 10)]
        d.polygon(pts + [(W, H), (0, H)], fill=t["main"])
        d.line(pts, fill=t["accent"], width=6)
        lg = logo_image(logo_path, 92, WHITE)
        img.paste(lg, (round(W / 2 - lg.width / 2), round(mid + 6 - 46)), lg)
        side = W / 2 - lg.width / 2 - m - 34
        f, lines, lh = fit_text(d, label, "sans", side, 90, start=40, minimum=24, spacing=1.08, max_lines=2)
        draw_lines(d, lines, f, m, mid + 6 - len(lines) * lh / 2, WHITE, lh, anchor="la")
        d.text((W - m, mid + 6), sublabel, font=font("sans_r", 28), fill=t["on_main"], anchor="rm")


# ====================================================================== tanlash
def _least_recent(options: list[str], recent: list[str], rng: random.Random) -> str:
    """Oxirgi postlarda eng kam ishlatilganini tanlaydi."""
    def score(o):
        return (recent.count(o), -(recent.index(o) if o in recent else 99))
    best = min(score(o) for o in options)
    return rng.choice([o for o in options if score(o) == best])


def choose_layout(post_type: str, style_id: str, recent: list[str], has_dialog: bool,
                  rng: random.Random) -> str:
    opts = list(LAYOUTS_BY_TYPE.get(post_type, ["card", "hero", "poster", "stickers"]))
    if style_id in ("test", "challenge") and "quiz" not in opts:
        opts.append("quiz")
    if style_id == "chat" and has_dialog and "chat" not in opts:
        opts.append("chat")
    if not has_dialog:
        opts = [o for o in opts if o != "chat"] or ["poster"]
    elif post_type in DIALOG_TYPES and "chat" in opts and recent[:1] != ["chat"]:
        return "chat"
    return _least_recent(opts, recent[:8], rng)


def choose_scene(lang: str, wanted: str | None, recent: list[str], rng: random.Random) -> str:
    if wanted in SCENES:
        return wanted
    return _least_recent(SCENES, recent[:4], rng)


def choose_theme(wanted, emojis: list[str], recent: list[str], rng: random.Random) -> str:
    """Mavzuga mos rang: yozuvchi tanlovi → emojidan taxmin → kam ishlatilgani.
    Oxirgi ikki postdagi rang takrorlanmaydi (o'rniga unga yaqin rang olinadi)."""
    if isinstance(wanted, str):
        wanted = [wanted]
    cands = [str(w).strip().lower() for w in wanted or []]
    cands = [w for w in cands if w in THEMES]
    guess = guess_theme(emojis)
    if guess and guess not in cands:
        cands.append(guess)
    last = [r for r in recent[:2] if r]
    for c in cands:
        if c not in last:
            return c
    if cands:
        rel = [r for r in THEME_RELATED.get(cands[0], []) if r not in last]
        if rel:
            return rel[0]
    return _least_recent([n for n in THEMES if n not in last] or list(THEMES), recent[:8], rng)


def choose_footer(recent: list[str], rng: random.Random) -> str:
    """Oxirgi 7 ta postda ishlatilmagan tasma uslubi — 8 xil uslub navbat bilan almashadi."""
    return _least_recent(FOOTERS, [r for r in recent[:len(FOOTERS) - 1] if r], rng)


def render_post(*, post_type: str, style_id: str, lang: str = "tr", title: str, label: str, sublabel: str,
                items: list[str] | None = None, visual: dict | None = None,
                lines: list[dict] | None = None, recent_layouts: list[str] | None = None,
                recent_scenes: list[str] | None = None,
                recent_themes: list[str] | None = None) -> tuple[Image.Image, dict]:
    visual = visual if isinstance(visual, dict) else {}
    title = clean_title(title) or label.title()
    seed = zlib.crc32(f"{title}|{post_type}|{style_id}".encode())
    rng = random.Random(seed)
    emojis = valid_emojis(visual.get("emojis"), DEFAULT_EMOJIS.get(post_type, ["📚", "💡", "✏️"]))
    scene = choose_scene(lang, str(visual.get("scene") or "").lower().strip(), recent_scenes or [], rng)
    theme = choose_theme(visual.get("colors") or visual.get("color"), visual.get("emojis") or [],
                         recent_themes or [], rng)
    dialog = [x for x in (lines or []) if str(x.get("text", "")).strip()]
    use_dialog = bool(dialog) and style_id != "diolog_boshqotirma" and (
        post_type in DIALOG_TYPES or style_id == "chat")
    layout = choose_layout(post_type, style_id, recent_layouts or [], use_dialog, rng)
    ctx = Ctx(title=title, label=label, sublabel=sublabel, items=[str(i) for i in items or []],
              emojis=emojis, scene=scene, lang=lang, lines=dialog if use_dialog else [], seed=seed,
              t=THEMES[theme])
    img = LAYOUTS[layout](ctx)
    return img, {"layout": layout, "scene": scene, "theme": theme, "emojis": emojis[:5]}
