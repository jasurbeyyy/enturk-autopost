"""Foto dizayner: Unsplash fotosi + sarlavha, turkcha so'zlar va JSR logosi.

Ish tartibi:
  1. "Foto muharriri" agenti (Gemini, matn) post mavzusidan 3 ta inglizcha qidiruv so'zi va mavzuga
     mos rang tanlaydi. Mavzuni foto bilan yaxshi ko'rsatib bo'lmasa (masalan, imtihon qoidalari),
     "photo_ok": false qaytaradi va post odatdagi kreativ illyustratsiya bilan chiqadi.
  2. Unsplash'dan portret fotolar qidiriladi: oxirgi postlarda ishlatilganlari, Unsplash+ (pullik)
     va kichik fotolar tashlanadi. Rasm tekshiruvchi fotoning mavzuga mosligini tekshiradi.
  3. Kod 7 xil foto maketidan (gradient, rangli plashka, duoton, panel, karta, shisha, vinyetka)
     oxirgi postlarda bo'lmaganini tanlaydi va sarlavha, rubrika, so'zlar hamda logoni qo'yadi.
     Matn o'qilishi (kontrast) kodda kafolatlanadi.
  4. Unsplash qoidalari: foto ishlatilganda download endpoint chaqiriladi, post matniga esa
     fotograf va Unsplash nomi (havola bilan) qo'shiladi.
"""
from __future__ import annotations

import io
import logging
import math
import random
from dataclasses import dataclass
from html import escape
from pathlib import Path

import httpx
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageOps

from . import design

log = logging.getLogger(__name__)

W, H = design.W, design.H
API = "https://api.unsplash.com"
APP = "jasur_turk_tili"
UTM = f"utm_source={APP}&utm_medium=referral"

LAYOUTS = ["gradient", "plate", "duotone", "panel", "card", "glass", "vignette"]
# Har bir maket uchun mos matn joylari
LAYOUT_PLACEMENTS = {
    "gradient": ["top", "bottom"],
    "plate": ["top", "bottom", "center", "top-left", "bottom-right", "left", "right"],
    "duotone": ["top", "bottom", "center"],
    "panel": ["top", "bottom", "left", "right"],
    "card": ["top", "bottom"],
    "glass": ["top", "bottom", "center", "top-left", "bottom-right"],
    "vignette": ["center", "top", "bottom"],
}

PLAN_SYSTEM = """You are the PHOTO EDITOR of "Jasur | Turk tili", a Telegram/Instagram channel that teaches
Turkish to Uzbek speakers. For each post you find a real stock photo on Unsplash that shows the post's
CONCRETE subject. Reply with ONE JSON object."""

PLAN_PROMPT = """Post rubric: {rubric} | Level: {level}
Headline (Uzbek): "{title}"
What the post teaches: {summary}
Scene idea: {brief}

1. Can a real photo show this topic well (people, places, objects, situations)? Abstract topics such as
   grammar rules, exam formats or scoring cannot -> "photo_ok": false.
2. Give 3 different English Unsplash search queries, 2-4 words each, most specific first. Name concrete,
   photographable things (e.g. "turkish breakfast table", "istanbul ferry passengers", "pharmacy counter").
   Add a Turkey/Istanbul context only where it is natural. No abstract words like "learning" or "language".
3. Pick a "main" colour that fits the topic and mood (food -> warm, sea/travel -> blue, health -> teal,
   nature -> green, night -> deep indigo ...) and a contrasting "accent". Avoid these recent colours: {recent_bg}.

Return JSON: {{"photo_ok": true/false, "queries": ["...", "...", "..."],
"colors": {{"main": "#hex", "accent": "#hex"}}}}"""

CHECK_SYSTEM = """You check stock photos for an educational Telegram channel. Answer with one JSON object only."""
CHECK_PROMPT = """This photo will illustrate a post about: "{topic}". Scene idea: "{brief}".
Return JSON: {{"on_topic": true/false (a viewer would connect the photo with the topic),
"appropriate": true/false (suitable for students: no alcohol, no revealing clothing, no violence,
no brand logos as the main subject, no religiously offensive content),
"problems": "short description or empty"}}"""


