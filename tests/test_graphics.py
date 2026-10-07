import random

import pytest

from enturk import graphics as g
from enturk.agents import writer


@pytest.mark.parametrize("layout", sorted(g.LAYOUTS))
@pytest.mark.parametrize("lang", ["tr", "en"])
def test_every_layout_renders(layout, lang):
    ctx = g.Ctx(title="Juda uzun sarlavha: bank xizmatlari va moliya amallari haqida o'n ta so'z",
                label="YANGI SO'ZLAR", sublabel="B1  ·  TÜRKÇE", items=["Havale", "EFT", "Hesap özeti", "x" * 40],
                emojis=g.valid_emojis(["🏦", "💳", "💸"], []), scene="london" if lang == "en" else "tea", lang=lang,
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
    assert g.choose_layout("haqiqiy_diolog", "chat", ["chat"], True, rng) == "poster"
    # boshqotirmada javoblar ko'rinib qolmasin — chat ishlatilmaydi
    _, meta = g.render_post(post_type="haqiqiy_diolog", style_id="diolog_boshqotirma", lang="tr", title="X",
                            label="L", sublabel="S", lines=[{"speaker": "male", "text": "javob"}])
    assert meta["layout"] != "chat"


def test_scene_choice():
    rng = random.Random(0)
    assert g.choose_scene("tr", "tea", [], rng) == "tea"
    assert g.choose_scene("en", "tea", [], rng) == "london"
    assert g.choose_scene("tr", "nonsense", ["skyline", "bosphorus", "balloons", "tulips"], rng) == "tea"


def test_writer_normalizes_visual():
    d = writer._normalize({"caption_html": "x", "visual": {"emojis": ["🏦", " ", 5], "scene": " Tea "}})
    assert d["visual"] == {"emojis": ["🏦", "5"], "scene": "tea"}
    assert writer._normalize({"caption_html": "x"})["visual"] == {"emojis": [], "scene": ""}
    assert "visual" in writer._system("tr", "female", 800)
