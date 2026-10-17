"""Kunlik testlar: generator, tekshiruvlar va GitHub rejimi oqimi (soxta Telegram va soat bilan)."""
import asyncio
import json
import random
from datetime import datetime, timedelta

import pytest

from enturk import oneshot, quiz
from enturk.db import DB
from enturk.mock import FakeGemini
from enturk.oneshot import SlotRunner
from enturk.pipeline import Pipeline
from enturk.quiz_runner import QuizRunner
from enturk.mock import FakeEleven
from enturk.settings import load_settings
from tests.test_oneshot import Clock, FakeTG


class PollTG(FakeTG):
    async def send_poll(self, chat_id, question, options, correct, explanation="", anonymous=True):
        assert len(question) <= 300 and 2 <= len(options) <= 12
        assert all(1 <= len(o) <= 100 for o in options)
        assert 0 <= correct < len(options) and len(explanation) <= 200
        self.sent.append(("poll", chat_id, question, options, correct, explanation))
        return self._m(chat_id)


async def _nosleep(_):
    return None


@pytest.fixture
def env(tmp_path, monkeypatch):
    s = load_settings()
    s.admin_ids = [111]
    s.channel = "@EnTurk_CSR"
    s.data_dir = tmp_path
    # 2026-10-17 shanba, 16:07 Toshkent (testlar 17:00 da)
    clock = Clock(datetime(2026, 10, 17, 16, 7, tzinfo=s.tz))
    monkeypatch.setattr(oneshot, "utcnow", clock.now)
    db = DB(tmp_path / "e.db")
    return s, db, clock


def _runner(s, db, tg, gemini=None):
    r = QuizRunner(s, db, gemini or FakeGemini(), tg)
    r.sleep = _nosleep
    return r


def _channel(tg):
    return [x for x in tg.sent if x[1] == "@EnTurk_CSR"]


# ------------------------------------------------------------------ tekshiruvlar
def test_problems_catch_bad_questions():
    good = quiz.clean_question({"kind": "grammar", "question": "Bo'sh joyni to'ldiring:\nEv___ gidiyorum.",
                                "options": ["-e", "-a", "-de", "-den"], "correct": "-e",
                                "explanation": "ev + -e → eve."})
    assert quiz.problems(good, quiz.PREFIX_LEN) == []
    bad = dict(good, options=["-e", "-e", "-de", "-den"])
    assert "bir xil variantlar" in quiz.problems(bad, quiz.PREFIX_LEN)
    bad = dict(good, correct="-ye")
    assert "to'g'ri javob variantlar orasida yo'q" in quiz.problems(bad, quiz.PREFIX_LEN)
    bad = dict(good, options=["-e", "-a", "-de"])
    assert any("variant" in p for p in quiz.problems(bad, quiz.PREFIX_LEN))
    bad = dict(good, explanation="ев")
    assert "kirill harflari bor" in quiz.problems(bad, quiz.PREFIX_LEN)
    bad = dict(good, question="x" * 290)
    assert "savol juda uzun" in quiz.problems(bad, quiz.PREFIX_LEN)


def test_finalize_shuffles_but_keeps_correct_answer():
    q = quiz.clean_question({"kind": "vocab", "question": "«qozon»?", "options": ["tencere", "tava", "kaşık", "çatal"],
                             "correct": "tencere", "explanation": "tencere — qozon"})
    positions = set()
    for seed in range(20):
        f = quiz.finalize(q, random.Random(seed))
        assert f["options"][f["correct_index"]] == "tencere"
        positions.add(f["correct_index"])
    assert len(positions) > 1


def test_make_set_5_grammar_5_vocab(env):
    s, db, clock = env
    qs = asyncio.run(quiz.make_quiz_set(s, db, FakeGemini(), now=clock.now()))
    kinds = [q["kind"] for q in qs.questions]
    assert kinds == ["grammar"] * 5 + ["vocab"] * 5
    assert "KUNLIK TEST — 10 ta savol" in qs.intro_caption and "@EnTurk_CSR" in qs.intro_caption
    assert qs.image[:2] == b"\xff\xd8"


