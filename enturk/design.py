"""Kreativ dizayner: har bir post uchun yangi, qolipsiz rasm.

Ish tartibi:
  1. Kod badiiy yo'nalish, joylashuv va shriftlarni oxirgi postlarda ishlatilmaganlaridan tanlaydi.
  2. "Art director" agenti (Gemini, matn) shu post uchun alohida SVG illyustratsiya chizadi,
     rang palitrasi va matn joyini belgilaydi. SVG ichida yozuv bo'lmaydi.
  3. Kod SVG'ni tozalaydi, rasmga aylantiradi (resvg), sarlavha, rubrika va logoni o'zi qo'yadi:
     matn sig'ishi, o'qilishi (kontrast) va logo joyi kodda kafolatlanadi.
  4. Rasm tekshiruvchi (Gemini, ko'rish) mavzuga mosligini va yozuv yo'qligini tekshiradi.
Takroriy naqsh, bir xil tasma yoki bir xil maket yo'q: har bir post o'z kompozitsiyasida chiqadi.
"""
from __future__ import annotations

import io
import logging
import math
import random
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageStat

log = logging.getLogger(__name__)

W, H = 1080, 1350
ASSETS = Path(__file__).resolve().parent.parent / "assets"
FONT_DIR = ASSETS / "fonts"
SVG_NS = "http://www.w3.org/2000/svg"

# name: (fayl, xarakter, faqat katta harf)
FONTS: dict[str, tuple[str, str, bool]] = {
    "Archivo Black": ("ArchivoBlack.ttf", "heavy grotesk, loud and modern", False),
    "Bebas Neue": ("BebasNeue.ttf", "tall condensed poster capitals", True),
    "DM Serif Display": ("DMSerifDisplay.ttf", "elegant high-contrast serif, editorial", False),
    "Abril Fatface": ("AbrilFatface.ttf", "fat didone serif, magazine cover", False),
    "Righteous": ("Righteous.ttf", "rounded retro-futuristic display", False),
    "Pacifico": ("Pacifico.ttf", "friendly brush script", False),
    "Bungee": ("Bungee.ttf", "chunky signage capitals", True),
    "Lobster": ("Lobster.ttf", "bold retro script", False),
    "Luckiest Guy": ("LuckiestGuy.ttf", "playful cartoon capitals", True),
    "Shrikhand": ("Shrikhand.ttf", "heavy italic groovy 70s display", False),
    "Young Serif": ("YoungSerif.ttf", "warm bookish serif", False),
    "Alfa Slab One": ("AlfaSlabOne.ttf", "heavy slab serif, vintage", False),
    "Rubik": ("Rubik.ttf", "soft rounded grotesk, friendly", False),
    "Unbounded": ("Unbounded.ttf", "wide geometric display, contemporary", False),
    "Playfair Display": ("PlayfairDisplay.ttf", "classic literary serif", False),
    "Caveat": ("Caveat.ttf", "handwritten marker notes", False),
    "Space Grotesk": ("SpaceGrotesk.ttf", "techy quirky grotesk", False),
    "Sora": ("Sora.ttf", "clean geometric sans", False),
    "Outfit": ("Outfit.ttf", "minimal geometric sans", False),
    "Montserrat": ("Montserrat.ttf", "urban geometric sans, extra bold", False),
    "Nunito": ("Nunito.ttf", "rounded soft sans, gentle", False),
    "Bricolage Grotesque": ("BricolageGrotesque.ttf", "expressive editorial grotesk", False),
}
BODY_FONTS = ["Rubik", "Sora", "Outfit", "Montserrat", "Nunito", "Space Grotesk"]

