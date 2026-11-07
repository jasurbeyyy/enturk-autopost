import random

import pytest

from enturk import graphics as g
from enturk.agents import writer


@pytest.mark.parametrize("layout", sorted(g.LAYOUTS))
@pytest.mark.parametrize("theme", ["red", "blue", "coffee"])
def test_every_layout_renders(layout, theme):
    ctx = g.Ctx(title="Juda uzun sarlavha: bank xizmatlari va moliya amallari haqida o'n ta so'z",
                label="YANGI SO'ZLAR", sublabel="B1  ·  TÜRKÇE", items=["Havale", "EFT", "Hesap özeti", "x" * 40],
                emojis=g.valid_emojis(["🏦", "💳", "💸"], []), scene="tea", t=g.THEMES[theme],
                lines=[{"speaker": "male", "text": "Merhaba, hesap açtırmak istiyorum."},
                       {"speaker": "female", "text": "Tabii, kimliğinizi alabilir miyim?"}], seed=1)
    img = g.LAYOUTS[layout](ctx)
    assert img.size == (g.W, g.H)


def test_empty_inputs_do_not_crash():
    img, meta = g.render_post(post_type="imtihon", style_id="strategiya", lang="tr", title="",
                              label="IMTIHON MA'LUMOTI", sublabel="B2  ·  TÜRKÇE")
    assert img.size == (g.W, g.H) and meta["layout"] in g.LAYOUTS_BY_TYPE["imtihon"]
    assert meta["emojis"]          # standart emojilar


def test_scenes_and_emoji_validation():
    for name in g.SCENE_FUNCS:
        assert g.scene_layer(name, g.RED).getbbox() is not None
    good = g.valid_emojis(["💈", "", "not-emoji", "💈", "✂️"], [])
    assert good[0] == "💈" and "not-emoji" not in good and good.count("💈") == 1


def test_layout_rotation_avoids_recent():
    rng = random.Random(0)
    recent = ["card", "hero", "stickers", "poster"]
    assert g.choose_layout("yangi_sozlar", "kartochka", recent, False, rng) == "tiles"
    # diolog posti doim chat, lekin ketma-ket ikki marta emas
    assert g.choose_layout("haqiqiy_diolog", "chat", [], True, rng) == "chat"
    assert g.choose_layout("haqiqiy_diolog", "chat", ["chat"], True, rng) in ("poster", "hero")
    # boshqotirmada javoblar ko'rinib qolmasin — chat ishlatilmaydi
    _, meta = g.render_post(post_type="haqiqiy_diolog", style_id="diolog_boshqotirma", lang="tr", title="X",
                            label="L", sublabel="S", lines=[{"speaker": "male", "text": "javob"}])
    assert meta["layout"] != "chat"


def test_scene_choice():
    rng = random.Random(0)
    assert g.choose_scene("tr", "tea", [], rng) == "tea"
    assert "london" not in g.SCENE_FUNCS
    assert g.choose_scene("tr", "nonsense", ["skyline", "bosphorus", "balloons", "tulips"], rng) == "tea"


def test_writer_normalizes_visual():
    d = writer._normalize({"caption_html": "x", "visual": {"emojis": ["🏦", " ", 5], "scene": " Tea ",
                                                              "colors": [" Navy", "", "blue"]}})
    assert d["visual"] == {"emojis": ["🏦", "5"], "scene": "tea", "colors": ["navy", "blue"]}
    assert writer._normalize({"caption_html": "x"})["visual"] == {"emojis": [], "scene": "", "colors": []}
    system = writer._system("tr", "female", 800)
    assert "visual" in system and "coffee" in system and "London" not in system


def test_theme_follows_topic_but_not_three_times_in_a_row():
    rng = random.Random(0)
    assert g.choose_theme(["navy", "blue"], ["🏦"], [], rng) == "navy"
    assert g.choose_theme(["navy", "blue"], [], ["navy"], rng) == "blue"
    assert g.choose_theme([], ["☕"], [], rng) == "coffee"          # emojidan taxmin
    assert g.choose_theme(["nonsense"], ["🌳"], [], rng) == "green"
    assert g.choose_theme(["green"], [], ["green", "teal"], rng) == "coffee"   # yaqin rang
    assert g.choose_theme(None, [], ["red", "blue"], rng) not in ("red", "blue")