def test_checker_rejections_are_refilled(env):
    s, db, clock = env

    class Strict(FakeGemini):
        async def generate_json(self, system, prompt, **kw):
            data, src = await super().generate_json(system, prompt, **kw)
            if "QUIZ CHECKER" in system and self.calls.count("quiz_checker") == 1:
                for r in data["results"][:4]:
                    r["ok"], r["problem"] = False, "ikkita to'g'ri javob"
            return data, src

    g = Strict()
    qs = asyncio.run(quiz.make_quiz_set(s, db, g, now=clock.now()))
    assert len(qs.questions) == 10
    assert g.calls.count("quiz_writer") == 2


# ------------------------------------------------------------------ oqim
def test_nothing_pressed_publishes_intro_then_10_quizzes(env):
    s, db, clock = env
    tg = PollTG(clock)
    assert asyncio.run(_runner(s, db, tg).run()) is True
    admin = [x for x in tg.sent if x[1] == 111]
    assert admin[0][0] == "photo" and "KUNLIK TEST" in admin[0][2]
    assert any(x[0] == "text" and "✅" in x[2] and "1/10" in x[2] for x in admin)   # savol-javoblar
    ch = _channel(tg)
    assert ch[0][0] == "photo" and "KUNLIK TEST" in ch[0][2]
    polls = [x for x in ch if x[0] == "poll"]
    assert len(polls) == 10 and len(ch) == 11
    assert polls[0][2].startswith("1/10 · 📘 Grammatika") and polls[9][2].startswith("10/10 · 📗 Kelime bilgisi")
    assert clock.t >= datetime(2026, 10, 17, 17, 0, tzinfo=s.tz)
    d = db.by_status("published")[0]
    assert d["post_type"] == quiz.QUIZ_TYPE and len(json.loads(d["qa_json"])["questions"]) == 10
    # ikkinchi ishga tushishda hech narsa qilinmaydi
    tg2 = PollTG(clock)
    assert asyncio.run(_runner(s, db, tg2).run()) is False
    assert tg2.sent == []


def test_regen_makes_new_questions(env):
    s, db, clock = env
    tg = PollTG(clock, script=[(datetime(2026, 10, 17, 16, 52, tzinfo=s.tz), "regen:LAST")])
    asyncio.run(_runner(s, db, tg).run())
    photos = [x for x in tg.sent if x[1] == 111 and x[0] == "photo"]
    assert len(photos) == 2
    rows = db.for_slot(datetime(2026, 10, 17, 17, 0, tzinfo=s.tz))
    assert [r["status"] for r in rows] == ["cancelled", "published"]
    q1 = {q["question"] for q in json.loads(rows[0]["qa_json"])["questions"]}
    q2 = {q["question"] for q in json.loads(rows[1]["qa_json"])["questions"]}
    assert not q1 & q2
    assert len([x for x in _channel(tg) if x[0] == "poll"]) == 10


def test_publish_now_button(env):
    s, db, clock = env
    tg = PollTG(clock, script=[(datetime(2026, 10, 17, 16, 51, tzinfo=s.tz), "now:LAST")])
    asyncio.run(_runner(s, db, tg).run())
    assert len(_channel(tg)) == 11
    assert clock.t < datetime(2026, 10, 17, 17, 0, tzinfo=s.tz)


def test_test_mode_goes_to_admin_only(env):
    s, db, clock = env
    tg = PollTG(clock)
    asyncio.run(_runner(s, db, tg).run(test=True))
    assert _channel(tg) == []
    assert len([x for x in tg.sent if x[1] == 111 and x[0] == "poll"]) == 10
    assert db.by_status("cancelled")


def test_slot_dispatch_picks_quiz_not_post(env):
    s, db, clock = env
    tg = PollTG(clock)
    posts = SlotRunner(s, db, Pipeline(s, db, FakeGemini(), FakeEleven()), tg)
    assert posts.find_slot(clock.now()) is None          # 16:07 da post yo'q
    assert _runner(s, db, tg).find_slot(clock.now()) is not None
    clock.t = datetime(2026, 10, 17, 12, 7, tzinfo=s.tz)  # 13:00 posti vaqti
    assert posts.find_slot(clock.now()) is not None
    assert _runner(s, db, tg).find_slot(clock.now()) is None