# Badiiy yo'nalishlar — har safar oxirgi postlarda bo'lmagani tanlanadi
DIRECTIONS = [
    "Swiss modernist poster: a few huge flat geometric shapes that together form the subject, strict grid, "
    "lots of breathing space",
    "paper cut-out collage: layered flat paper pieces with soft drop shadows, slightly irregular edges",
    "isometric miniature scene: a small 3D-looking diorama of the place where the topic happens",
    "one giant hero object seen close-up and boldly cropped by the frame edge",
    "warm children's-book illustration: a friendly character doing the action of the topic",
    "neo-brutalist graphic: thick dark outlines, hard offset shadows, bright flat fills",
    "duotone composition: only two strong colours plus white, big simple silhouettes",
    "diagonal split: the canvas cut into two colour fields by a bold diagonal, subject crossing the cut",
    "night scene: deep dark sky, glowing warm lights, objects lit from one side",
    "Bauhaus construction: the subject built from circles, half-circles, rectangles and triangles",
    "retro travel-poster mood: big sun or moon disc, layered landscape planes, limited palette",
    "window or doorway frame: we look through an arch or window into the topic's scene",
    "floating objects: 4-6 different objects of the topic floating at different sizes and angles, "
    "with soft shadows (NOT a repeated pattern)",
    "minimal line art: elegant single-weight outlines on a calm background with one bold colour blob",
    "big speech bubbles and two simple characters facing each other",
    "top-down flat-lay: objects of the topic arranged on a table seen from above",
    "soft 3D clay look: rounded chunky shapes with gentle gradients and highlights",
    "magazine cover: a large subject on a bold background, overlapping a clean empty band for the headline",
    "sunset gradient sky with simple foreground silhouettes of the topic",
    "postcard from Türkiye: a stamp-like framed vignette of a Turkish street or landscape linked to the topic",
    "scale play: a tiny person next to a huge object of the topic",
    "abstract organic: large fluid blobs in harmonious colours with one recognisable object in the middle",
    "spotlight stage: the subject on a round stage under a single cone of light",
    "cozy interior corner: a warm room detail where the topic happens (desk, kitchen, counter, shop)",
]

# Matn bloki joyi — kod har safar boshqasini so'raydi
PLACEMENTS = {
    "top": "headline block across the TOP part (y between 60 and 520), illustration fills the lower part",
    "bottom": "headline block across the BOTTOM part (ending above y=1270), illustration fills the upper part",
    "left": "headline in a tall LEFT column (about 46-55% of the width), illustration on the right side",
    "right": "headline in a tall RIGHT column (about 46-55% of the width), illustration on the left side",
    "center": "headline in the MIDDLE, the illustration arranged around it (above, below or framing it)",
    "top-left": "headline in the TOP-LEFT area, illustration flowing from the right and bottom",
    "bottom-right": "headline in the BOTTOM-RIGHT area, illustration flowing from the top and left",
}

SYSTEM = """You are the ART DIRECTOR and SVG illustrator of "Jasur | Turk tili", a Telegram/Instagram channel
that teaches Turkish to Uzbek speakers. You design ONE unique post image (1080 x 1350 px, portrait).
Every post must look like it came from a different, inventive designer: new concept, new composition,
new colours. Never reuse a template look. Think like an award-winning editorial illustrator.

Hard rules for the SVG:
- Root: <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1080 1350" width="1080" height="1350">.
- Draw a rich, finished illustration: background (solid or gradient) + at least 25 shapes; use paths,
  gradients (linearGradient/radialGradient), opacity, layering, highlights and shadows for depth.
- The illustration must clearly depict the CONCRETE subject of the post (objects, places, people, actions).
- ABSOLUTELY NO text: no <text>, no letters, digits, words, pseudo-text or scribbles that look like writing.
  Signs, books, screens and labels are blank or show simple icons.
- NO repeating patterns, tilings, ornaments, polka dots, stripes wallpaper, kilim/Iznik/geometric pattern
  fills, frames of repeated motifs or textures. Large purposeful shapes only.
- No <image>, <script>, <foreignObject>, external links or CSS @import. Keep under 14000 characters.
- Keep the headline area you choose calm and simple (plain colour or a smooth single shape behind it),
  so text placed there later is perfectly readable. Do not put important details under it.
- People: friendly adults, modest everyday clothing.

Reply with ONE JSON object."""

