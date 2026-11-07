"""Haftalik jadval, daraja/uslub/imtihon aylanishi va vaqt hisob-kitoblari."""
from __future__ import annotations

import random
from collections import Counter
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
DAY_NAMES_UZ = ["Dushanba", "Seshanba", "Chorshanba", "Payshanba", "Juma", "Shanba", "Yakshanba"]


def parse_hhmm(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m))


def slot_times(cfg: dict) -> list[str]:
    """Jadvaldagi barcha noyob vaqtlar (masalan 08:00, 13:00, 20:00)."""
    return sorted({e["time"] for day in cfg["weekly"].values() for e in day})


AUTO = "auto"
DEFAULT_ROTATION = ["yangi_sozlar", "haqiqiy_diolog", "kunlik_iboralar", "hayotiy_maslahat",
                    "mavzuli_lugat", "imtihon"]


def rotation_types(cfg: dict) -> list[str]:
    rot = (cfg.get("rotation") or {}).get("types") or DEFAULT_ROTATION
    return [t for t in rot if t in cfg.get("post_types", {})] or list(cfg.get("post_types", {}))[:1]


def choose_type(cfg: dict, entry: dict, recent_types: list[str], slot: datetime | None = None) -> str:
    """Jadvaldagi `type: auto` uchun post turini tanlaydi.

    recent_types — kanalga chiqqan postlar turlari, eng yangisi birinchi.
    Oxirgi `no_repeat` ta postning turi qaytarilmaydi, qolganlaridan eng kam ishlatilgani olinadi."""
    t = entry.get("type", AUTO)
    if t != AUTO:
        return t
    options = rotation_types(cfg)
    no_repeat = int((cfg.get("rotation") or {}).get("no_repeat", 2))
    recent = [r for r in recent_types if r in options]
    banned = set(recent[:min(no_repeat, len(options) - 1)])
    pool = [o for o in options if o not in banned] or options
    rng = random.Random(slot.isoformat() if slot else None)
    return pick_least_used(pool, recent[:len(options) * 3], rng)


def type_title(cfg: dict, t: str) -> str:
    if t == AUTO:
        return "Aylanma mavzu"
    return (cfg.get("post_types", {}).get(t) or {}).get("title", t)


def entry_for(cfg: dict, slot_local: datetime) -> dict | None:
    day = DAYS[slot_local.weekday()]
    hhmm = slot_local.strftime("%H:%M")
    for e in cfg["weekly"].get(day, []):
        if e["time"] == hhmm:
            return e
    return None


def next_slot_after(now: datetime, hhmm: str, tz: ZoneInfo) -> datetime:
    """`now` dan keyingi eng yaqin HH:MM (mahalliy vaqt) — tz bilan."""
    local = now.astimezone(tz)
    t = parse_hhmm(hhmm)
    cand = datetime.combine(local.date(), t, tzinfo=tz)
    if cand <= local:
        cand += timedelta(days=1)
    return cand


def generation_time(slot_hhmm: str, minutes_before: int, tz: ZoneInfo) -> time:
    base = datetime.combine(datetime(2000, 1, 3).date(), parse_hhmm(slot_hhmm))
    t = (base - timedelta(minutes=minutes_before)).time()
    return t.replace(tzinfo=tz)


def preview_at(slot_at: datetime, minutes_before: int, now: datetime) -> datetime:
    return max(now, slot_at - timedelta(minutes=minutes_before))


def publish_at(slot_at: datetime, preview_sent: datetime, minutes_before: int) -> datetime:
    """Post chiqish vaqti: rejalashtirilgan vaqt, lekin admin kamida N daqiqa ko'rishi shart."""
    return max(slot_at, preview_sent + timedelta(minutes=minutes_before))


def pick_least_used(options: list[str], used_recent_first: list[str], rng: random.Random | None = None) -> str:
    """Eng kam ishlatilganini tanlaydi; tenglikda eng uzoq vaqt ishlatilmaganini."""
    rng = rng or random.Random()
    counts = Counter(u for u in used_recent_first if u in options)
    min_count = min(counts.get(o, 0) for o in options)
    cands = [o for o in options if counts.get(o, 0) == min_count]
    if len(cands) > 1:
        # oxirgi marta qachon ishlatilgan (indeks katta = uzoqroq); hech ishlatilmagan = eng yaxshi
        def age(o: str) -> int:
            return used_recent_first.index(o) if o in used_recent_first else 10_000
        best = max(age(o) for o in cands)
        cands = [o for o in cands if age(o) == best]
    return rng.choice(cands)


def styles_for(styles: list[dict], post_type: str) -> list[dict]:
    return [s for s in styles if post_type in s.get("applies_to", [])]


def pick_style(styles: list[dict], post_type: str, recent_style_ids: list[str],
               exclude: str | None = None) -> dict:
    options = styles_for(styles, post_type)
    if not options:
        raise ValueError(f"{post_type} uchun uslub yo'q (styles.yaml)")
    ids = [s["id"] for s in options if s["id"] != exclude] or [s["id"] for s in options]
    chosen = pick_least_used(ids, recent_style_ids)
    return next(s for s in options if s["id"] == chosen)
