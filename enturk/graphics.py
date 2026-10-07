"""Gemini'siz grafika: har bir post uchun turi va mavzusiga mos maket, emoji va Turkiya sahnasi.

Maketlar: card, hero, chat, quiz, poster, stickers, notebook, tiles.
Sahnalar: skyline, bosphorus, balloons, tulips, tea (turkcha) va london (inglizcha).
Emoji va sahnani yozuvchi agent mavzuga qarab tanlaydi (draft["visual"]).
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

RED, DEEP, WINE = "#E30A17", "#A8060F", "#6E0A12"
CREAM, PINK, PALE = "#FFF8F3", "#FDECEC", "#F8DEDF"
TURQ, GOLD, INK, WHITE = "#13807F", "#F2B33D", "#1F1F1F", "#FFFFFF"
CLEAR = (0, 0, 0, 0)

FONT_FILES = {"sans": "font-bold.ttf", "sans_r": "font-regular.ttf",
              "display": "Carlito-Bold.ttf", "serif": "Caladea-Bold.ttf"}
EMOJI_PATHS = [ASSETS / "NotoColorEmoji.ttf",
               Path("/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf"),
               Path("/usr/share/fonts/noto/NotoColorEmoji.ttf")]

SCENES_TR = ["skyline", "bosphorus", "balloons", "tulips", "tea"]
SCENES_EN = ["london"]
DIALOG_TYPES = {"haqiqiy_diolog", "en_diolog"}

LAYOUTS_BY_TYPE = {
    "yangi_sozlar": ["card", "hero", "stickers", "poster", "tiles"],
    "kunlik_iboralar": ["hero", "poster", "stickers", "tiles"],
    "mavzuli_lugat": ["card", "tiles", "stickers", "poster"],
    "haqiqiy_diolog": ["chat", "poster"],
    "en_diolog": ["chat", "poster"],
    "hayotiy_maslahat": ["notebook", "poster", "hero", "card"],
    "imtihon": ["notebook", "quiz", "hero"],
    "haftalik_takrorlash": ["quiz", "notebook", "stickers"],
    "en_iboralar": ["hero", "stickers", "poster"],
    "en_sozlar": ["card", "stickers", "hero", "poster"],
}
DEFAULT_EMOJIS = {
    "yangi_sozlar": ["📚", "✏️", "💡", "📝"], "kunlik_iboralar": ["💬", "🗣️", "👋", "😊"],
    "mavzuli_lugat": ["📖", "🔤", "🧩", "📌"], "haqiqiy_diolog": ["💬", "👩", "👨", "☕"],
    "hayotiy_maslahat": ["💡", "✅", "⚠️", "🧭"], "imtihon": ["📝", "🎯", "⏱️", "🏆"],
    "haftalik_takrorlash": ["🔁", "🧠", "✅", "🏆"], "en_iboralar": ["💬", "🇬🇧", "👋", "😊"],
    "en_diolog": ["💬", "🇬🇧", "☕", "🎧"], "en_sozlar": ["📚", "🇬🇧", "💡", "✏️"],
}


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


def put_emoji(img, ch, px, cx, cy, rot=0.0, sticker=False):
    im = emoji(ch, px)
    if im is None:
        return
    if sticker:
        im = make_sticker(im, border=max(6, px // 16))
    if rot:
        im = im.rotate(rot, expand=True, resample=Image.BICUBIC)
    paste_c(img, im, cx, cy)


def make_sticker(im: Image.Image, border: int = 10) -> Image.Image:
    """Oq kontur va yumshoq soya — stiker ko'rinishi."""
    pad = border * 3
    base = Image.new("RGBA", (im.width + pad * 2, im.height + pad * 2), CLEAR)
    alpha = Image.new("L", base.size, 0)
    alpha.paste(im.split()[3], (pad, pad))
    grown = alpha.filter(ImageFilter.MaxFilter(border * 2 + 1)).point(lambda v: 255 if v > 40 else 0)
    shadow = grown.filter(ImageFilter.GaussianBlur(border))
    base.paste(Image.new("RGBA", base.size, (90, 10, 15, 70)), (border // 2, border), shadow)
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
        if (len(lines) <= max_lines and len(lines) * lh <= max_h) or size <= minimum:
            break
        size -= 4
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


def draw_chips(d, rows, cx, y, *, fname="sans", size=34, fill=PINK, outline=RED, color=RED, gap=16, h=58):
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


def tulip_pattern(d, color, step=120, height=WH + 60):
    for yi, y in enumerate(range(30, height, step)):
        for x in range(-40 + (step // 2 if yi % 2 else 0), W + 60, step):
            d.ellipse((x - 12, y - 20, x + 12, y + 8), fill=color)
            d.polygon([(x - 16, y - 6), (x - 5, y - 27), (x, y - 10)], fill=color)
            d.polygon([(x + 16, y - 6), (x + 5, y - 27), (x, y - 10)], fill=color)
            d.line((x, y + 8, x, y + 30), fill=color, width=4)


def dot_grid(d, color, step=42, r=3, height=WH):
    for y in range(step // 2, height, step):
        for x in range(step // 2, W, step):
            d.ellipse((x - r, y - r, x + r, y + r), fill=color)


def tile_image(w, h, s=120, red=RED, turq=TURQ, bg=WHITE, line=PALE) -> Image.Image:
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


def _london(d, base, c, accent=None):
    d.rectangle((0, base - 18, W, base), fill=c)
    for bx, w, h in ((40, 120, 140), (470, 90, 190), (960, 160, 170)):
        d.rectangle((bx - w // 2, base - h, bx + w // 2, base), fill=c)
        for wy in range(base - h + 20, base - 30, 40):
            for wx in range(bx - w // 2 + 16, bx + w // 2 - 20, 32):
                d.rectangle((wx, wy, wx + 14, wy + 20), fill=CLEAR)
    x = 230                                             # soat minorasi
    d.rectangle((x - 50, base - 300, x + 50, base), fill=c)
    d.rectangle((x - 64, base - 390, x + 64, base - 300), fill=c)
    d.ellipse((x - 42, base - 387, x + 42, base - 303), fill=CLEAR)
    d.ellipse((x - 34, base - 379, x + 34, base - 311), fill=c)
    d.ellipse((x - 28, base - 373, x + 28, base - 317), fill=CLEAR)
    d.line((x, base - 345, x, base - 368), fill=c, width=5)
    d.line((x, base - 345, x + 16, base - 345), fill=c, width=5)
    d.polygon([(x - 64, base - 390), (x, base - 480), (x + 64, base - 390)], fill=c)
    d.line((x, base - 480, x, base - 520), fill=c, width=6)
    for wy in range(base - 280, base - 30, 50):
        d.rectangle((x - 30, wy, x - 10, wy + 30), fill=CLEAR)
        d.rectangle((x + 10, wy, x + 30, wy + 30), fill=CLEAR)
    x = 740                                             # ikki qavatli avtobus
    d.rounded_rectangle((x - 210, base - 250, x + 210, base - 44), radius=26, fill=c)
    for row_y in (base - 228, base - 140):
        for wx in range(x - 180, x + 170, 70):
            d.rounded_rectangle((wx, row_y, wx + 54, row_y + 52), radius=8, fill=CLEAR)
    for wx in (x - 125, x + 125):
        d.ellipse((wx - 36, base - 80, wx + 36, base - 8), fill=c)
        d.ellipse((wx - 14, base - 58, wx + 14, base - 30), fill=CLEAR)


SCENE_FUNCS = {"skyline": _skyline, "bosphorus": _bosphorus, "balloons": _balloons, "tulips": _tulips,
               "tea": _tea, "london": _london}


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
    lang: str
    lines: list[dict] = field(default_factory=list)
    seed: int = 0

    @property
    def rng(self) -> random.Random:
        return random.Random(self.seed)

    def e(self, i: int) -> str:
        return self.emojis[i % len(self.emojis)] if self.emojis else ""


def lay_card(c: Ctx) -> Image.Image:
    img = Image.new("RGB", (W, H), CREAM)
    d = ImageDraw.Draw(img)
    tulip_pattern(d, PALE)
    paste_scene(img, c.scene, RED, accent=WHITE)
    m, top, bottom = 80, 120, WH - 345
    d.rounded_rectangle((m + 10, top + 14, W - m + 10, bottom + 14), radius=44, fill="#EBCACA")
    d.rounded_rectangle((m, top, W - m, bottom), radius=44, fill=WHITE, outline=RED, width=7)
    pill(d, c.label, W / 2, top, size=36)
    for i, x in enumerate((W / 2 - 170, W / 2, W / 2 + 170)[:max(1, min(3, len(c.emojis)))]):
        put_emoji(img, c.e(i), 118 if i != 1 else 140, x if len(c.emojis) >= 3 else W / 2, top + 140)
        if len(c.emojis) < 3:
            break
    rows = plan_chips(d, c.items, W - 2 * m - 80)
    t_top, t_bot = top + 225, bottom - 84 - chips_h(rows) - 26
    f, lines, lh = fit_text(d, c.title, "sans", W - 2 * m - 100, t_bot - t_top, start=76, max_lines=3)
    draw_lines(d, lines, f, W / 2, t_top + (t_bot - t_top - len(lines) * lh) / 2, INK, lh)
    draw_chips(d, rows, W / 2, t_bot + 26)
    d.text((W / 2, bottom - 42), c.sublabel, font=font("sans_r", 32), fill=DEEP, anchor="mm")
    return img


def lay_hero(c: Ctx) -> Image.Image:
    img = Image.new("RGB", (W, H), RED)
    d = ImageDraw.Draw(img)
    cx, cy = W / 2, 360
    for k in range(24):                                  # quyosh nurlari
        if k % 2:
            continue
        a0, a1 = k * 15, k * 15 + 15
        d.pieslice((cx - 1300, cy - 1300, cx + 1300, cy + 1300), a0, a1, fill="#EA1B27")
    paste_scene(img, c.scene, DEEP, accent=None, scale=0.82)
    d.ellipse((cx - 228 + 14, cy - 228 + 18, cx + 228 + 14, cy + 228 + 18), fill=DEEP)
    d.ellipse((cx - 228, cy - 228, cx + 228, cy + 228), fill=WHITE)
    put_emoji(img, c.e(0), 290, cx, cy)
    for i, ang in enumerate((-35, 215, 145)[:max(0, len(c.emojis) - 1)]):
        ex = cx + math.cos(math.radians(ang)) * 300
        ey = cy + math.sin(math.radians(ang)) * 260
        d.ellipse((ex - 82 + 6, ey - 82 + 8, ex + 82 + 6, ey + 82 + 8), fill=DEEP)
        d.ellipse((ex - 82, ey - 82, ex + 82, ey + 82), fill=WHITE)
        put_emoji(img, c.e(i + 1), 104, ex, ey)
    pill(d, c.label, W / 2, 680, fill=WHITE, color=RED, size=34)
    rows = plan_chips(d, c.items, W - 160, max_rows=1)
    t_top, t_bot = 740, 960 - chips_h(rows)
    f, lines, lh = fit_text(d, c.title, "display", W - 140, t_bot - t_top, start=96, minimum=48)
    draw_lines(d, lines, f, W / 2, t_top + (t_bot - t_top - len(lines) * lh) / 2, WHITE, lh)
    draw_chips(d, rows, W / 2, t_bot + 4, fill=DEEP, outline=WHITE, color=WHITE)
    d.text((W / 2, 1010), c.sublabel, font=font("sans_r", 30), fill="#FFD9DB", anchor="mm")
    return img


def lay_chat(c: Ctx) -> Image.Image:
    img = Image.new("RGB", (W, H), "#FFF5F5")
    d = ImageDraw.Draw(img)
    dot_grid(d, PALE)
    paste_scene(img, c.scene, "#F3C4C7", accent=None)
    pill(d, c.label, W / 2, 90, size=34)
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
        d.ellipse((ax - 58, y - 4, ax + 58, y + 112), fill=WHITE, outline=RED, width=4)
        put_emoji(img, male_e if right else female_e, 76, ax, y + 54)
        x0 = ax - 80 - bw if right else ax + 80
        fill, col = (RED, WHITE) if right else (WHITE, INK)
        d.rounded_rectangle((x0 + 6, y + 8, x0 + bw + 6, y + bh + 8), radius=30, fill="#EBCACA")
        d.rounded_rectangle((x0, y, x0 + bw, y + bh), radius=30, fill=fill,
                            outline=None if right else RED, width=0 if right else 3)
        tx = x0 + bw if right else x0
        d.polygon([(tx, y + 30), (tx + (22 if right else -22), y + 40), (tx, y + 58)], fill=fill)
        draw_lines(d, bl, fb, x0 + 32, y + 20, col, 48, anchor="la")
        y += max(bh, 116) + 34
    for i in range(min(3, len(c.emojis))):
        put_emoji(img, c.e(i), 74, W / 2 + (i - 1) * 110, 1080, rot=(i - 1) * -10, sticker=True)
    d.text((W / 2, 1160), c.sublabel, font=font("sans_r", 30), fill=DEEP, anchor="mm")
    return img


def lay_quiz(c: Ctx) -> Image.Image:
    img = Image.new("RGB", (W, H), WHITE)
    d = ImageDraw.Draw(img)
    rng = c.rng
    fq = font("display", 240)
    for _ in range(9):
        layer = Image.new("RGBA", (220, 300), CLEAR)
        ImageDraw.Draw(layer).text((110, 150), "?", font=fq, fill=PALE, anchor="mm")
        layer = layer.rotate(rng.uniform(-30, 30), expand=True)
        img.paste(layer, (rng.randint(-60, W - 120), rng.randint(-60, WH - 260)), layer)
    cx, cy = W / 2, 250
    d.ellipse((cx - 160 + 10, cy - 160 + 14, cx + 160 + 10, cy + 160 + 14), fill="#F3C4C7")
    d.ellipse((cx - 160, cy - 160, cx + 160, cy + 160), fill=RED)
    put_emoji(img, c.e(0), 190, cx, cy)
    bx, by = cx + 125, cy + 110
    d.ellipse((bx - 52, by - 52, bx + 52, by + 52), fill=WHITE, outline=RED, width=6)
    d.text((bx, by + 4), "?", font=font("display", 84), fill=RED, anchor="mm")
    pill(d, c.label, W / 2, 470, size=34)
    f, lines, lh = fit_text(d, c.title, "sans", W - 180, 170, start=66, minimum=40, max_lines=3)
    draw_lines(d, lines, f, W / 2, 530 + (170 - len(lines) * lh) / 2, INK, lh)
    opts = [i for i in c.items if i and len(i) <= 32][:3]
    fo = font("sans", 40)
    y = 720
    for k, it in enumerate(opts):
        d.rounded_rectangle((110 + 6, y + 8, W - 110 + 6, y + 96 + 8), radius=26, fill="#EBCACA")
        d.rounded_rectangle((110, y, W - 110, y + 96), radius=26, fill=WHITE, outline=RED, width=4)
        d.ellipse((132, y + 14, 200, y + 82), fill=RED)
        d.text((166, y + 48), "ABC"[k], font=font("sans", 38), fill=WHITE, anchor="mm")
        txt = it
        while d.textlength(txt, font=fo) > W - 360 and len(txt) > 4:
            txt = txt[:-2]
        d.text((230, y + 48), txt if txt == it else txt.rstrip() + "…", font=fo, fill=INK, anchor="lm")
        y += 110
    strip = tile_image(W, 70, s=70) if c.lang != "en" else None
    if strip is not None:
        img.paste(strip, (0, WH - 70))
    else:
        for x in range(0, W, 60):
            d.polygon([(x, WH), (x + 30, WH - 50), (x + 60, WH)], fill=RED if (x // 60) % 2 else PALE)
    d.text((W / 2, WH - 100), c.sublabel, font=font("sans_r", 30), fill=DEEP, anchor="mm")
    return img


def lay_poster(c: Ctx) -> Image.Image:
    img = Image.new("RGB", (W, H), CREAM)
    d = ImageDraw.Draw(img)
    split = 640
    red_layer = Image.new("RGBA", (W, H), CLEAR)
    rd = ImageDraw.Draw(red_layer)
    rd.polygon([(0, 0), (W, 0), (W, split - 60), (0, split + 40)], fill=RED)
    img.paste(red_layer, (0, 0), red_layer)
    tulip_pattern(d, "#EC2733", height=split - 120)
    paste_scene(img, c.scene, DEEP, accent="#F04A54", base=split - 10, scale=0.95)
    d.polygon([(0, split + 40), (W, split - 60), (W, split + 4), (0, split + 104)], fill=CREAM)
    cx, cy = W / 2, 560
    d.ellipse((cx - 178, cy - 178, cx + 178, cy + 178), fill=RED)
    d.ellipse((cx - 164, cy - 164, cx + 164, cy + 164), fill=WHITE)
    put_emoji(img, c.e(0), 220, cx, cy)
    for i, (ex, ey, rot) in enumerate(((cx - 250, cy + 70, 14), (cx + 250, cy + 60, -12))):
        if len(c.emojis) > i + 1:
            put_emoji(img, c.e(i + 1), 120, ex, ey, rot=rot, sticker=True)
    pill(d, c.label, W / 2, 800, fill=PINK, color=RED, outline=RED, size=32)
    rows = plan_chips(d, c.items, W - 160, max_rows=1)
    t_top, t_bot = 850, 1150 - chips_h(rows)
    f, lines, lh = fit_text(d, c.title, "serif", W - 160, t_bot - t_top, start=84, minimum=46)
    draw_lines(d, lines, f, W / 2, t_top + (t_bot - t_top - len(lines) * lh) / 2, INK, lh)
    draw_chips(d, rows, W / 2, t_bot, fill=RED, outline=None, color=WHITE)
    return img


def lay_stickers(c: Ctx) -> Image.Image:
    img = Image.new("RGB", (W, H), CREAM)
    d = ImageDraw.Draw(img)
    dot_grid(d, "#F2CFD1")
    rng = c.rng
    slots = [(170, 190), (900, 200), (540, 150), (160, 1030), (920, 1020), (540, 1070)]
    rng.shuffle(slots)
    n = min(len(c.emojis), 6) if c.emojis else 0
    for i in range(n):
        sx, sy = slots[i]
        put_emoji(img, c.e(i), rng.randint(130, 175), sx + rng.randint(-25, 25), sy + rng.randint(-20, 20),
                  rot=rng.uniform(-18, 18), sticker=True)
    pw, ph = 860, 520
    panel = Image.new("RGBA", (pw + 30, ph + 30), CLEAR)
    pd = ImageDraw.Draw(panel)
    pd.rounded_rectangle((16, 20, pw + 16, ph + 20), radius=40, fill="#E7C2C4")
    pd.rounded_rectangle((0, 0, pw, ph), radius=40, fill=WHITE, outline=RED, width=8)
    pill(pd, c.label, pw / 2, 80, size=34)
    rows = plan_chips(pd, c.items, pw - 80, max_rows=2)
    t_top, t_bot = 140, ph - 50 - chips_h(rows)
    f, lines, lh = fit_text(pd, c.title, "display", pw - 90, t_bot - t_top, start=92, minimum=46)
    draw_lines(pd, lines, f, pw / 2, t_top + (t_bot - t_top - len(lines) * lh) / 2, RED, lh)
    draw_chips(pd, rows, pw / 2, t_bot)
    panel = panel.rotate(rng.choice((-2.5, 2.0, -1.5)), expand=True, resample=Image.BICUBIC)
    paste_c(img, panel, W / 2, 610)
    d.text((W / 2, WH - 26), c.sublabel, font=font("sans_r", 28), fill=DEEP, anchor="mm")
    return img


def lay_notebook(c: Ctx) -> Image.Image:
    img = Image.new("RGB", (W, H), RED)
    d = ImageDraw.Draw(img)
    dot_grid(d, "#D10815", step=46, r=4)
    pw, ph = 880, 1000
    paper = Image.new("RGBA", (pw + 30, ph + 30), CLEAR)
    p = ImageDraw.Draw(paper)
    p.rectangle((14, 18, pw + 14, ph + 18), fill=(110, 5, 12, 120))
    p.rectangle((0, 0, pw, ph), fill=WHITE)
    for ly in range(250, ph - 30, 66):
        p.line((0, ly, pw, ly), fill="#F1CDD0", width=3)
    p.line((110, 0, 110, ph), fill=RED, width=4)
    for hy in (180, ph // 2, ph - 180):
        p.ellipse((36, hy - 18, 72, hy + 18), fill="#E9E2E2")
    p.text((150, 70), c.label, font=font("sans", 32), fill=RED, anchor="la")
    f, lines, lh = fit_text(p, c.title, "serif", pw - 330, 240, start=70, minimum=42, max_lines=4)
    draw_lines(p, lines, f, 150, 128, INK, lh, anchor="la")
    y = max(250 + 66 * 3, 128 + len(lines) * lh + 70)
    y = 250 + 66 * math.ceil((y - 250) / 66)
    fi = font("serif", 44)
    for it in [i for i in c.items if i][:5]:
        if y > ph - 120:
            break
        txt = it if len(it) <= 34 else it[:33].rstrip() + "…"
        p.rounded_rectangle((150, y - 50, 192, y - 8), radius=6, outline=RED, width=4)
        p.line((158, y - 30, 170, y - 16, 186, y - 44), fill=RED, width=5)
        p.text((214, y - 12), txt, font=fi, fill=INK, anchor="ls")
        y += 66
    p.text((pw - 40, ph - 40), c.sublabel, font=font("sans_r", 28), fill=DEEP, anchor="rs")
    paper = paper.rotate(-1.2, expand=True, resample=Image.BICUBIC)
    paste_c(img, paper, W / 2, 590)
    put_emoji(img, c.e(0), 170, W - 190, 210, rot=12, sticker=True)
    if len(c.emojis) > 1:
        put_emoji(img, c.e(1), 120, 150, 1050, rot=-14, sticker=True)
    cx = 700
    d.rounded_rectangle((cx - 22, 60, cx + 22, 170), radius=22, outline="#9A9A9A", width=8)
    d.rounded_rectangle((cx - 10, 80, cx + 10, 150), radius=10, outline="#9A9A9A", width=6)
    return img


def lay_tiles(c: Ctx) -> Image.Image:
    img = Image.new("RGB", (W, H), CREAM)
    t = 110
    img.paste(tile_image(W, WH, s=t))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((t - 14, t - 14, W - t + 14, WH - t + 14), radius=30, fill=RED)
    d.rounded_rectangle((t, t, W - t, WH - t), radius=24, fill=CREAM)
    cx, cy = W / 2, 370
    d.ellipse((cx - 190, cy - 190, cx + 190, cy + 190), fill=RED)
    d.ellipse((cx - 176, cy - 176, cx + 176, cy + 176), fill=WHITE)
    d.ellipse((cx - 160, cy - 160, cx + 160, cy + 160), outline=TURQ, width=5)
    put_emoji(img, c.e(0), 220, cx, cy)
    for i, (ex, ey) in enumerate(((cx - 260, cy + 60), (cx + 260, cy + 60))):
        if len(c.emojis) > i + 1:
            put_emoji(img, c.e(i + 1), 100, ex, ey)
    pill(d, c.label, W / 2, 620, size=34)
    rows = plan_chips(d, c.items, W - 2 * t - 80, max_rows=2)
    t_top, t_bot = 680, WH - t - 90 - chips_h(rows)
    f, lines, lh = fit_text(d, c.title, "serif", W - 2 * t - 80, t_bot - t_top, start=82, minimum=44)
    draw_lines(d, lines, f, W / 2, t_top + (t_bot - t_top - len(lines) * lh) / 2, RED, lh)
    draw_chips(d, rows, W / 2, t_bot, fill=WHITE, outline=TURQ, color=TURQ)
    d.text((W / 2, WH - t - 40), c.sublabel, font=font("sans_r", 30), fill=DEEP, anchor="mm")
    return img


LAYOUTS = {"card": lay_card, "hero": lay_hero, "chat": lay_chat, "quiz": lay_quiz, "poster": lay_poster,
           "stickers": lay_stickers, "notebook": lay_notebook, "tiles": lay_tiles}


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
    pool = SCENES_EN if lang == "en" else SCENES_TR
    if wanted in pool:
        return wanted
    return _least_recent(pool, recent[:4], rng)


def render_post(*, post_type: str, style_id: str, lang: str, title: str, label: str, sublabel: str,
                items: list[str] | None = None, visual: dict | None = None,
                lines: list[dict] | None = None, recent_layouts: list[str] | None = None,
                recent_scenes: list[str] | None = None) -> tuple[Image.Image, dict]:
    visual = visual if isinstance(visual, dict) else {}
    title = clean_title(title) or label.title()
    seed = zlib.crc32(f"{title}|{post_type}|{style_id}".encode())
    rng = random.Random(seed)
    emojis = valid_emojis(visual.get("emojis"), DEFAULT_EMOJIS.get(post_type, ["📚", "💡", "✏️"]))
    scene = choose_scene(lang, str(visual.get("scene") or "").lower().strip(), recent_scenes or [], rng)
    dialog = [x for x in (lines or []) if str(x.get("text", "")).strip()]
    use_dialog = bool(dialog) and style_id != "diolog_boshqotirma" and (
        post_type in DIALOG_TYPES or style_id == "chat")
    layout = choose_layout(post_type, style_id, recent_layouts or [], use_dialog, rng)
    ctx = Ctx(title=title, label=label, sublabel=sublabel, items=[str(i) for i in items or []],
              emojis=emojis, scene=scene, lang=lang, lines=dialog if use_dialog else [], seed=seed)
    img = LAYOUTS[layout](ctx)
    return img, {"layout": layout, "scene": scene, "emojis": emojis[:5]}