def test_render_post_uses_chosen_theme():
    _, meta = g.render_post(post_type="yangi_sozlar", style_id="x", title="Bankda", label="L", sublabel="S",
                            visual={"emojis": ["🏦"], "colors": ["navy"]})
    assert meta["theme"] == "navy"


def test_footers_rotate_and_render():
    rng = random.Random(1)
    seen = []
    for _ in range(len(g.FOOTERS)):
        seen.insert(0, g.choose_footer(seen, rng))
    assert sorted(seen) == sorted(g.FOOTERS)                  # 8 ta postda hammasi bir martadan
    from pathlib import Path
    logo = Path(g.ASSETS) / "logo_white.png"
    for style in g.FOOTERS:
        for theme in ("red", "purple"):
            img = g.LAYOUTS["card"](g.Ctx(title="T", label="L", sublabel="S", items=[], emojis=[], scene="tea",
                                         t=g.THEMES[theme]))
            before = img.crop((0, g.WH, g.W, g.H)).tobytes()
            g.draw_footer(img, g.THEMES[theme], style, "HAFTALIK TAKRORLASH", "A2  ·  TÜRKÇE", logo)
            assert img.crop((0, g.WH, g.W, g.H)).tobytes() != before


def test_themes_keep_white_text_readable():
    def lum(h):
        r, gg, b = [v / 255 for v in g._rgb(h)]
        f = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in (r, gg, b)]
        return 0.2126 * f[0] + 0.7152 * f[1] + 0.0722 * f[2]
    for name, t in g.THEMES.items():
        assert (1.05) / (lum(t["main"]) + 0.05) >= 3.5, name     # oq sarlavha asosiy rang ustida


def test_creative_design_svg_is_sanitized_and_composed(tmp_path):
    import asyncio
    from PIL import Image
    import io
    from enturk import design
    from enturk.mock import MOCK_DESIGN
    svg = MOCK_DESIGN["svg"].replace("</svg>", '<text x="9" y="9">YOZUV</text><script>x()</script></svg>')
    clean, n = design.sanitize_svg(svg)
    assert "<text" not in clean and "<script" not in clean and n >= 12

    class G:
        calls = 0

        async def generate_json(self, system, prompt, **kw):
            G.calls += 1
            assert "ART DIRECTOR" in system and "NO repeating patterns" in system
            return dict(MOCK_DESIGN, text_box={"x": 700, "y": 1100, "w": 900, "h": 900}), []

    jpg, meta = asyncio.run(design.design(
        G(), title="TURKİYADA UY IJARAGA OLISH", rubric="Kunlik iboralar", level="B2", summary="",
        brief="renting a flat", words=["kira", "ev sahibi"], kicker="Kunlik iboralar · B2",
        logo_path=design.ASSETS / "logo_white.png", recent=[], seed=1))
    im = Image.open(io.BytesIO(jpg))
    assert im.size == (1080, 1350) and meta["layout"] == "kreativ" and G.calls == 1
    assert design.smart_case("TURKİYADA UY IJARAGA OLISH") == "Turkiyada uy ijaraga olish"


def test_design_brief_rotates_directions_and_placements():
    import random
    from enturk import design
    recent, seen_dirs, seen_places = [], [], []
    for i in range(8):
        d, p, fonts = design.choose_brief(recent, random.Random(i))
        assert d not in seen_dirs and len(fonts) == 5
        if seen_places:
            assert p != seen_places[-1]
        seen_dirs.append(d)
        seen_places.append(p)
        recent.insert(0, {"direction": d, "placement": p, "font": fonts[0]})


def test_image_words_only_short_items():
    from enturk import design
    assert design.image_words(["eczane — dorixona", "ilaç", "reçete (retsept)"], "yangi_sozlar") == \
        ["eczane", "ilaç", "reçete"]
    assert design.image_words(["eczane", "ilaç"], "imtihon") == []
