"""Bot oqimi: tayyorlash → adminga ko'rsatish → (Qayta ishlash) → kanalga chiqarish.
Telegram o'rniga soxta bot, Gemini/ElevenLabs o'rniga mock ishlatiladi."""
import asyncio
from datetime import timedelta
from types import SimpleNamespace

import pytest

from enturk import bot as botmod
from enturk.bot import Coordinator
from enturk.db import DB, parse_iso
from enturk.mock import FakeEleven, FakeGemini
from enturk.pipeline import Pipeline
from enturk.settings import load_settings


class FakeBot:
    def __init__(self):
        self.sent = []
        self._mid = 100

    def _msg(self, chat_id):
        self._mid += 1
        return SimpleNamespace(chat_id=chat_id, message_id=self._mid)

    async def send_photo(self, chat_id, photo, caption, parse_mode):
        self.sent.append(("photo", chat_id, caption))
        return self._msg(chat_id)

    async def send_audio(self, chat_id, audio, title, performer, filename):
        self.sent.append(("audio", chat_id, title))
        return self._msg(chat_id)

    async def send_message(self, chat_id, text, parse_mode=None, reply_markup=None):
        self.sent.append(("text", chat_id, text, reply_markup))
        return self._msg(chat_id)

    async def edit_message_text(self, chat_id, message_id, text, parse_mode, reply_markup):
        self.sent.append(("edit", chat_id, text))


class FakeJob:
    def __init__(self, cb, when, data, name):
        self.cb, self.when, self.data, self.name, self.removed = cb, when, data, name, False

    def schedule_removal(self):
        self.removed = True


class FakeJobQueue:
    def __init__(self):
        self.jobs = []

    def run_once(self, cb, when, data, name):
        self.jobs.append(FakeJob(cb, when, data, name))

    def get_jobs_by_name(self, name):
        return [j for j in self.jobs if j.name == name and not j.removed]

    async def fire(self, name):
        (job,) = self.get_jobs_by_name(name)
        job.removed = True
        await job.cb(SimpleNamespace(job=job))
        return job


class FakeApp:
    def __init__(self):
        self.bot = FakeBot()
        self.job_queue = FakeJobQueue()
        self.tasks = []

    def create_task(self, coro):
        t = asyncio.ensure_future(coro)
        self.tasks.append(t)
        return t

    async def drain(self):
        while self.tasks:
            await self.tasks.pop(0)


@pytest.fixture
def coord(tmp_path, monkeypatch):
    monkeypatch.setenv("ADMIN_IDS", "111")
    monkeypatch.setenv("CHANNEL_ID", "@EnTurk_CSR")
    s = load_settings()
    s.data_dir = tmp_path
    s.eleven_key = "test"
    s.admin_ids = [111]
    for k in s.cfg["elevenlabs"]["voices"]:
        s.cfg["elevenlabs"]["voices"][k] = f"mock-{k.split('_')[1]}"
    db = DB(tmp_path / "t.db")
    c = Coordinator(s, db, Pipeline(s, db, FakeGemini(), FakeEleven()))
    c.app = FakeApp()
    return c


def _slot(coord):
    # keyingi dushanba 08:00 — yangi_sozlar
    from datetime import datetime
    from enturk import planner
    now = botmod.utcnow()
    for i in range(8):
        cand = planner.next_slot_after(now + timedelta(days=i), "08:00", coord.s.tz)
        if cand.weekday() == 0:
            return cand
    raise AssertionError


def test_normal_flow_publishes_on_time(coord):
    async def go():
        slot = _slot(coord)
        did = coord.db.create_draft(slot_at=slot, post_type="yangi_sozlar", lang="tr")
        await coord.produce(did)
        d = coord.db.get(did)
        assert d["status"] == "ready"
        job = coord.app.job_queue.get_jobs_by_name(f"prev-{did}")[0]
        assert job.when == slot - timedelta(minutes=10)
        await coord.app.job_queue.fire(f"prev-{did}")
        d = coord.db.get(did)
        assert d["status"] == "previewed"
        kinds = [x[0] for x in coord.app.bot.sent if x[1] == 111]
        assert kinds == ["photo", "audio", "text"]
        pub = coord.app.job_queue.get_jobs_by_name(f"pub-{did}")[0]
        assert pub.when >= slot
        await coord.app.job_queue.fire(f"pub-{did}")
        assert coord.db.get(did)["status"] == "published"
        channel = [x for x in coord.app.bot.sent if x[1] == "@EnTurk_CSR"]
        assert [x[0] for x in channel] == ["photo", "audio"]
        assert "👉 @EnTurk_CSR" in channel[0][2]
    asyncio.run(go())


def test_regenerate_replaces_and_publishes_late(coord):
    async def go():
        slot = _slot(coord)
        did = coord.db.create_draft(slot_at=slot, post_type="yangi_sozlar", lang="tr")
        await coord.produce(did)
        await coord.app.job_queue.fire(f"prev-{did}")
        # admin "Qayta ishlash" ni bosdi
        msg = await coord.regenerate(did)
        assert "Qayta" in msg
        assert coord.db.get(did)["status"] == "cancelled"
        assert not coord.app.job_queue.get_jobs_by_name(f"pub-{did}")   # eski post chiqmaydi
        await coord.app.drain()
        new = coord.db.by_status("ready")[0]
        assert new["parent_id"] == did and new["slot_at"] == coord.db.get(did)["slot_at"]
        assert new["style_id"] != coord.db.get(did)["style_id"]          # boshqa uslub
        await coord.app.job_queue.fire(f"prev-{new['id']}")               # darhol ko'rsatiladi
        pub = coord.app.job_queue.get_jobs_by_name(f"pub-{new['id']}")[0]
        assert pub.when >= parse_iso(new["slot_at"])
        assert pub.when >= botmod.utcnow() + timedelta(minutes=9)         # kamida ~10 daqiqa ko'rish
        await coord.app.job_queue.fire(f"pub-{new['id']}")
        assert coord.db.get(new["id"])["status"] == "published"
        # eski post kanalga chiqmagan
        assert coord.db.get(did)["status"] == "cancelled"
        # ikkinchi marta chiqarish mumkin emas
        assert await coord.publish(new["id"]) is False
    asyncio.run(go())


def test_test_post_does_not_autopublish(coord):
    async def go():
        did = coord.db.create_draft(slot_at=botmod.utcnow(), post_type="haqiqiy_diolog", lang="tr",
                                    is_test=True)
        await coord.produce(did)
        await coord.app.job_queue.fire(f"prev-{did}")
        assert coord.db.get(did)["status"] == "previewed"
        assert not coord.app.job_queue.get_jobs_by_name(f"pub-{did}")
        ctrl = [x for x in coord.app.bot.sent if x[0] == "text"][-1][2]
        assert "SINOV" in ctrl
    asyncio.run(go())


def test_failure_notifies_admin(coord, monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("Gemini 429")
    monkeypatch.setattr(coord.pipeline, "run", boom)

    async def go():
        did = coord.db.create_draft(slot_at=_slot(coord), post_type="imtihon", lang="tr")
        await coord.produce(did)
        assert coord.db.get(did)["status"] == "failed"
        last = coord.app.bot.sent[-1]
        assert last[0] == "text" and "tayyorlanmadi" in last[2]
    asyncio.run(go())