TEMPLATE = """Design the image for this post.

Rubric: {rubric}  |  Level: {level}
Headline (will be typed on the image later by code, in Uzbek): "{title}"
What the post teaches: {summary}
Scene idea from the writer: {brief}

Art direction for THIS post: {direction}
Headline placement for THIS post: {placement}
Choose the headline font from: {fonts}
Recent posts used these concepts — do something clearly different: {recent_concepts}
Recent background colours — avoid them and their close shades: {recent_bg}

Colour: pick an original palette that fits the topic and mood (not the default Turkish red every time;
red may appear as an accent). Ensure strong contrast between "ink" and the background of the headline area.

Return JSON:
{{"concept": "one sentence: the visual idea",
  "palette": {{"bg": "#hex", "ink": "#hex (headline colour)", "accent": "#hex (kicker/label colour)",
              "soft": "#hex (light colour for plates/highlights)"}},
  "font": "one font name from the list",
  "text_box": {{"x": int, "y": int, "w": int, "h": int}},
  "align": "left|center|right",
  "tilt": number between -6 and 6 (degrees; 0 is fine),
  "plate": "none|rounded|pill|sharp|blob" (shape drawn behind the headline; "none" if the area is calm),
  "kicker_style": "pill|plain|underline|tag",
  "logo_corner": "tl|tr|bl|br (a corner far from the headline and free of details)",
  "svg": "<svg ...>...</svg>"}}

Headline box rules: inside the canvas with 48 px margins; w between 520 and 984; h between 260 and 640;
keep the 230x150 px logo corner free."""


@dataclass
class Spec:
    concept: str = ""
    palette: dict = field(default_factory=dict)
    font: str = "Rubik"
    box: tuple[int, int, int, int] = (60, 80, 960, 420)
    align: str = "left"
    tilt: float = 0.0
    plate: str = "none"
    kicker_style: str = "pill"
    logo_corner: str = "br"
    svg: str = ""
    direction: str = ""
    placement: str = ""


# ------------------------------------------------------------------ yordamchilar
HEX_RE = re.compile(r"^#?([0-9a-fA-F]{6}|[0-9a-fA-F]{3})$")


def hex_rgb(h: str, default=(30, 30, 30)) -> tuple[int, int, int]:
    m = HEX_RE.match(str(h or "").strip())
    if not m:
        return default
    v = m.group(1)
    if len(v) == 3:
        v = "".join(c * 2 for c in v)
    return int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16)


def luminance(rgb) -> float:
    def ch(c):
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = rgb[:3]
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def contrast(a, b) -> float:
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def least_recent(options: list[str], recent: list[str], rng: random.Random, k: int = 1) -> list[str]:
    """Eng uzoq vaqt ishlatilmaganlari (hech ishlatilmagan — birinchi)."""
    def age(o):
        return recent.index(o) if o in recent else 10_000
    shuffled = options[:]
    rng.shuffle(shuffled)
    return sorted(shuffled, key=age, reverse=True)[:k]


def font(name: str, size: int) -> ImageFont.FreeTypeFont:
    file = FONTS.get(name, FONTS["Rubik"])[0]
    return ImageFont.truetype(str(FONT_DIR / file), size)


def norm_text(t: str) -> str:
    """Shrift uchun belgilarni moslash (o'zbekcha ʻ → ’)."""
    return (t or "").replace("ʻ", "’").replace("ʼ", "’").replace("`", "’").replace("‘", "’")


# ------------------------------------------------------------------ SVG
BAD_TAGS = {"text", "tspan", "textPath", "image", "script", "foreignObject", "a", "iframe", "video",
            "audio", "font", "font-face"}


def _local(tag: str) -> str:
    return tag.split("}", 1)[-1]


def extract_svg(raw: str) -> str:
    raw = raw or ""
    m = re.search(r"<svg\b.*</svg>", raw, re.S | re.I)
    return m.group(0) if m else ""