class UnsplashError(RuntimeError):
    pass


@dataclass
class Photo:
    id: str
    raw: str
    download_location: str
    author: str
    author_url: str
    color: str = ""
    description: str = ""
    query: str = ""

    @property
    def credit_html(self) -> str:
        name = escape(self.author[:40] or "Unsplash", quote=False)
        return (f'📷 Foto: <a href="{escape(self.author_url, quote=True)}">{name}</a> / '
                f'<a href="https://unsplash.com/?{UTM}">Unsplash</a>')


def credit_from_meta(meta: dict | None) -> str:
    """Saqlangan meta'dan post matni uchun foto muallifi qatori (HTML)."""
    c = (meta or {}).get("credit") if isinstance(meta, dict) else None
    if not isinstance(c, dict) or not c.get("name"):
        return ""
    return Photo(id="", raw="", download_location="", author=str(c["name"]),
                 author_url=str(c.get("url") or f"https://unsplash.com/?{UTM}")).credit_html


# Post uzunligini hisoblashda foto muallifi qatori uchun joy (eng uzun ism — 40 belgi)
CREDIT_PLACEHOLDER = "📷 Foto: " + "X" * 40 + " / Unsplash"


# ------------------------------------------------------------------ Unsplash API
class UnsplashClient:
    def __init__(self, access_key: str, timeout: float = 30.0):
        self.key = access_key
        self.http = httpx.AsyncClient(timeout=timeout, follow_redirects=True,
                                      headers={"Authorization": f"Client-ID {access_key}",
                                               "Accept-Version": "v1"})
        self.remaining: str | None = None

    async def aclose(self) -> None:
        await self.http.aclose()

    async def _get(self, url: str, params: dict | None = None) -> dict | list:
        r = await self.http.get(url, params=params)
        self.remaining = r.headers.get("X-Ratelimit-Remaining", self.remaining)
        if r.status_code != 200:
            raise UnsplashError(f"Unsplash {r.status_code}: {r.text[:200]}")
        return r.json()

    async def search(self, query: str, per_page: int = 20) -> list[dict]:
        data = await self._get(f"{API}/search/photos", {
            "query": query, "per_page": per_page, "orientation": "portrait", "content_filter": "high"})
        return list(data.get("results") or []) if isinstance(data, dict) else []

    async def track_download(self, download_location: str) -> None:
        """Unsplash qoidasi: foto ishlatilganda download endpoint chaqiriladi."""
        if download_location.startswith(API):
            await self._get(download_location)

    async def fetch(self, photo: Photo) -> bytes:
        sep = "&" if "?" in photo.raw else "?"
        url = f"{photo.raw}{sep}w={W}&h={H}&fit=crop&crop=faces,entropy&fm=jpg&q=88"
        r = await self.http.get(url, headers={"Authorization": ""})
        if r.status_code != 200 or not r.content:
            raise UnsplashError(f"Foto yuklanmadi: {r.status_code}")
        return r.content


def to_photo(item: dict, query: str = "") -> Photo | None:
    try:
        user = item.get("user") or {}
        author_url = (user.get("links") or {}).get("html") or "https://unsplash.com"
        return Photo(id=str(item["id"]), raw=str(item["urls"]["raw"]),
                     download_location=str((item.get("links") or {}).get("download_location") or ""),
                     author=str(user.get("name") or user.get("username") or "Unsplash"),
                     author_url=f"{author_url}?{UTM}", color=str(item.get("color") or ""),
                     description=str(item.get("description") or item.get("alt_description") or "")[:200],
                     query=query)
    except (KeyError, TypeError):
        return None


