"""3-agent: Rassom — Nano Banana orqali illustratsiya yaratadi va unga brend tasmasi + logoni qo'yadi."""
from __future__ import annotations

import io
import logging
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

from ..gemini import GeminiClient
from . import qa

log = logging.getLogger(__name__)

PROMPT = """Create a warm, modern, high-quality flat vector editorial illustration for an educational social-media post
(language learning channel for Uzbek students learning {lang_name}).

Scene: {brief}
Setting / decorative motif: {motif}.

Art direction:
- Color palette dominated by Turkish red ({red}) and clean white, with a few warm neutral accents (cream, soft beige,
  a little charcoal). Friendly, bright, uncluttered, soft shadows, subtle paper texture.
- Characters (if any) are friendly adults, modest everyday clothing, diverse but natural.
- ABSOLUTELY NO text of any kind: no letters, words, numbers, captions, signs with writing, logos or watermarks.
  Any signs, books or screens must be blank or show simple icons only.
- Leave the bottom 14% of the image as a calm, simple background area (a banner will be placed there).
- Vertical composition, main subject centered in the upper and middle part."""

STRICT_SUFFIX = "\n\nIMPORTANT: The previous attempt contained text. Draw NO letters or writing at all."


def _font(path: Path, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(path), size)


def compose(raw: bytes, *, logo_path: Path, font_bold: Path, font_regular: Path, red: str,
            label: str, sublabel: str, band: int = 150, size: tuple[int, int] = (1080, 1350)) -> bytes:
    """Illustratsiyaga pastki qizil tasma, oq logo va rubrika nomini qo'yadi. JPEG qaytaradi."""
    W, H = size
    img = Image.open(io.BytesIO(raw)).convert("RGB")
    img = ImageOps.fit(img, (W, H), Image.LANCZOS, centering=(0.5, 0.42))
    draw = ImageDraw.Draw(img)

    # tasma
    top = H - band
    draw.rectangle((0, top, W, H), fill=red)
    draw.rectangle((0, top, W, top + 4), fill="#FFFFFF")

    # logo (shaffof foni kesiladi)
    logo = Image.open(logo_path).convert("RGBA")
    logo = logo.crop(logo.getbbox())
    lh = band - 40
    lw = int(logo.width * lh / logo.height)
    logo = logo.resize((lw, lh), Image.LANCZOS)
    margin = 36
    img.paste(logo, (margin, top + (band - lh) // 2 + 2), logo)

    # rubrika nomi (o'ng tomonda)
    max_w = W - lw - margin * 3
    size_l = 46
    f_label = _font(font_bold, size_l)
    while draw.textlength(label, font=f_label) > max_w and size_l > 24:
        size_l -= 2
        f_label = _font(font_bold, size_l)
    f_sub = _font(font_regular, 28)
    right = W - margin
    y_label = top + band // 2 - size_l + 4
    draw.text((right, y_label), label, font=f_label, fill="#FFFFFF", anchor="ra")
    draw.text((right, y_label + size_l + 12), sublabel, font=f_sub, fill="#FFE9EA", anchor="ra")

    out = io.BytesIO()
    img.save(out, "JPEG", quality=92, optimize=True)
    return out.getvalue()


def _wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_w: int) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for w in words:
        test = (cur + " " + w).strip()
        if draw.textlength(test, font=font) <= max_w:
            cur = test
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def _skyline(d: ImageDraw.ImageDraw, W: int, base: int, color: str) -> None:
    """Soddalashtirilgan Istanbul silueti: masjid gumbazlari, minoralar, Galata minorasi."""
    def minaret(x: int, h: int, w: int = 16) -> None:
        d.rectangle((x - w // 2, base - h, x + w // 2, base), fill=color)
        d.rectangle((x - w // 2 - 5, base - int(h * 0.62), x + w // 2 + 5, base - int(h * 0.62) + 8), fill=color)
        d.polygon([(x - w // 2, base - h), (x + w // 2, base - h), (x, base - h - 46)], fill=color)

    def mosque(cx: int, r: int) -> None:
        d.rectangle((cx - int(r * 1.5), base - int(r * 1.0), cx + int(r * 1.5), base), fill=color)
        d.pieslice((cx - r, base - int(r * 1.7), cx + r, base - int(r * 0.3)), 180, 360, fill=color)
        for sx in (-1, 1):
            c2 = cx + sx * int(r * 1.05)
            d.pieslice((c2 - r // 2, base - int(r * 1.05), c2 + r // 2, base - int(r * 0.2)), 180, 360, fill=color)
        d.rectangle((cx - 3, base - int(r * 1.7) - 26, cx + 3, base - int(r * 1.0)), fill=color)
        minaret(cx - int(r * 1.75), int(r * 2.5))
        minaret(cx + int(r * 1.75), int(r * 2.5))

    def galata(x: int) -> None:
        d.rectangle((x - 34, base - 190, x + 34, base), fill=color)
        d.rectangle((x - 44, base - 200, x + 44, base - 186), fill=color)
        d.polygon([(x - 40, base - 200), (x + 40, base - 200), (x, base - 290)], fill=color)

    d.rectangle((0, base - 22, W, base), fill=color)
    mosque(int(W * 0.26), 78)
    galata(int(W * 0.62))
    mosque(int(W * 0.84), 58)
    for x, h in ((int(W * 0.05), 60), (int(W * 0.46), 90), (int(W * 0.72), 70), (int(W * 0.97), 55)):
        d.rectangle((x - 30, base - h, x + 30, base), fill=color)


def graphic_art(*, title: str, label: str, sublabel: str, red: str, font_bold: Path,
                font_regular: Path, items: list[str] | None = None,
                size: tuple[int, int] = (1080, 1350), band: int = 150) -> bytes:
    """Gemini'siz grafika: lola naqshi, Istanbul silueti, rubrika, mavzu va asosiy so'zlar."""
    W, H = size
    img = Image.new("RGB", (W, H), "#FFF8F3")
    d = ImageDraw.Draw(img)
    pale = "#F8DEDF"
    for yi, y in enumerate(range(30, H, 120)):
        for x in range(-40 + (60 if yi % 2 else 0), W + 60, 120):
            d.ellipse((x - 12, y - 20, x + 12, y + 8), fill=pale)
            d.polygon([(x - 16, y - 6), (x - 5, y - 27), (x, y - 10)], fill=pale)
            d.polygon([(x + 16, y - 6), (x + 5, y - 27), (x, y - 10)], fill=pale)
            d.line((x, y + 8, x, y + 30), fill=pale, width=4)

    base = H - band                     # siluet tasmaga tegib turadi
    _skyline(d, W, base, red)
    # quyosh / oy doirasi siluet ortida
    m, top, bottom = 80, 120, base - 330
    d.rounded_rectangle((m + 10, top + 14, W - m + 10, bottom + 14), radius=44, fill="#EBCACA")
    d.rounded_rectangle((m, top, W - m, bottom), radius=44, fill="#FFFFFF", outline=red, width=7)

    f_lab = _font(font_bold, 38)
    lab_w = d.textlength(label, font=f_lab) + 70
    d.rounded_rectangle(((W - lab_w) / 2, top - 36, (W + lab_w) / 2, top + 36), radius=36, fill=red)
    d.text((W / 2, top), label, font=f_lab, fill="#FFFFFF", anchor="mm")

    items = [i for i in (items or []) if 0 < len(i) <= 22][:6]
    chips_h = 0
    f_chip = _font(font_bold, 34)
    chip_rows: list[list[str]] = []
    if items:
        row: list[str] = []
        row_w = 0.0
        for it in items:
            w = d.textlength(it, font=f_chip) + 56
            if row and row_w + w > W - 2 * m - 80:
                chip_rows.append(row)
                row, row_w = [], 0.0
            row.append(it)
            row_w += w + 16
        if row:
            chip_rows.append(row)
        chip_rows = chip_rows[:2]
        chips_h = len(chip_rows) * 74 + 30

    avail = (bottom - top) - 150 - chips_h
    size_t = 80
    while True:
        f_t = _font(font_bold, size_t)
        lines = _wrap(d, title, f_t, W - 2 * m - 100)
        if len(lines) * size_t * 1.18 <= avail or size_t <= 40:
            break
        size_t -= 4
    block = len(lines) * size_t * 1.18
    y = top + 80 + (avail - block) / 2
    for ln in lines:
        d.text((W / 2, y), ln, font=f_t, fill="#1F1F1F", anchor="ma")
        y += size_t * 1.18

    cy = bottom - 70 - chips_h + 20
    for row in chip_rows:
        widths = [d.textlength(it, font=f_chip) + 56 for it in row]
        x = (W - (sum(widths) + 16 * (len(row) - 1))) / 2
        for it, w in zip(row, widths):
            d.rounded_rectangle((x, cy, x + w, cy + 58), radius=29, fill="#FDECEC", outline=red, width=3)
            d.text((x + w / 2, cy + 29), it, font=f_chip, fill=red, anchor="mm")
            x += w + 16
        cy += 74
    f_sub = _font(font_regular, 34)
    d.text((W / 2, bottom - 48), sublabel, font=f_sub, fill="#8A1A1F", anchor="mm")

    out = io.BytesIO()
    img.save(out, "PNG")
    return out.getvalue()


def _to_jpeg(raw: bytes, max_side: int = 768) -> bytes:
    im = Image.open(io.BytesIO(raw)).convert("RGB")
    im.thumbnail((max_side, max_side))
    b = io.BytesIO()
    im.save(b, "JPEG", quality=85)
    return b.getvalue()


async def illustrate(gemini: GeminiClient, *, cfg: dict, root: Path, lang: str, brief: str,
                     topic: str, label: str, sublabel: str, check: bool = True,
                     items: list[str] | None = None) -> bytes:
    fonts = dict(font_bold=root / "assets" / "font-bold.ttf", font_regular=root / "assets" / "font-regular.ttf")
    band = int(cfg["brand"].get("band_height", 150))
    if cfg["models"].get("image_mode", "grafika") != "gemini":
        raw = graphic_art(title=topic or label, label=label, sublabel=sublabel, red=cfg["brand"]["red"],
                          items=items, band=band, **fonts)
        return compose(raw, logo_path=root / "assets" / "logo_white.png", red=cfg["brand"]["red"],
                       label=label, sublabel=sublabel, band=band, **fonts)
    motifs = cfg.get("motifs_en" if lang == "en" else "motifs_tr") or cfg.get("motifs_tr", [])
    motif = random.choice(motifs) if motifs else "Istanbul skyline"
    prompt = PROMPT.format(lang_name="English" if lang == "en" else "Turkish", brief=brief or topic,
                           motif=motif, red=cfg["brand"]["red"])
    raw = b""
    for attempt in range(3):
        try:
            raw = await gemini.generate_image(prompt, aspect=cfg["models"].get("image_aspect", "4:5"),
                                              size=cfg["models"].get("image_size", "1K"))
        except Exception as exc:  # noqa: BLE001 — billing yo'q, limit va h.k.
            log.warning("Rasm modeli ishlamadi, brend kartochka chiziladi: %s", str(exc)[:200])
            raw = graphic_art(title=topic or label, label=label, sublabel=sublabel,
                              red=cfg["brand"]["red"], items=items, band=band, **fonts)
            break
        if not check:
            break
        try:
            verdict = await qa.check_image(gemini, _to_jpeg(raw), topic=topic, brief=brief)
        except Exception as exc:  # tekshiruv ishlamasa ham rasm yaroqli bo'lishi mumkin
            log.warning("Rasm tekshiruvi ishlamadi: %s", exc)
            break
        ok = (not verdict.get("has_text")) and verdict.get("on_topic", True) and verdict.get("appropriate", True)
        if ok:
            break
        log.info("Rasm qayta chiziladi (%s): %s", attempt + 1, verdict)
        if verdict.get("has_text") and STRICT_SUFFIX not in prompt:
            prompt += STRICT_SUFFIX
    return compose(raw, logo_path=root / "assets" / "logo_white.png",
                   font_bold=root / "assets" / "font-bold.ttf",
                   font_regular=root / "assets" / "font-regular.ttf",
                   red=cfg["brand"]["red"], label=label, sublabel=sublabel,
                   band=int(cfg["brand"].get("band_height", 150)))
