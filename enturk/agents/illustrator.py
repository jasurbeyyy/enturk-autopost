"""3-agent: Rassom — mavzuga mos grafika (kod) yoki Nano Banana illustratsiyasi + brend tasmasi va logo."""
from __future__ import annotations

import io
import logging
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

from .. import graphics
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


def _to_jpeg(raw: bytes, max_side: int = 768) -> bytes:
    im = Image.open(io.BytesIO(raw)).convert("RGB")
    im.thumbnail((max_side, max_side))
    b = io.BytesIO()
    im.save(b, "JPEG", quality=85)
    return b.getvalue()


def _png(img: Image.Image) -> bytes:
    b = io.BytesIO()
    img.save(b, "PNG")
    return b.getvalue()


async def illustrate(gemini: GeminiClient, *, cfg: dict, root: Path, lang: str, brief: str,
                     topic: str, label: str, sublabel: str, check: bool = True,
                     items: list[str] | None = None, post_type: str = "", style_id: str = "",
                     visual: dict | None = None, lines: list[dict] | None = None,
                     recent_layouts: list[str] | None = None,
                     recent_scenes: list[str] | None = None) -> tuple[bytes, dict]:
    """Rasm yaratadi. (jpeg_baytlar, {"layout", "scene", ...}) qaytaradi."""
    fonts = dict(font_bold=root / "assets" / "font-bold.ttf", font_regular=root / "assets" / "font-regular.ttf")
    band = int(cfg["brand"].get("band_height", 150))

    def finish(raw: bytes) -> bytes:
        return compose(raw, logo_path=root / "assets" / "logo_white.png", red=cfg["brand"]["red"],
                       label=label, sublabel=sublabel, band=band, **fonts)

    def code_graphic() -> tuple[bytes, dict]:
        img, meta = graphics.render_post(
            post_type=post_type, style_id=style_id, lang=lang, title=topic or label, label=label,
            sublabel=sublabel, items=items, visual=visual, lines=lines,
            recent_layouts=recent_layouts, recent_scenes=recent_scenes)
        return finish(_png(img)), meta

    if cfg["models"].get("image_mode", "grafika") != "gemini":
        return code_graphic()

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
            log.warning("Rasm modeli ishlamadi, kod grafikasi chiziladi: %s", str(exc)[:200])
            return code_graphic()
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
    return finish(raw), {"layout": "gemini", "scene": motif}