def usable(item: dict, used: set[str]) -> bool:
    if not isinstance(item, dict) or item.get("id") in used:
        return False
    if item.get("premium") or item.get("plus") or item.get("sponsorship"):
        return False                       # Unsplash+ va reklama fotolari bepul emas
    w, h = int(item.get("width") or 0), int(item.get("height") or 0)
    return w >= 1000 and h >= 1200 and h >= w * 0.9


def candidates(results: list[dict], used: set[str], query: str, rng: random.Random, k: int = 3) -> list[Photo]:
    good = [it for it in results if usable(it, used)][:8]
    rng.shuffle(good)
    out = [to_photo(it, query) for it in good[:k]]
    return [p for p in out if p]


# ------------------------------------------------------------------ rang va maket
def mix(a, b, t: float) -> tuple[int, int, int]:
    return tuple(int(a[i] * (1 - t) + b[i] * t) for i in range(3))


def palette(main_hex: str, accent_hex: str) -> dict:
    main = design.hex_rgb(main_hex, (200, 40, 50))
    accent = design.hex_rgb(accent_hex, (255, 200, 60))
    return {"main": main, "accent": accent, "dark": mix(main, (8, 8, 14), 0.62),
            "deep": mix(main, (0, 0, 0), 0.35), "soft": mix(main, (255, 255, 255), 0.86)}


def hexs(rgb) -> str:
    return "#%02x%02x%02x" % tuple(rgb[:3])


def fit_photo(raw: bytes) -> Image.Image:
    img = Image.open(io.BytesIO(raw)).convert("RGB")
    return ImageOps.fit(img, (W, H), Image.LANCZOS, centering=(0.5, 0.45))


def _gradient_mask(direction: str, start: float, end: float, max_a: int = 235) -> Image.Image:
    """direction: top/bottom/left/right — qaysi chetdan qoraytiriladi. start..end — 0..1 ulush."""
    vertical = direction in ("top", "bottom")
    n = H if vertical else W
    col = Image.new("L", (1, n) if vertical else (n, 1))
    px = col.load()
    for i in range(n):
        p = i / (n - 1)
        if direction in ("bottom", "right"):
            p = 1 - p
        if p <= start:
            a = max_a
        elif p >= end:
            a = 0
        else:
            t = (p - start) / (end - start)
            a = int(max_a * (1 - t) ** 1.6)
        if vertical:
            px[0, i] = a
        else:
            px[i, 0] = a
    return col.resize((W, H))


def overlay(img: Image.Image, color, mask: Image.Image) -> Image.Image:
    layer = Image.new("RGB", (W, H), tuple(color))
    return Image.composite(layer, img, mask)


def rounded_mask(size, radius: int) -> Image.Image:
    m = Image.new("L", size, 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, size[0] - 1, size[1] - 1), radius=radius, fill=255)
    return m


