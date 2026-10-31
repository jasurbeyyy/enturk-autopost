"""3-agent: Rassom — mavzuga mos grafika (kod) yoki Nano Banana illustratsiyasi + rangli pastki tasma va logo."""
from __future__ import annotations

import io
import logging
import random
from pathlib import Path

from PIL import Image, ImageOps

from .. import graphics
from ..gemini import GeminiClient
from . import qa

log = logging.getLogger(__name__)

PROMPT = """Create a warm, modern, high-quality flat vector editorial illustration for an educational social-media post
(language learning channel for Uzbek students learning {lang_name}).

Scene: {brief}
Setting / decorative motif: {motif}.

Art direction:
- Color palette dominated by {red} and clean white, with a few warm neutral accents (cream, soft beige,
  a little charcoal). Friendly, bright, uncluttered, soft shadows, subtle paper texture.
- Characters (if any) are friendly adults, modest everyday clothing, diverse but natural.
- ABSOLUTELY NO text of any kind: no letters, words, numbers, captions, signs with writing, logos or watermarks.
  Any signs, books or screens must be blank or show simple icons only.
- Leave the bottom 14% of the image as a calm, simple background area (a banner will be placed there).
- Vertical composition, main subject centered in the upper and middle part."""

STRICT_SUFFIX = "\n\nIMPORTANT: The previous attempt contained text. Draw NO letters or writing at all."


def compose(raw: bytes, *, logo_path: Path, font_bold: Path | None = None, font_regular: Path | None = None,
            red: str = graphics.RED, label: str, sublabel: str, band: int = 150,
            size: tuple[int, int] = (1080, 1350), theme: str | dict | None = None,
            footer: str | None = None) -> bytes:
    """Rasmga pastki tasma, logo va rubrika nomini qo'yadi. JPEG qaytaradi.

    theme — rang temasi (graphics.THEMES nomi yoki lug'at), footer — tasma uslubi (graphics.FOOTERS)."""
    W, H = size
    img = Image.open(io.BytesIO(raw)).convert("RGB")
    img = ImageOps.fit(img, (W, H), Image.LANCZOS, centering=(0.5, 0.42))
    if isinstance(theme, dict):
        t = theme
    elif theme in graphics.THEMES:
        t = graphics.THEMES[theme]
    else:
        t = graphics.make_theme("custom", red, "#13807F", "tulip") if red != graphics.RED else graphics.THEMES["red"]
    graphics.draw_footer(img, t, footer or "solid", label, sublabel, logo_path, band=band)
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
                     recent_scenes: list[str] | None = None,
                     recent_themes: list[str] | None = None,
                     recent_footers: list[str] | None = None) -> tuple[bytes, dict]:
    """Rasm yaratadi. (jpeg_baytlar, {"layout", "scene", "theme", "footer", ...}) qaytaradi."""
    band = int(cfg["brand"].get("band_height", 150))
    footer = graphics.choose_footer(recent_footers or [], random.Random(f"{topic}|{post_type}|{style_id}"))

    def finish(raw: bytes, theme: str) -> bytes:
        return compose(raw, logo_path=root / "assets" / "logo_white.png", label=label, sublabel=sublabel,
                       band=band, theme=theme, footer=footer)

    def code_graphic() -> tuple[bytes, dict]:
        img, meta = graphics.render_post(
            post_type=post_type, style_id=style_id, lang=lang, title=topic or label, label=label,
            sublabel=sublabel, items=items, visual=visual, lines=lines,
            recent_layouts=recent_layouts, recent_scenes=recent_scenes, recent_themes=recent_themes)
        meta["footer"] = footer
        return finish(_png(img), meta["theme"]), meta

    if cfg["models"].get("image_mode", "grafika") != "gemini":
        return code_graphic()

    motifs = cfg.get("motifs_tr") or []
    motif = random.choice(motifs) if motifs else "Istanbul skyline"
    vis = visual if isinstance(visual, dict) else {}
    theme = graphics.choose_theme(vis.get("colors"), vis.get("emojis") or [], recent_themes or [], random.Random())
    prompt = PROMPT.format(lang_name="Turkish", brief=brief or topic, motif=motif,
                           red=graphics.THEMES[theme]["main"])
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
    return finish(raw, theme), {"layout": "gemini", "scene": motif, "theme": theme, "footer": footer}
