"""Navbatchi: GitHub jadvaliga ishonmasdan, keyingi post yoki test vaqtini o'zi kutadi.

Keyingi ish (post yoki kunlik test) uchun tayyorlash vaqti kelguncha uxlaydi (eng ko'pi CAP).
Vaqt kelsa "FIRE", aks holda "WAIT" deb chiqaradi. Workflow shunga qarab asosiy tizimni ishga tushiradi
va navbatchini o'zini qayta ishga tushiradi, shunda zanjir uzilmaydi.
"""
from __future__ import annotations

import os
import sys
import time
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from enturk.db import DB  # noqa: E402
from enturk.oneshot import SlotRunner, utcnow  # noqa: E402
from enturk.quiz_runner import QuizRunner  # noqa: E402
from enturk.settings import load_settings  # noqa: E402

CAP = timedelta(hours=float(os.getenv("KEEPER_CAP_HOURS", "4.5")))
STEP = timedelta(minutes=10)
# find_slot ish vaqtidan 2 soat oldin "ochiladi"; tayyorlash uchun ~70 daqiqa oldin boshlash yetarli
LEAD_DELAY = timedelta(minutes=50)


def next_wake(posts: SlotRunner, quizzes: QuizRunner, now) -> tuple[object, str]:
    for i in range(0, 6 * 30):
        x = now + i * STEP
        post = posts.find_slot(x)
        quiz = quizzes.find_slot(x)
        if post or quiz:
            what = []
            if post:
                what.append(f"post {post[0].astimezone(posts.s.tz):%d.%m %H:%M}")
            if quiz:
                what.append(f"test {quiz.astimezone(posts.s.tz):%d.%m %H:%M}")
            return (now if i == 0 else x + LEAD_DELAY), ", ".join(what)
    return None, "yaqin 30 soatda ish yo'q"


def main() -> None:
    s = load_settings()
    db = DB(s.data_dir / "enturk.db")
    posts = SlotRunner(s, db, None, None)  # type: ignore[arg-type]
    quizzes = QuizRunner(s, db, None, None)  # type: ignore[arg-type]
    now = utcnow()
    wake, what = next_wake(posts, quizzes, now)
    limit = now + CAP
    if wake is None or wake > limit:
        print(f"Keyingi ish: {what}. {limit.astimezone(s.tz):%H:%M} gacha kutaman, keyin navbatchi yangilanadi",
              flush=True)
        time.sleep(max(0, (limit - utcnow()).total_seconds()))
        print("WAIT", flush=True)
        return
    print(f"Keyingi ish: {what}. Tizim {wake.astimezone(s.tz):%H:%M} da ishga tushadi", flush=True)
    time.sleep(max(0, (wake - utcnow()).total_seconds()))
    paused = os.getenv("PAUSED", "0") == "1" or db.get_kv("paused", "0") == "1"
    print("WAIT" if paused else "FIRE", flush=True)


if __name__ == "__main__":
    main()