def sanitize_svg(raw: str) -> tuple[str, int]:
    """Xavfsiz va o'lchami to'g'ri SVG qaytaradi. (svg, shakllar soni). Xato bo'lsa ValueError."""
    svg = extract_svg(raw)
    if not svg:
        raise ValueError("SVG topilmadi")
    svg = re.sub(r"<!DOCTYPE[^>]*>", "", svg, flags=re.I)
    svg = re.sub(r"@import[^;]*;", "", svg)
    try:
        root = ET.fromstring(svg)
    except ET.ParseError as exc:
        raise ValueError(f"SVG xato: {exc}") from exc
    if _local(root.tag) != "svg":
        raise ValueError("ildiz svg emas")
    count = 0
    for parent in list(root.iter()):
        for child in list(parent):
            if _local(child.tag) in BAD_TAGS:
                parent.remove(child)
    for el in root.iter():
        for k in list(el.attrib):
            lk = _local(k).lower()
            v = el.attrib[k]
            if lk.startswith("on"):
                del el.attrib[k]
            elif lk == "href" and not v.startswith("#"):
                del el.attrib[k]
        if _local(el.tag) in {"path", "rect", "circle", "ellipse", "polygon", "polyline", "line", "use"}:
            count += 1
    root.set("viewBox", "0 0 1080 1350")
    root.set("width", "1080")
    root.set("height", "1350")
    ET.register_namespace("", SVG_NS)
    out = ET.tostring(root, encoding="unicode")
    if "xmlns=" not in out[:200]:
        out = out.replace("<svg", f'<svg xmlns="{SVG_NS}"', 1)
    return out, count


def render_svg(svg: str) -> Image.Image:
    import resvg_py
    data = resvg_py.svg_to_bytes(svg_string=svg, width=W, height=H, skip_system_fonts=True)
    img = Image.open(io.BytesIO(bytes(data))).convert("RGBA")
    if img.size != (W, H):
        img = img.resize((W, H), Image.LANCZOS)
    base = Image.new("RGBA", (W, H), (255, 255, 255, 255))
    base.alpha_composite(img)
    return base.convert("RGB")


def art_problems(img: Image.Image, shapes: int) -> list[str]:
    st = ImageStat.Stat(img.convert("L").resize((108, 135)))
    probs = []
    if st.stddev[0] < 14:
        probs.append("the illustration is almost empty / one flat colour")
    if shapes < 12:
        probs.append(f"too simple: only {shapes} shapes, draw a richer illustration (25+ shapes)")
    return probs


# ------------------------------------------------------------------ spec
def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def parse_spec(data: dict, *, fonts: list[str], direction: str, placement: str,
               rng: random.Random) -> Spec:
    sp = Spec(direction=direction, placement=placement)
    sp.concept = str(data.get("concept") or "")[:200]
    pal = data.get("palette") if isinstance(data.get("palette"), dict) else {}
    sp.palette = {k: "#%02x%02x%02x" % hex_rgb(pal.get(k), d) for k, d in
                  (("bg", (250, 246, 238)), ("ink", (25, 25, 35)), ("accent", (227, 10, 23)),
                   ("soft", (255, 255, 255)))}
    f = str(data.get("font") or "")
    sp.font = f if f in FONTS else rng.choice(fonts)
    tb = data.get("text_box") if isinstance(data.get("text_box"), dict) else {}
    try:
        x, y, w, h = (int(float(tb.get(k))) for k in ("x", "y", "w", "h"))
    except (TypeError, ValueError):
        x, y, w, h = default_box(placement)
    w = _clamp(w, 520, 984)
    h = _clamp(h, 260, 640)
    x = _clamp(x, 48, W - 48 - w)
    y = _clamp(y, 48, H - 48 - h)
    sp.box = (x, y, w, h)
    a = str(data.get("align") or "left").lower()
    sp.align = a if a in ("left", "center", "right") else "left"
    try:
        sp.tilt = _clamp(float(data.get("tilt") or 0), -6, 6)
    except (TypeError, ValueError):
        sp.tilt = 0.0
    p = str(data.get("plate") or "none").lower()
    sp.plate = p if p in ("none", "rounded", "pill", "sharp", "blob") else "none"
    k = str(data.get("kicker_style") or "pill").lower()
    sp.kicker_style = k if k in ("pill", "plain", "underline", "tag") else "pill"
    c = str(data.get("logo_corner") or "br").lower()
    sp.logo_corner = c if c in ("tl", "tr", "bl", "br") else "br"
    sp.svg = str(data.get("svg") or "")
    return sp