def test_disabled_and_paused(env, monkeypatch):
    s, db, clock = env
    s.cfg["quiz"]["enabled"] = False
    assert _runner(s, db, PollTG(clock)).find_slot(clock.now()) is None
    s.cfg["quiz"]["enabled"] = True
    monkeypatch.setenv("PAUSED", "1")
    tg = PollTG(clock)
    assert asyncio.run(_runner(s, db, tg).run()) is False and tg.sent == []


# ------------------------------------------------------------------ kuchaytirilgan tekshiruv
def test_solver_disagreement_rejects_question(env):
    s, db, clock = env

    class WrongSolver(FakeGemini):
        async def generate_json(self, system, prompt, **kw):
            data, src = await super().generate_json(system, prompt, **kw)
            if "QUIZ SOLVER" in system and self.calls.count("quiz_solver") == 1:
                data["answers"][0]["choice"] = "-dan"          # boshqa javob
                data["answers"][1]["ambiguous"] = True         # ikki javob ham to'g'ri
            return data, src

    g = WrongSolver()
    qs = asyncio.run(quiz.make_quiz_set(s, db, g, now=clock.now()))
    assert len(qs.questions) == 10
    assert qs.qa["rejected"] >= 2


def test_low_score_rejected_and_editor_cannot_touch_turkish(env):
    s, db, clock = env

    class Picky(FakeGemini):
        async def generate_json(self, system, prompt, **kw):
            data, src = await super().generate_json(system, prompt, **kw)
            if "QUIZ CHECKER" in system:
                data["results"][0]["score"] = 7
            if "UZBEK EDITOR" in system:
                for it in data["items"]:
                    if "\n" in it["question"]:
                        it["question"] = it["question"].replace("okul___", "ev___")   # turkchani buzadi
                    it["explanation"] = "Tahrirlangan izoh: yo'nalish kelishigi."
            return data, src

    qs = asyncio.run(quiz.make_quiz_set(s, db, Picky(), now=clock.now()))
    assert all("okul___" in q["question"] for q in qs.questions if q["kind"] == "grammar")
    assert all(q["explanation"].startswith("Tahrirlangan") for q in qs.questions)
    assert qs.qa["rejected"] >= 1


def test_apostrophes_and_gap_checks():
    q = quiz.clean_question({"kind": "grammar", "question": "Bo‘sh joyni to‘ldiring:\nEv____ gidiyorum.",
                             "options": ["-e", "-a", "-de", "-den"], "correct": "-e", "explanation": "ma’no"})
    assert "Bo'sh joyni to'ldiring" in q["question"] and "Ev___ " in q["question"] and q["explanation"] == "💡 ma'no"
    two_gaps = dict(q, question="Bo'sh joyni to'ldiring:\nEv___ ___ gidiyorum.")
    assert any("bo'sh joy" in p for p in quiz.problems(two_gaps, quiz.PREFIX_LEN))


def test_emojis_on_questions_options_and_explanations(env):
    s, db, clock = env
    qs = asyncio.run(quiz.make_quiz_set(s, db, FakeGemini(), now=clock.now()))
    for i, q in enumerate(qs.questions, 1):
        assert quiz.has_emoji(q["question"].split("\n")[0])
        opts = quiz.poll_options(q)
        assert all(quiz.has_emoji(o[:2]) for o in opts) and len(set(o.split()[0] for o in opts)) == 4
        assert [o.split(" ", 1)[1] for o in opts] == q["options"]
        ex = quiz.poll_explanation(q)
        assert ex.startswith("✅ " + q["options"][q["correct_index"]]) and len(ex) <= 200
    assert quiz.poll_question(qs.questions[-1], 10, 10).startswith("10/10 · 📗 Kelime bilgisi 🏁")
    # model variantlarga emoji qo'ysa ham olib tashlanadi
    c = quiz.clean_question({"kind": "vocab", "question": "🔤 X?\nY", "options": ["🍞 ekmek", "su 💧", "et", "süt"],
                             "correct": "🍞 ekmek", "explanation": "e"})
    assert c["options"][:2] == ["ekmek", "su"] and c["correct"] == "ekmek"