def build_art(photo: Image.Image, layout: str, placement: str, pal: dict,
              rng: random.Random) -> tuple[Image.Image, tuple[int, int, int, int], dict]:
    """Fotoni maket bo'yicha tayyorlaydi. (rasm, matn qutisi, spec sozlamalari) qaytaradi."""
    box = design.default_box(placement)
    opts = {"plate": "none", "ink": (255, 255, 255), "bg": pal["dark"], "soft": pal["soft"],
            "accent": pal["accent"], "kicker": rng.choice(["pill", "plain", "underline", "tag"]),
            "align": "center" if placement == "center" else rng.choice(["left", "left", "center"])}

    if layout == "gradient":
        img = ImageEnhance.Brightness(photo).enhance(0.92)
        img = overlay(img, pal["dark"], _gradient_mask(placement, 0.30, 0.66))
        box = (64, 80, 952, 470) if placement == "top" else (64, H - 90 - 470, 952, 470)

    elif layout == "plate":
        img = ImageEnhance.Brightness(photo).enhance(0.9)
        opts.update(plate=rng.choice(["rounded", "pill", "sharp", "blob"]), bg=pal["main"], soft=pal["main"])
        opts["ink"] = design.best_ink(pal["main"], [(255, 255, 255), (20, 20, 28)])
        if placement in ("left", "right"):
            box = (56, 200, 600, 560) if placement == "left" else (424, 200, 600, 560)

    elif layout == "duotone":
        gray = ImageOps.autocontrast(photo.convert("L"), cutoff=1)
        img = ImageOps.colorize(gray, black=pal["deep"], white=pal["soft"], mid=pal["main"])
        if placement == "center":
            img = overlay(img, pal["dark"], Image.new("L", (W, H), 120))
        else:
            img = overlay(img, pal["dark"], _gradient_mask(placement, 0.28, 0.62, 225))
            box = (64, 80, 952, 460) if placement == "top" else (64, H - 90 - 460, 952, 460)

    elif layout == "panel":
        seam = rng.choice(["straight", "diagonal", "wave"])
        img = photo.copy()
        mask = Image.new("L", (W, H), 0)
        d = ImageDraw.Draw(mask)
        size = 0.44 if placement in ("top", "bottom") else 0.52
        if placement in ("top", "bottom"):
            edge = int(H * size)
            pts_edge = []
            sign = rng.choice([1, -1])
            phase = rng.uniform(0, math.tau)
            for i in range(0, W + 1, 20):
                if seam == "diagonal":
                    off = int(140 * (i / W - 0.5) * sign)
                elif seam == "wave":
                    off = int(26 * math.sin(i / W * math.tau * 1.2 + phase))
                else:
                    off = 0
                pts_edge.append((i, edge + off if placement == "top" else H - edge + off))
            poly = ([(0, 0)] + pts_edge + [(W, 0)]) if placement == "top" else \
                   ([(0, H)] + pts_edge + [(W, H)])
            d.polygon(poly, fill=255)
            box = (64, 70, 952, edge - 120) if placement == "top" else (64, H - edge + 70, 952, edge - 130)
        else:
            edge = int(W * size)
            x = edge if placement == "left" else W - edge
            skew = 80 if seam == "diagonal" else 0
            poly = [(0, 0), (x + skew, 0), (x - skew, H), (0, H)] if placement == "left" else \
                   [(W, 0), (x - skew, 0), (x + skew, H), (W, H)]
            d.polygon(poly, fill=255)
            box = (52, 190, edge - 110, 620) if placement == "left" else (W - edge + 70, 190, edge - 120, 620)
        img = overlay(img, pal["main"], mask.filter(ImageFilter.GaussianBlur(1)))
        opts.update(bg=pal["main"], align="left")
        opts["ink"] = design.best_ink(pal["main"], [(255, 255, 255), (20, 20, 28)])

    elif layout == "card":
        bg = pal["soft"] if rng.random() < 0.5 else pal["main"]
        img = Image.new("RGB", (W, H), bg)
        m = 50
        ph = int(H * 0.56)
        pw = W - 2 * m
        y0 = H - m - ph if placement == "top" else m
        pic = ImageOps.fit(photo, (pw, ph), Image.LANCZOS, centering=(0.5, 0.45))
        sh = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ImageDraw.Draw(sh).rounded_rectangle((m, y0 + 14, m + pw, y0 + ph + 14), radius=44, fill=(0, 0, 0, 90))
        sh = sh.filter(ImageFilter.GaussianBlur(18))
        base = img.convert("RGBA")
        base.alpha_composite(sh)
        img = base.convert("RGB")
        img.paste(pic, (m, y0), rounded_mask((pw, ph), 44))
        free_h = H - ph - 2 * m - 40
        box = (70, 60, 940, free_h - 20) if placement == "top" else (70, m + ph + 50, 940, free_h - 20)
        box = (box[0], box[1], box[2], max(260, box[3]))
        opts.update(bg=bg, align=rng.choice(["left", "center"]))
        opts["ink"] = design.best_ink(bg, [pal["deep"], (20, 20, 28), (255, 255, 255)])
        if design.contrast(pal["accent"], bg) < 2.6:
            opts["accent"] = pal["deep"] if bg == pal["soft"] else (255, 255, 255)

    elif layout == "glass":
        img = photo.copy()
        x, y, w, h = box
        pad = 40
        r = (max(0, x - pad), max(0, y - pad), min(W, x + w + pad), min(H, y + h + pad))
        region = img.crop(r).filter(ImageFilter.GaussianBlur(22))
        tint = Image.new("RGB", region.size, pal["dark"])
        region = Image.blend(region, tint, 0.55)
        img.paste(region, r[:2], rounded_mask(region.size, 42))
        hl = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ImageDraw.Draw(hl).rounded_rectangle(r, radius=42, outline=(255, 255, 255, 90), width=2)
        base = img.convert("RGBA")
        base.alpha_composite(hl)
        img = base.convert("RGB")

    else:  # vignette
        img = ImageEnhance.Brightness(photo).enhance(0.8)
        cx, cy = W / 2, (H / 2 if placement == "center" else (H * 0.3 if placement == "top" else H * 0.7))
        small = Image.new("L", (108, 135), 0)
        sp = small.load()
        for j in range(135):
            for i in range(108):
                dx, dy = (i * 10 - cx) / (W * 0.62), (j * 10 - cy) / (H * 0.55)
                dist = min(1.0, (dx * dx + dy * dy) ** 0.5)
                sp[i, j] = int(70 + 150 * (1 - dist))     # markaz qoraroq: matn shu yerda
        img = overlay(img, pal["dark"], small.resize((W, H), Image.BICUBIC))
        if placement != "center":
            box = (90, 150, 900, 470) if placement == "top" else (90, H - 150 - 470, 900, 470)
        opts["align"] = "center"

    return img, box, opts