def default_box(placement: str) -> tuple[int, int, int, int]:
    return {
        "top": (60, 70, 960, 420), "bottom": (60, 820, 960, 380), "left": (56, 160, 560, 620),
        "right": (464, 160, 560, 620), "center": (90, 470, 900, 420), "top-left": (56, 70, 700, 460),
        "bottom-right": (324, 760, 700, 460),
    }.get(placement, (60, 70, 960, 420))


LOGO_BOX = {"tl": (36, 32), "tr": (W - 36 - 240, 32), "bl": (36, H - 32 - 136), "br": (W - 36 - 240, H - 32 - 136)}


def _overlap(a, b) -> bool:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return not (ax + aw <= bx or bx + bw <= ax or ay + ah <= by or by + bh <= ay)


def pick_logo_corner(sp: Spec) -> str:
    order = [sp.logo_corner] + [c for c in ("br", "bl", "tr", "tl") if c != sp.logo_corner]
    for c in order:
        lx, ly = LOGO_BOX[c]
        if not _overlap((lx, ly, 240, 136), sp.box):
            return c
    return sp.logo_corner


# ------------------------------------------------------------------ matn
def wrap(text: str, f: ImageFont.FreeTypeFont, max_w: int) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for wd in words:
        t = f"{cur} {wd}".strip()
        if f.getlength(t) <= max_w or not cur:
            cur = t
        else:
            lines.append(cur)
            cur = wd
    if cur:
        lines.append(cur)
    return lines


def fit_title(text: str, fname: str, max_w: int, max_h: int) -> tuple[ImageFont.FreeTypeFont, list[str], int]:
    script = fname in ("Pacifico", "Lobster", "Caveat")
    lh_k = 1.24 if script else 1.1
    for size in range(150, 38, -4):
        f = font(fname, size)
        lines = wrap(text, f, max_w)
        if len(lines) > 4:
            continue
        if any(f.getlength(ln) > max_w for ln in lines):
            continue
        lh = int(size * lh_k)
        if lh * len(lines) <= max_h:
            return f, lines, lh
    f = font(fname, 40)
    return f, wrap(text, f, max_w)[:5], int(40 * lh_k)


