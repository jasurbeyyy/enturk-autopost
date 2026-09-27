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


def fallback_art(*, title: str, label: str, sublabel: str, red: str, font_bold: Path,
                 font_regular: Path, size: tuple[int, int] = (1080, 1350)) -> bytes:
    """Rasm modeli ishlamasa: qizil-oq brend kartochka (naqsh + mavzu nomi)."""
    W, H = size
    img = Image.new("RGB", (W, H), "#FFF8F3")
    d = ImageDraw.Draw(img)
    # yengil lola/yulduz naqshi
    pale = "#F7D9DB"
    for yi, y in enumerate(range(-40, H, 120)):
        for x in range(-40 + (60 if yi % 2 else 0), W, 120):
            d.ellipse((x - 14, y - 22, x + 14, y + 10), fill=pale)          # lola guli
            d.polygon([(x - 18, y - 8), (x - 6, y - 30), (x, y - 12)], fill=pale)
            d.polygon([(x + 18, y - 8), (x + 6, y - 30), (x, y - 12)], fill=pale)
            d.line((x, y + 10, x, y + 34), fill=pale, width=4)
    # markaziy karta
    m, top, bottom = 90, 250, H - 330
    d.rounded_rectangle((m + 10, top + 14, W - m + 10, bottom + 14), radius=48, fill="#E9C9C9")
    d.rounded_rectangle((m, top, W - m, bottom), radius=48, fill="#FFFFFF", outline=red, width=8)
    # rubrika yorlig'i
    f_lab = _font(font_bold, 40)
    lab_w = d.textlength(label, font=f_lab) + 70
    d.rounded_rectangle(((W - lab_w) / 2, top - 38, (W + lab_w) / 2, top + 38), radius=38, fill=red)
    d.text((W / 2, top), label, font=f_lab, fill="#FFFFFF", anchor="mm")
    # sarlavha
    size_t = 84
    while size_t > 44:
        f_t = _font(font_bold, size_t)
        lines = _wrap(d, title, f_t, W - 2 * m - 110)
        if len(lines) * size_t * 1.2 <= (bottom - top) - 220:
            break
        size_t -= 6
    block_h = len(lines) * size_t * 1.2
    y = top + ((bottom - top) - block_h) / 2 - 20
    for ln in lines:
        d.text((W / 2, y), ln, font=f_t, fill="#1F1F1F", anchor="ma")
        y += size_t * 1.2
    # daraja
    f_sub = _font(font_regular, 36)
    d.text((W / 2, bottom - 70), sublabel, font=f_sub, fill=red, anchor="mm")
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
                     topic: str, label: str, sublabel: str, check: bool = True) -> bytes:
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
            raw = fallback_art(title=topic or label, label=label, sublabel=sublabel,
                               red=cfg["brand"]["red"], font_bold=root / "assets" / "font-bold.ttf",
                               font_regular=root / "assets" / "font-regular.ttf")
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
