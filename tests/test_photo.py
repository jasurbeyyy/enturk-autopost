"""Unsplash foto dizayni: maketlar, foto tanlash, muallif qatori va pipeline'ga ulanish."""
import asyncio
import io
import random
from datetime import datetime, timezone

import pytest
from PIL import Image, ImageDraw

from enturk import caption as cap
from enturk import photo
from enturk.db import DB
from enturk.mock import FakeEleven, FakeGemini
from enturk.pipeline import Pipeline
from enturk.settings import ROOT, load_settings

LOGO = ROOT / "assets" / "logo_white.png"


def fake_photo_bytes(seed=0) -> bytes:
    rng = random.Random(seed)
    img = Image.new("RGB", (1200, 1500), (200, 180, 150))
    d = ImageDraw.Draw(img)
    for _ in range(60):
        x, y = rng.randint(0, 1200), rng.randint(0, 1500)
        d.ellipse((x, y, x + rng.randint(40, 300), y + rng.randint(40, 300)),
                  fill=tuple(rng.randint(0, 255) for _ in range(3)))
    b = io.BytesIO()
    img.save(b, "JPEG")
    return b.getvalue()


def item(pid, w=3000, h=4000, **kw):
    return {"id": pid, "width": w, "height": h, "color": "#336699", "description": "x",
            "urls": {"raw": f"https://images.unsplash.com/photo-{pid}?ixid=abc"},
            "links": {"download_location": f"https://api.unsplash.com/photos/{pid}/download?ixid=abc"},
            "user": {"name": "Ayşe <Yılmaz>", "links": {"html": "https://unsplash.com/@ayse"}}, **kw}


class FakeUnsplash:
    def __init__(self, results):
        self.results = results
        self.tracked, self.fetched, self.queries = [], [], []
        self.remaining = "49"

    async def search(self, query, per_page=20):
        self.queries.append(query)
        return self.results

    async def track_download(self, loc):
        self.tracked.append(loc)

    async def fetch(self, ph):
        self.fetched.append(ph.id)
        return fake_photo_bytes()

    async def aclose(self):
        pass


@pytest.mark.parametrize("layout", photo.LAYOUTS)
def test_every_layout_and_placement_renders(layout):
    raw = fake_photo_bytes(1)
    for i, pl in enumerate(photo.LAYOUT_PLACEMENTS[layout]):
        for fname in ("Bebas Neue", "Pacifico", "Archivo Black"):
            jpg = photo.compose(raw, layout=layout, placement=pl, pal=photo.palette("#0F766E", "#FDE68A"),
                                font_name=fname, title="Bozorda: ziravorlar va ularning turkcha nomlari",
                                kicker="Yangi so'zlar · A2", words=["baharat", "tarçın", "kimyon"],
                                logo_path=LOGO, seed=i)
            assert Image.open(io.BytesIO(jpg)).size == (photo.W, photo.H)


def test_usable_filters_paid_used_and_small():
    used = {"old"}
    assert photo.usable(item("ok"), used)
    assert not photo.usable(item("old"), used)
    assert not photo.usable(item("p", premium=True), used)
    assert not photo.usable(item("s", w=600, h=800), used)
    assert not photo.usable(item("l", w=4000, h=2000), used)     # yotiq foto


def test_credit_line_and_footer_order():
    ph = photo.to_photo(item("a"))
    html = ph.credit_html
    assert "Ayşe &lt;Yılmaz&gt;" in html and "utm_source=jasur_turk_tili" in html and "Unsplash</a>" in html
    footer = cap.build_footer(None, "👉 @jasurturktili", ["yangi_sozlar", "A2"],
                              links={"telegram": "https://t.me/jasurturktili",
                                     "instagram": "https://instagram.com/jasurturktili"}, credit=html)
    assert footer.index("Foto:") < footer.index("#yangi_sozlar")
    assert footer.rstrip().endswith('instagram.com/jasurturktili">@jasurturktili</a>')
    assert photo.credit_from_meta({"credit": {"name": "Ali", "url": "https://unsplash.com/@ali?x"}})
    assert photo.credit_from_meta({}) == ""


def test_make_picks_unused_photo_and_tracks_download():
    u = FakeUnsplash([item("used1"), item("new1"), item("paid", premium=True)])
    jpg, meta = asyncio.run(photo.make(
        FakeGemini(), u, title="Oshxonada", rubric="Yangi so'zlar", level="A1", summary="tencere; tava",
        brief="kitchen", words=["tencere", "tava"], kicker="Yangi so'zlar · A1", logo_path=LOGO,
        recent=[{"layout": "foto", "photo_id": "used1", "photo_layout": "gradient"}], seed=3))
    assert meta["photo_id"] == "new1" and meta["layout"] == "foto"
    assert meta["photo_layout"] != "gradient"                # oxirgi maket takrorlanmaydi
    assert u.tracked == ["https://api.unsplash.com/photos/new1/download?ixid=abc"]
    assert meta["credit"]["name"] == "Ayşe <Yılmaz>" and jpg[:2] == b"\xff\xd8"


def test_make_refuses_abstract_topics():
    class NoPhoto(FakeGemini):
        async def generate_json(self, system, prompt, **kw):
            if "PHOTO EDITOR" in system:
                return {"photo_ok": False, "queries": []}, []
            return await super().generate_json(system, prompt, **kw)
    with pytest.raises(RuntimeError):
        asyncio.run(photo.make(NoPhoto(), FakeUnsplash([item("a")]), title="Imtihon", rubric="Imtihon",
                               level="B2", summary="", brief="", words=[], kicker="Imtihon", logo_path=LOGO))


def test_photo_streak():
    assert photo.photo_streak([{"layout": "foto"}, {"layout": "foto"}, {"layout": "kreativ"}]) == 2
    assert photo.photo_streak([{"layout": "kreativ"}, {"layout": "foto"}]) == 0


def test_pipeline_uses_photo_and_adds_credit(tmp_path, monkeypatch):
    s = load_settings()
    s.data_dir = tmp_path
    s.eleven_key = ""
    s.unsplash_key = "test-key"
    fake = FakeUnsplash([item("p1"), item("p2")])
    monkeypatch.setattr(photo, "UnsplashClient", lambda key: fake)
    p = Pipeline(s, DB(tmp_path / "p.db"), FakeGemini(), FakeEleven())
    r = asyncio.run(p.run("yangi_sozlar", now=datetime.now(timezone.utc)))
    assert r.qa["layout"] == "foto" and r.qa["design"]["photo_id"] in ("p1", "p2")
    assert "📷 Foto:" in r.caption_html and "Unsplash</a>" in r.caption_html
    assert r.caption_html.rstrip().endswith('instagram.com/jasurturktili">@jasurturktili</a>')
    _, text = cap.sanitize(r.caption_html)
    assert cap.visible_len(text) <= cap.CAPTION_LIMIT


def test_pipeline_without_key_draws_illustration(tmp_path):
    s = load_settings()
    s.data_dir = tmp_path
    s.eleven_key = ""
    s.unsplash_key = ""
    p = Pipeline(s, DB(tmp_path / "p.db"), FakeGemini(), FakeEleven())
    r = asyncio.run(p.run("yangi_sozlar", now=datetime.now(timezone.utc)))
    assert r.qa["layout"] == "kreativ" and "Foto:" not in r.caption_html