def compose(raw: bytes, *, layout: str, placement: str, pal: dict, font_name: str, title: str,
            kicker: str, words: list[str], logo_path: Path, seed: int) -> bytes:
    rng = random.Random(seed)
    photo = fit_photo(raw)
    art, box, o = build_art(photo, layout, placement, pal, rng)
    sp = design.Spec(concept="", palette={"bg": hexs(o["bg"]), "ink": hexs(o["ink"]),
                                          "accent": hexs(o["accent"]), "soft": hexs(o["soft"])},
                     font=font_name, box=box, align=o["align"], tilt=0.0, plate=o["plate"],
                     kicker_style=o["kicker"], logo_corner=rng.choice(["br", "bl", "tr", "tl"]),
                     placement=placement)
    sp.logo_corner = design.pick_logo_corner(sp)
    img = design.draw_text_block(art, sp, title=title, kicker=kicker, words=words, rng=rng)
    img = design.draw_logo(img, sp.logo_corner, logo_path)
    b = io.BytesIO()
    img.save(b, "JPEG", quality=92, optimize=True)
    return b.getvalue()


def choose_layout(recent: list[dict], rng: random.Random) -> tuple[str, str, list[str]]:
    lays = [r.get("photo_layout") for r in recent if r.get("photo_layout")]
    places = [r.get("placement") for r in recent if r.get("placement")]
    fonts_used = [r.get("font") for r in recent if r.get("font")]
    layout = design.least_recent(LAYOUTS, lays[:5], rng)[0]
    placement = design.least_recent(LAYOUT_PLACEMENTS[layout], places[:3], rng)[0]
    fonts = design.least_recent(list(design.FONTS), fonts_used[:10], rng, k=4)
    return layout, placement, fonts


def photo_streak(recent: list[dict]) -> int:
    """Oxirgi postlardan nechtasi ketma-ket foto bilan chiqqan."""
    n = 0
    for r in recent:
        if isinstance(r, dict) and r.get("layout") == "foto":
            n += 1
        else:
            break
    return n


