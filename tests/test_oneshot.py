"""GitHub rejimi oqimi: soxta Telegram va soxta soat bilan."""
import asyncio
from datetime import datetime, timedelta

import pytest

from enturk import oneshot
from enturk.db import DB, parse_iso
from enturk.mock import FakeEleven, FakeGemini
from enturk.oneshot import SlotRunner
from enturk.pipeline import Pipeline
from enturk.settings import load_settings


class Clock:
    def __init__(self, t): self.t = t
    def now(self): return self.t


class FakeTG:
    def __init__(self, clock, script=None):
        self.clock, self.sent, self.answers, self.edits = clock, [], [], []
        self.script = script or []   # [(vaqt, callback_data), ...]
        self.uid, self.mid = 0, 500

    def _m(self, chat):
        self.mid += 1
        return {"message_id": self.mid, "chat": {"id": chat}}

    async def send_message(self, chat_id, text, reply_markup=None):
        self.sent.append(("text", chat_id, text, reply_markup)); return self._m(chat_id)
    async def send_photo(self, chat_id, photo, caption):
        self.sent.append(("photo", chat_id, caption)); return self._m(chat_id)
    async def send_audio(self, chat_id, audio, title, performer="EnTurk_CSR"):
        self.sent.append(("audio", chat_id, title)); return self._m(chat_id)
    async def edit_text(self, chat_id, message_id, text):
        self.edits.append(text)
    async def answer_callback(self, cid, text="", alert=False):
        self.answers.append(text)

    async def get_updates(self, offset, timeout):
        if offset == -1:
            return []
        for i, (at, data) in enumerate(self.script):
            if self.clock.t >= at:
                self.script.pop(i)
                self.uid += 1
                if data.startswith("regen:LAST") or data.startswith("now:LAST"):
                    last = [s for s in self.sent if s[0] == "text" and s[3]][-1]
                    data = last[3]["inline_keyboard"][0][0 if data.startswith("regen") else 1]["callback_data"]
                return [{"update_id": self.uid, "callback_query":
                         {"id": str(self.uid), "from": {"id": 111}, "data": data}}]
        self.clock.t += timedelta(seconds=timeout)
        return []


@pytest.fixture
def env(tmp_path, monkeypatch):
    s = load_settings()
    s.admin_ids = [111]
    s.channel = "@EnTurk_CSR"
    s.data_dir = tmp_path
    s.eleven_key = "test"
    for k in s.cfg["elevenlabs"]["voices"]:
        s.cfg["elevenlabs"]["voices"][k] = f"mock-{k.split('_')[1]}"
    # 2026-09-28 dushanba, 07:07 Toshkent
    clock = Clock(datetime(2026, 9, 28, 7, 7, tzinfo=s.tz))
    monkeypatch.setattr(oneshot, "utcnow", clock.now)
    db = DB(tmp_path / "e.db")
    return s, db, clock


def _runner(s, db, tg):
    return SlotRunner(s, db, Pipeline(s, db, FakeGemini(), FakeEleven()), tg)


def test_nothing_pressed_publishes_at_slot(env):
    s, db, clock = env
    tg = FakeTG(clock)
    asyncio.run(_runner(s, db, tg).run())
    admin = [x[0] for x in tg.sent if x[1] == 111]
    chan = [x[0] for x in tg.sent if x[1] == "@EnTurk_CSR"]
    assert admin == ["photo", "audio", "text"] and chan == ["photo", "audio"]
    (d,) = db.by_status("published")
    assert parse_iso(d["publish_at"]).astimezone(s.tz).strftime("%H:%M") == "08:00"
    assert "Kanalga chiqdi" in tg.edits[-1]


def test_regen_then_publish_late(env):
    s, db, clock = env
    regen_at = datetime(2026, 9, 28, 7, 56, tzinfo=s.tz)
    tg = FakeTG(clock, script=[(regen_at, "regen:LAST")])
    asyncio.run(_runner(s, db, tg).run())
    assert len(db.by_status("cancelled")) == 1
    (d,) = db.by_status("published")
    pub = parse_iso(d["publish_at"]).astimezone(s.tz)
    assert pub.strftime("%H:%M") >= "08:06"          # asl vaqt o'tsa ham chiqdi
    assert [x[0] for x in tg.sent if x[1] == "@EnTurk_CSR"] == ["photo", "audio"]  # faqat bitta post
    assert [x[0] for x in tg.sent if x[1] == 111].count("photo") == 2


def test_stale_button_ignored_and_now_publishes(env):
    s, db, clock = env
    t = datetime(2026, 9, 28, 7, 52, tzinfo=s.tz)
    tg = FakeTG(clock, script=[(t, "regen:9999"), (t, "now:LAST")])
    asyncio.run(_runner(s, db, tg).run())
    assert any("eskirgan" in a for a in tg.answers)
    (d,) = db.by_status("published")
    assert parse_iso(d["published_at"]) is not None


def test_already_published_slot_is_skipped(env):
    s, db, clock = env
    asyncio.run(_runner(s, db, FakeTG(clock)).run())
    clock.t = datetime(2026, 9, 28, 7, 30, tzinfo=s.tz)   # qayta ishga tushsa
    tg2 = FakeTG(clock)
    asyncio.run(_runner(s, db, tg2).run())
    # 08:00 allaqachon chiqqan, 13:00 hali uzoq → hech narsa qilinmaydi
    assert len(db.by_status("published")) == 1 and tg2.sent == []


def test_test_post_times_out_without_publishing(env):
    s, db, clock = env
    tg = FakeTG(clock)
    asyncio.run(_runner(s, db, tg).run(test_type="haqiqiy_diolog"))
    assert not [x for x in tg.sent if x[1] == "@EnTurk_CSR"]
    assert "Sinov tugadi" in tg.edits[-1]


def test_without_elevenlabs_posts_photo_only(env):
    s, db, clock = env
    s.eleven_key = ""
    tg = FakeTG(clock)
    asyncio.run(_runner(s, db, tg).run())
    chan = [x for x in tg.sent if x[1] == "@EnTurk_CSR"]
    assert [x[0] for x in chan] == ["photo"]
    assert "🎧" not in chan[0][2]
