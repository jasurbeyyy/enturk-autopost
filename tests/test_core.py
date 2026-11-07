from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from enturk import caption as cap
from enturk import planner

TZ = ZoneInfo("Asia/Tashkent")


def test_sanitize_keeps_allowed_and_escapes():
    html, text = cap.sanitize('<b>Salom</b> & <span class="tg-spoiler">x</span><br>'
                              '<script>bad()</script><p>ok</p> 5 < 6')
    assert "<b>Salom</b>" in html
    assert "&amp;" in html and "&lt; 6" in html
    assert "<tg-spoiler>x</tg-spoiler>" in html
    assert "<script>" not in html and "<p>" not in html
    assert "Salom & x" in text


def test_sanitize_closes_unclosed():
    html, _ = cap.sanitize("<b>ochiq <i>ichki")
    assert html.endswith("</i></b>")


def test_visible_len_emoji_counts_two():
    assert cap.visible_len("🍳a") == 3


def test_strip_footer_like():
    body = "🍳 <b>[A1] X</b>\nmatn\n👉 @jasurturktili\n#yangi_sozlar #A1"
    assert cap.strip_footer_like(body) == "🍳 <b>[A1] X</b>\nmatn"


def _checks(body_text, **kw):
    base = dict(body_html=body_text, body_text=body_text, footer_text="👉 @jasurturktili", level="A1",
                audio=[{"speaker": "female", "text": "merhaba"}], items=["merhaba"],
                recent_items=set(), strict_dedupe=True, has_levels=True)
    base.update(kw)
    return cap.code_checks(**base)


def test_code_checks_length_and_level():
    long = "🍳 [A1] Sarlavha\n" + "a" * 1100
    issues = _checks(long)
    assert any("Too long" in i for i in issues)
    ok = "🍳 [A1] Sarlavha\n" + "a" * 400
    assert _checks(ok) == []
    assert any("level tag" in i for i in _checks("Sarlavha\n" + "a" * 400))


def test_code_checks_cyrillic_and_dedupe():
    t = "🍳 [A1] Sarlavha\n" + "a" * 400 + " салом"
    assert any("Cyrillic" in i for i in _checks(t))
    t = "🍳 [A1] Sarlavha\n" + "a" * 400
    issues = _checks(t, items=["Tava", "kaşık", "çatal", "yeni"], recent_items={"tava", "kaşık", "çatal"})
    assert any("already taught" in i for i in issues)


def test_publish_at_rules():
    slot = datetime(2026, 9, 28, 13, 0, tzinfo=TZ)
    # oddiy holat: 12:50 da ko'rsatildi → 13:00 da chiqadi
    assert planner.publish_at(slot, slot - timedelta(minutes=10), 10) == slot
    # qayta ishlash 13:02 da tayyor bo'ldi → 13:12 da chiqadi (vaqt o'tib ketsa ham)
    late = slot + timedelta(minutes=2)
    assert planner.publish_at(slot, late, 10) == late + timedelta(minutes=10)


def test_preview_at():
    slot = datetime(2026, 9, 28, 13, 0, tzinfo=TZ)
    early = slot - timedelta(minutes=35)
    assert planner.preview_at(slot, 10, early) == slot - timedelta(minutes=10)
    assert planner.preview_at(slot, 10, slot) == slot


def test_next_slot_and_entry():
    cfg = {"weekly": {"mon": [{"time": "08:00", "type": "yangi_sozlar"}]}}
    now = datetime(2026, 9, 28, 7, 20, tzinfo=TZ)  # dushanba
    slot = planner.next_slot_after(now.astimezone(timezone.utc), "08:00", TZ)
    assert slot == datetime(2026, 9, 28, 8, 0, tzinfo=TZ)
    assert planner.entry_for(cfg, slot)["type"] == "yangi_sozlar"
    assert planner.generation_time("08:00", 40, TZ).strftime("%H:%M") == "07:20"


def test_pick_least_used_rotates():
    assert planner.pick_least_used(["A1", "A2", "B1"], ["A1", "A2"]) == "B1"
    # hammasi bir marta ishlatilgan → eng uzoq vaqt ishlatilmagani
    assert planner.pick_least_used(["A1", "A2", "B1"], ["B1", "A2", "A1"]) == "A1"


def test_every_post_type_has_styles_and_schedule_valid():
    from enturk.settings import load_settings
    s = load_settings()
    for key in s.cfg["post_types"]:
        assert len(planner.styles_for(s.styles, key)) >= 2, key
    for day, items in s.cfg["weekly"].items():
        assert [e["time"] for e in items] == ["10:00", "18:00"], day
        for e in items:
            assert e["type"] == planner.AUTO or e["type"] in s.cfg["post_types"], e
    for t in s.cfg["rotation"]["types"]:
        assert t in s.cfg["post_types"], t
    # faqat turk tili: inglizcha post turlari ham, jadvalda ham yo'q
    assert not any(k.startswith("en_") for k in s.cfg["post_types"])
    assert all(pt.get("lang", "tr") == "tr" for pt in s.cfg["post_types"].values())


def test_rotation_varies_and_never_repeats_last_two():
    from datetime import datetime, timedelta, timezone
    from enturk.settings import load_settings
    cfg = load_settings().cfg
    rot = cfg["rotation"]["types"]
    history: list[str] = []
    t0 = datetime(2026, 11, 9, 5, tzinfo=timezone.utc)
    for i in range(36):
        t = planner.choose_type(cfg, {"type": "auto"}, history, t0 + timedelta(hours=12 * i))
        assert t in rot
        assert t not in history[:2]
        history.insert(0, t)
    counts = {t: history.count(t) for t in rot}
    assert min(counts.values()) >= 5 and max(counts.values()) <= 7, counts   # teng taqsimlanadi
    # aniq tur yozilgan bo'lsa — o'sha
    assert planner.choose_type(cfg, {"type": "imtihon"}, ["imtihon"]) == "imtihon"


def test_footer_has_telegram_and_instagram_links_at_end():
    from enturk import caption as cap
    links = {"telegram": "https://t.me/jasurturktili", "instagram": "https://instagram.com/jasurturktili"}
    f = cap.build_footer(None, "👉 @jasurturktili", ["yangi_sozlar", "A1"], links=links)
    lines = f.split("\n")
    assert lines[-2].startswith("✈️ Telegram") and 'href="https://t.me/jasurturktili"' in lines[-2]
    assert lines[-1].startswith("📸 Instagram") and 'href="https://instagram.com/jasurturktili"' in lines[-1]
    assert "#yangi_sozlar #A1" in f
    html, text = cap.sanitize(f)
    assert 'href="https://instagram.com/jasurturktili"' in html and "@jasurturktili" in text
    # yozuvchi o'zi qo'shgan havolalar takrorlanmaydi
    body = "Matn\n📸 Instagram: <a href=\"https://instagram.com/jasurturktili\">@jasurturktili</a>"
    assert "instagram" not in cap.strip_footer_like(body).lower()