# ------------------------------------------------------------------ agent
async def make(gemini, unsplash: UnsplashClient, *, title: str, rubric: str, level: str, summary: str,
               brief: str, words: list[str], kicker: str, logo_path: Path, recent: list[dict] | None = None,
               check: bool = True, seed: int | None = None) -> tuple[bytes, dict]:
    """Unsplash fotosi bilan post rasmini yaratadi. (jpeg, meta). Mos foto bo'lmasa RuntimeError."""
    recent = [r for r in (recent or []) if isinstance(r, dict)]
    rng = random.Random(seed)
    bgs = [r.get("bg") for r in recent[:6] if r.get("bg")]
    plan, _ = await gemini.generate_json(PLAN_SYSTEM, PLAN_PROMPT.format(
        rubric=rubric, level=level, title=title, summary=summary[:400] or title, brief=brief or title,
        recent_bg=", ".join(bgs) or "(none)"), temperature=0.7)
    if not isinstance(plan, dict):
        raise RuntimeError("foto rejasi JSON emas")
    if plan.get("photo_ok") is False:
        raise RuntimeError("mavzu foto uchun mos emas")
    queries = [str(q).strip() for q in (plan.get("queries") or []) if str(q).strip()][:3]
    if not queries:
        raise RuntimeError("qidiruv so'zlari yo'q")
    colors = plan.get("colors") if isinstance(plan.get("colors"), dict) else {}
    used = {r.get("photo_id") for r in recent if r.get("photo_id")}

    chosen: Photo | None = None
    raw = b""
    checked = 0
    for q in queries:
        try:
            results = await unsplash.search(q)
        except UnsplashError as exc:
            log.warning("Unsplash qidiruvi (%s): %s", q, exc)
            if "403" in str(exc) or "401" in str(exc):
                raise                                   # kalit yoki soatlik limit muammosi
            continue
        for ph in candidates(results, used, q, rng):
            try:
                data = await unsplash.fetch(ph)
            except (UnsplashError, httpx.HTTPError) as exc:
                log.warning("Foto yuklanmadi: %s", exc)
                continue
            if check and checked < 3:
                checked += 1
                try:
                    small = Image.open(io.BytesIO(data)).convert("RGB")
                    v, _ = await gemini.generate_json(
                        CHECK_SYSTEM, CHECK_PROMPT.format(topic=title, brief=brief or q),
                        images=[design.to_jpeg(small)], temperature=0.0)
                    if isinstance(v, dict) and (v.get("on_topic") is False or v.get("appropriate") is False):
                        log.info("Foto mos emas (%s): %s", ph.id, v.get("problems"))
                        used.add(ph.id)
                        continue
                except Exception as exc:  # noqa: BLE001 — tekshiruv ishlamasa ham foto yaroqli
                    log.warning("Foto tekshiruvi ishlamadi: %s", exc)
            chosen, raw = ph, data
            break
        if chosen:
            break
    if not chosen:
        raise RuntimeError("mos foto topilmadi: " + "; ".join(queries))

    try:
        await unsplash.track_download(chosen.download_location)
    except Exception as exc:  # noqa: BLE001 — statistika so'rovi postni to'xtatmasin
        log.warning("Unsplash download trigger: %s", exc)

    layout, placement, fonts = choose_layout(recent, rng)
    font_name = rng.choice(fonts)
    pal = palette(colors.get("main") or chosen.color, colors.get("accent") or "")
    jpg = compose(raw, layout=layout, placement=placement, pal=pal, font_name=font_name, title=title,
                  kicker=kicker, words=words, logo_path=logo_path, seed=rng.randint(0, 2**31))
    meta = {"layout": "foto", "photo_layout": layout, "placement": placement, "font": font_name,
            "photo_id": chosen.id, "concept": f"foto: {chosen.query}", "bg": hexs(pal["main"]),
            "credit": {"name": chosen.author, "url": chosen.author_url}}
    log.info("Foto: %s | %s | %s | %s (%s)", chosen.id, layout, placement, font_name, chosen.author)
    return jpg, meta