def region_color(img: Image.Image, box) -> tuple[tuple[int, int, int], float]:
    x, y, w, h = box
    crop = img.crop((x, y, x + w, y + h)).convert("RGB").resize((max(1, w // 8), max(1, h // 8)))
    st = ImageStat.Stat(crop)
    mean = tuple(int(v) for v in st.mean[:3])
    busy = sum(st.stddev[:3]) / 3
    return mean, busy


def best_ink(bg_rgb, cands: list[tuple[int, int, int]]) -> tuple[int, int, int]:
    return max(cands, key=lambda c: contrast(c, bg_rgb))


def _plate(layer: Image.Image, box, style: str, fill, rng: random.Random) -> None:
    d = ImageDraw.Draw(layer)
    x, y, w, h = box
    pad = 34
    r = (x - pad, y - pad, x + w + pad, y + h + pad)
    if style == "pill":
        d.rounded_rectangle(r, radius=min(120, (h + 2 * pad) // 2), fill=fill)
    elif style == "sharp":
        d.rectangle(r, fill=fill)
    elif style == "blob":
        cx, cy = x + w / 2, y + h / 2
        rx, ry = w / 2 + pad * 1.6, h / 2 + pad * 1.6
        pts = []
        ph = [rng.uniform(0, math.tau) for _ in range(3)]
        for i in range(72):
            a = math.tau * i / 72
            k = 1 + 0.05 * math.sin(3 * a + ph[0]) + 0.04 * math.sin(5 * a + ph[1]) + 0.03 * math.sin(2 * a + ph[2])
            pts.append((cx + rx * k * math.cos(a), cy + ry * k * math.sin(a)))
        d.polygon(pts, fill=fill)
    else:
        d.rounded_rectangle(r, radius=40, fill=fill)


def draw_text_block(img: Image.Image, sp: Spec, *, title: str, kicker: str, words: list[str],
                    rng: random.Random) -> Image.Image:
    x, y, w, h = sp.box
    pal = {k: hex_rgb(v) for k, v in sp.palette.items()}
    mean, busy = region_color(img, sp.box)
    plate = sp.plate
    if plate == "none" and (busy > 34 or contrast(pal["ink"], mean) < 3.2 and
                            contrast(best_ink(mean, [pal["ink"], pal["soft"], (255, 255, 255), (20, 20, 28)]),
                                     mean) < 4.5):
        plate = rng.choice(["rounded", "pill", "blob", "sharp"])

    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    if plate != "none":
        under = pal["soft"] if contrast(pal["soft"], pal["ink"]) >= contrast(pal["bg"], pal["ink"]) else pal["bg"]
        if contrast(under, pal["ink"]) < 4.5:
            under = (255, 255, 255) if luminance(pal["ink"]) < 0.4 else (22, 22, 30)
        _plate(layer, sp.box, plate, under + (238,), rng)
        surface = under
    else:
        surface = mean
    ink = pal["ink"] if contrast(pal["ink"], surface) >= 4.0 else best_ink(
        surface, [pal["ink"], pal["soft"], pal["bg"], (255, 255, 255), (20, 20, 28)])
    accent = pal["accent"] if contrast(pal["accent"], surface) >= 2.6 else ink

    d = ImageDraw.Draw(layer)
    upper = FONTS.get(sp.font, ("", "", False))[2]
    ttl = norm_text(title)
    ttl = ttl.upper() if upper else ttl   # sarlavha o'zbekcha: oddiy katta harf (i → I)

    # kicker (rubrika · daraja)
    kfont = font(rng.choice(["Montserrat", "Sora", "Outfit", "Space Grotesk", "Rubik"]), 30)
    ktext = norm_text(kicker).upper()
    kw = int(kfont.getlength(ktext))
    k_h = 58
    wtext = "  •  ".join(norm_text(wd) for wd in words[:4] if wd)
    wfont = font(rng.choice(BODY_FONTS), 34)
    while wtext and wfont.getlength(wtext) > w and "  •  " in wtext:
        wtext = wtext.rsplit("  •  ", 1)[0]
    if wtext and wfont.getlength(wtext) > w:
        wtext = ""
    w_h = 60 if wtext else 0

    tf, lines, lh = fit_title(ttl, sp.font, w, h - k_h - 24 - w_h - (18 if w_h else 0))
    block_h = k_h + 22 + lh * len(lines) + (w_h + 18 if w_h else 0)
    cy = y + max(0, (h - block_h) // 2)

    def ax(line_w: float) -> float:
        if sp.align == "center":
            return x + (w - line_w) / 2
        if sp.align == "right":
            return x + w - line_w
        return x

    # kicker
    kx = ax(kw + (44 if sp.kicker_style in ("pill", "tag") else 0))
    if sp.kicker_style == "pill":
        d.rounded_rectangle((kx, cy, kx + kw + 44, cy + 50), radius=25, fill=accent)
        d.text((kx + 22, cy + 25), ktext, font=kfont, fill=best_ink(accent, [(255, 255, 255), (20, 20, 28)]),
               anchor="lm")
    elif sp.kicker_style == "tag":
        d.rectangle((kx, cy, kx + kw + 44, cy + 50), fill=ink)
        d.text((kx + 22, cy + 25), ktext, font=kfont, fill=best_ink(ink, [(255, 255, 255), (20, 20, 28)]),
               anchor="lm")
    else:
        d.text((kx, cy + 25), ktext, font=kfont, fill=accent, anchor="lm")
        if sp.kicker_style == "underline":
            d.rectangle((kx, cy + 46, kx + min(kw, 120), cy + 52), fill=accent)
    ty = cy + k_h + 22
    for ln in lines:
        lw = tf.getlength(ln)
        d.text((ax(lw), ty), ln, font=tf, fill=ink)
        ty += lh
    if wtext:
        ty += 18
        d.text((ax(wfont.getlength(wtext)), ty + 6), wtext, font=wfont, fill=accent)

    if abs(sp.tilt) >= 0.5:
        cxp, cyp = x + w / 2, y + h / 2
        layer = layer.rotate(sp.tilt, resample=Image.BICUBIC, center=(cxp, cyp))
    out = img.convert("RGBA")
    if plate != "none":
        sh = layer.split()[3].filter(ImageFilter.GaussianBlur(14)).point(lambda a: int(a * 0.22))
        shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        shadow.putalpha(sh)
        out.alpha_composite(shadow, (0, 10))
    out.alpha_composite(layer)
    return out.convert("RGB")


def draw_logo(img: Image.Image, corner: str, logo_path: Path) -> Image.Image:
    lx, ly = LOGO_BOX[corner]
    mean, _ = region_color(img, (lx, ly, 240, 136))
    color = best_ink(mean, [(255, 255, 255), (22, 22, 28)])
    mask = Image.open(logo_path).convert("RGBA").split()[3]
    hgt = 128
    wid = int(mask.width * hgt / mask.height)
    mask = mask.resize((wid, hgt), Image.LANCZOS)
    tile = Image.new("RGBA", (wid, hgt), color + (255,))
    tile.putalpha(mask)
    out = img.convert("RGBA")
    # yengil soya — har qanday fonda o'qiladi
    sh_col = (0, 0, 0) if color == (255, 255, 255) else (255, 255, 255)
    sh = Image.new("RGBA", (wid, hgt), sh_col + (0,))
    sh.putalpha(mask.filter(ImageFilter.GaussianBlur(6)).point(lambda a: int(a * 0.45)))
    x = lx + (240 - wid) // 2
    out.alpha_composite(sh, (x + 2, ly + 4))
    out.alpha_composite(tile, (x, ly))
    return out.convert("RGB")


def compose(art: Image.Image, sp: Spec, *, title: str, kicker: str, words: list[str],
            logo_path: Path, seed: int) -> bytes:
    rng = random.Random(seed)
    sp.logo_corner = pick_logo_corner(sp)
    img = draw_text_block(art, sp, title=title, kicker=kicker, words=words, rng=rng)
    img = draw_logo(img, sp.logo_corner, logo_path)
    b = io.BytesIO()
    img.save(b, "JPEG", quality=93, optimize=True)
    return b.getvalue()


def to_jpeg(img: Image.Image, side: int = 768) -> bytes:
    im = img.copy()
    im.thumbnail((side, side))
    b = io.BytesIO()
    im.convert("RGB").save(b, "JPEG", quality=85)
    return b.getvalue()


def image_words(items: list[str] | None, post_type: str) -> list[str]:
    """Rasmga yoziladigan 2-4 ta turkcha so'z (faqat qisqa so'zli rubrikalarda)."""
    if post_type not in ("yangi_sozlar", "mavzuli_lugat", "kunlik_iboralar"):
        return []
    limit = 22 if post_type == "kunlik_iboralar" else 18
    out = []
    for it in items or []:
        w = re.split(r"\s[—–-]\s|[(:=/]", str(it))[0].strip(" .,!?;\"'«»")
        if 1 < len(w) <= limit and w not in out:
            out.append(w)
    return out[:4] if len(out) >= 2 else []


# ------------------------------------------------------------------ agent
def choose_brief(recent: list[dict], rng: random.Random) -> tuple[str, str, list[str]]:
    dirs = [r.get("direction") for r in recent if r.get("direction")]
    places = [r.get("placement") for r in recent if r.get("placement")]
    fonts_used = [r.get("font") for r in recent if r.get("font")]
    direction = least_recent(DIRECTIONS, dirs, rng)[0]
    placement = least_recent(list(PLACEMENTS), places[:4], rng)[0]
    fonts = least_recent(list(FONTS), fonts_used[:10], rng, k=5)
    return direction, placement, fonts


async def design(gemini, *, title: str, rubric: str, level: str, summary: str, brief: str,
                 words: list[str], kicker: str, logo_path: Path, recent: list[dict] | None = None,
                 check=None, seed: int | None = None, attempts: int = 2) -> tuple[bytes, dict]:
    """Yangi dizayn chizadi. (jpeg, meta) qaytaradi. Ishlamasa RuntimeError."""
    recent = [r for r in (recent or []) if isinstance(r, dict)]
    rng = random.Random(seed)
    direction, placement, fonts = choose_brief(recent, rng)
    concepts = [r.get("concept") for r in recent[:8] if r.get("concept")]
    bgs = [r.get("bg") for r in recent[:8] if r.get("bg")]
    feedback = ""
    last = "noma'lum"
    for attempt in range(attempts):
        prompt = TEMPLATE.format(
            rubric=rubric, level=level, title=title, summary=summary[:400] or title, brief=brief or title,
            direction=direction, placement=PLACEMENTS[placement],
            fonts=", ".join(f"{f} ({FONTS[f][1]})" for f in fonts),
            recent_concepts="; ".join(concepts) or "(none)", recent_bg=", ".join(bgs) or "(none)")
        if feedback:
            prompt += f"\n\nThe previous attempt was rejected: {feedback}. Fix this in a new design."
        try:
            data, _ = await gemini.generate_json(SYSTEM, prompt, temperature=1.0)
            if not isinstance(data, dict):
                raise ValueError("JSON obyekt emas")
            sp = parse_spec(data, fonts=fonts, direction=direction, placement=placement, rng=rng)
            svg, shapes = sanitize_svg(sp.svg)
            art = render_svg(svg)
        except Exception as exc:  # noqa: BLE001
            last = str(exc)[:200]
            feedback = f"the SVG could not be used ({last}); return valid, complete SVG markup"
            log.warning("Dizayn %s: %s", attempt + 1, last)
            continue
        probs = art_problems(art, shapes)
        if not probs and check is not None:
            try:
                v = await check(to_jpeg(art), topic=title, brief=brief or sp.concept)
                if v.get("has_text"):
                    probs.append("it contains letters or text-like marks; draw NO writing at all")
                if v.get("on_topic") is False:
                    probs.append(f"it does not show the topic clearly ({v.get('problems', '')})")
                if v.get("appropriate") is False:
                    probs.append(f"not appropriate ({v.get('problems', '')})")
            except Exception as exc:  # noqa: BLE001 — tekshiruv ishlamasa ham rasm yaroqli
                log.warning("Rasm tekshiruvi ishlamadi: %s", exc)
        if probs and attempt < attempts - 1:
            feedback = "; ".join(probs)
            last = feedback
            log.info("Dizayn qayta chiziladi: %s", feedback)
            continue
        jpg = compose(art, sp, title=title, kicker=kicker, words=words, logo_path=logo_path,
                      seed=rng.randint(0, 2**31))
        meta = {"layout": "kreativ", "direction": direction, "placement": placement, "font": sp.font,
                "concept": sp.concept, "bg": sp.palette.get("bg"), "logo": sp.logo_corner,
                "problems": probs}
        log.info("Dizayn: %s | %s | %s | %s", direction[:40], placement, sp.font, sp.concept[:80])
        return jpg, meta
    raise RuntimeError(f"Dizayn chizilmadi: {last}")
