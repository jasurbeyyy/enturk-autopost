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
    body = "🍳 <b>[A1] X</b>\nmatn\n👉 @EnTurk_CSR\n#yangi_sozlar #A1"
    assert cap.strip_footer_like(body) == "🍳 <b>[A1] X</b>\nmatn"


def _checks(body_text, **kw):
    base = dict(body_html=body_text, body_text=body_text, footer_text="👉 @EnTurk_CSR", level="A1",
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
        assert len(items) == 3, day
        for e in items:
            assert e["type"] in s.cfg["post_types"], e
    en_days = [d for d, items in s.cfg["weekly"].items() if any(e["type"].startswith("en_") for e in items)]
    assert len(en_days) == 3
