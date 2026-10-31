"""Kunlik testlar: 5 ta grammatika + 5 ta kelime bilgisi, Telegram quiz (QuizBot uslubida).

  QUIZ WRITER agent → kod tekshiruvi → QUIZ CHECKER agent (har bir savol) → kirish posti + 10 ta quiz
"""
from __future__ import annotations

import html
import io
import json
import logging
import random
import re
import zlib
from dataclasses import dataclass, field
from datetime import datetime

from . import caption as cap
from . import graphics, planner
from .agents import illustrator
from .db import DB
from .gemini import GeminiClient
from .settings import ROOT, Settings

log = logging.getLogger(__name__)

QUIZ_TYPE = "kunlik_test"
QUIZ_LANG = "tr_test"          # postlar tarixi bilan aralashmasligi uchun alohida
GRAMMAR, VOCAB = "grammar", "vocab"
KIND_LABEL = {GRAMMAR: "📘 Grammatika", VOCAB: "📗 Kelime bilgisi"}

# Telegram cheklovlari
Q_LIMIT = 300
OPT_LIMIT = 100
EXPL_LIMIT = 200
N_OPTIONS = 4
EXTRA = 3          # har bir turdan nechta zaxira savol so'raladi
MAX_ROUNDS = 4

CYRILLIC = re.compile(r"[Ѐ-ӿ]")

WRITER_SYSTEM = """You are the QUIZ WRITER agent — an experienced teacher of Turkish for Uzbek speakers — for the
Telegram channel @EnTurk_CSR. You write multiple-choice questions that will be posted as Telegram quizzes
(like @QuizBot): a question, 4 answer options, exactly one correct option and a short explanation.

LEVEL: CEFR {level}. Every question must fit this level.

"grammar" questions — each tests ONE Turkish grammar point: vowel harmony in suffixes, buffer letters, consonant
mutation (kitap → kitabı), cases (-ı, -e, -de, -den, ile), possessive suffixes, plural, tenses (-iyor, -di, -miş,
-ecek, -ir/-ar, geniş zaman olumsuz), question particle mi, imperative, -mek istemek, -ebilmek, -meli, -mek zorunda,
conditionals (-se, -ise), participles (-en, -dik, -ecek), converbs (-ip, -erek, -ince, -meden, -dikten sonra),
postpositions (için, gibi, kadar, göre, önce, sonra), conjunctions (ama, çünkü, ya da, hem…hem), comparison (daha,
en), word order, passive/causative at higher levels. Use a varied mix: at most two questions on the same point.
Typical form: a Turkish sentence with a gap "___" and four forms of the same word or suffix.

"vocab" questions (kelime bilgisi) — test word knowledge with varied forms: meaning of a Turkish word in Uzbek,
Uzbek word/phrase → Turkish, the right word for a gap in a context sentence, synonym (eş anlamlı), antonym
(zıt anlamlı), collocations (karar vermek, yardım etmek), set phrases (Geçmiş olsun, Kolay gelsin). Prefer
useful everyday words of this level, several themes.

WRITING RULES
- "question": the instruction in Uzbek (Latin script), then a line break, then the Turkish part
  (sentence, word or phrase) on its own line. Example:
  "✍️ Bo'sh joyni to'ldiring:\\nDün akşam arkadaşlarım___ sinemaya gittik. 🎬🍿" Max 220 characters, plain text,
  no HTML, no numbering, no level tag. Use "\\n" between the instruction and the Turkish sentence.
- EMOJIS (to make the quiz fun): start the Uzbek instruction with ONE fitting emoji (✍️ gap-fill, 🔤 meaning,
  🔁 synonym, ↔️ antonym, 🧩 phrase/collocation, 🗣 set phrase, 🔄 word form…) and end the Turkish line with ONE or
  TWO emojis that fit the situation of the sentence (🏫 school, 🛒 shopping, ✈️ travel, 🍽 food, 🩺 doctor…).
  An emoji must NEVER give away the correct answer (in a meaning/translation question do not draw the answer word).
  Max 3 emojis in the question. No emojis in the options (the system decorates them itself).
- "options": exactly 4 different options, each max 60 characters, all plausible and of the same kind
  (four suffix forms, four words…). Exactly ONE option is correct; the others must be clearly wrong for a
  teacher. Never "all of the above"/"none of the above".
- "correct": the exact text of the correct option.
- "explanation": Uzbek (Latin), max 150 characters, max one line break: why the answer is right (the rule or the
  meaning), may include a very short Turkish example. Start it with ONE fitting emoji (💡 📌 🧠 🎯 📖 …) and you may
  add one more at the end. It is shown to students who choose a wrong answer.
- Turkish must be 100% correct standard Turkish with ç ş ğ ı İ ö ü. Uzbek: correct Latin spelling with o', g',
  sh, ch and the apostrophe (so'z, ma'no). Never use Cyrillic.
- Nothing political, religious or unsuitable for school students.
- Do not reuse questions from the "already used" list and avoid the same tested words.

OUTPUT exactly one JSON object:
{{"grammar_focus": "short Uzbek phrase naming today's grammar topics (max 60 chars)",
  "vocab_theme": "short Uzbek phrase naming today's vocabulary themes (max 60 chars)",
  "questions": [{{"kind": "grammar|vocab", "question": "...", "options": ["...", "...", "...", "..."],
                 "correct": "...", "explanation": "...", "key": "the tested Turkish word or grammar point"}}]}}"""

WRITER_TEMPLATE = """Write {n_grammar} "grammar" questions and {n_vocab} "vocab" questions for level {level}.
Date: {date}.
{avoid_line}
Already used questions (do NOT repeat or paraphrase them):
{used}
Recently tested words / grammar points (prefer different ones): {keys}"""

EDITOR_SYSTEM = """You are the UZBEK EDITOR agent: a professional Uzbek (Latin script) proofreader who also knows
Turkish grammar terminology. You polish ONLY the Uzbek parts of quiz questions for Uzbek learners of Turkish.

Fix in the Uzbek instruction and explanation:
- spelling in the official Latin alphabet: o', g' and the tutuq belgisi written with the apostrophe ' (so'z, ma'no,
  qo'shimcha), sh, ch, ng; never Cyrillic;
- grammar, suffix agreement and natural modern phrasing (as a good Uzbek textbook would write it);
- precise word choice: e.g. a wish is "tilak", not "xushomad"; stale bread is "qotgan", not "eski"; use standard
  grammar terms: bosh, qaratqich, tushum, jo'nalish, o'rin-payt, chiqish kelishigi; egalik qo'shimchasi;
  hozirgi zamon, o'tgan zamon, kelasi zamon, keng zamon (geniş zaman); fe'l, ot, sifat, ravish, ko'makchi;
  unli / undosh, jarangli / jarangsiz undosh; ma'nodosh (sinonim), zid ma'noli (antonim);
- the explanation must say correctly WHY the right answer is right; remove filler.
Rules: keep EVERY Turkish word, sentence and suffix exactly as it is, and keep the emojis. Do not change the meaning or the answer.
Keep the instruction short. Explanation max 150 characters, max one line break.

Output exactly one JSON object: {"items": [{"i": 0, "question": "...", "explanation": "..."}]}
Return every item, edited or not."""

CHECKER_SYSTEM = """You are the QUIZ CHECKER agent: a strict native-level Turkish teacher (Türkçe öğretmeni) and an
Uzbek (Latin script) editor. Questions go to a public channel WITHOUT human review, so you are the last line of
defence. Reject anything you are not sure about.

For EVERY question check:
1. KEY: the option marked "correct" is right, and NO other option is also acceptable in standard modern Turkish
   (think about each distractor separately: could a native speaker say it? is it also grammatical? also a valid
   synonym/antonym/translation?). Any doubt → not ok.
2. TURKISH: 100% correct spelling (ı/i, İ, ş, ç, ğ, ö, ü, â), vowel harmony, consonant mutation, buffer letters,
   apostrophes with proper names, natural modern usage. The full sentence with the correct answer inserted must be
   natural and error-free. Distractors must be real-looking forms, but clearly wrong.
3. UZBEK: correct Latin spelling (o', g', apostrophe), correct grammar and PRECISE word choice and terminology;
   no Cyrillic; no awkward machine-like phrasing.
4. EXPLANATION: factually correct, matches the correct answer, explains the rule or meaning, no false statements
   about Turkish grammar.
5. CLARITY & LEVEL: understandable without extra context, fits CEFR {level}, exactly one gap if it is a gap-fill.
6. EMOJIS: they fit the content and NEVER reveal or hint at the correct answer (e.g. a 🍞 next to a question
   asking which word means "bread"). An emoji that gives a hint → not ok (or fix it by changing the emoji).
7. Limits: question max 220 chars, each option max 60 chars, explanation max 150 chars.

For each question return: "ok" (true only if everything is right), "score" 1-10 (10 = flawless), "problem"
(short), and — only if you can fix it with full confidence — "fixed": the COMPLETE corrected question object
(question, options, correct, explanation); otherwise "fixed": null.

Output exactly one JSON object:
{{"results": [{{"i": 0, "ok": true, "score": 10, "problem": "", "fixed": null}}]}}"""

SOLVER_SYSTEM = """You are the QUIZ SOLVER agent: an expert in Turkish (native level) taking a test. You do not know
the intended answers. For each question pick the single correct option and copy its text exactly.
If two or more options are acceptable, or none is, or the question is unclear, set "ambiguous": true.

Output exactly one JSON object:
{"answers": [{"i": 0, "choice": "exact option text", "ambiguous": false, "reason": ""}]}"""

MIN_SCORE = 9

OPENERS = [
    "Bilimingizni sinab ko'ring! Hozir pastda 10 ta test chiqadi 👇",
    "Test vaqti keldi! ⏰ 10 ta savol sizni kutmoqda 👇",
    "Bugun qanchalik tayyorsiz? Keling, tekshirib ko'ramiz 👇",
    "Kunlik mashq: 5 daqiqa, 10 ta savol. Boshladik! 👇",
    "Yangi testlar tayyor! Qalam emas, faqat diqqat kerak 😉👇",
    "Turk tilingizni mustahkamlash vaqti! Quyidagi testlarni yeching 👇",
]


@dataclass
class QuizSet:
    level: str
    grammar_focus: str
    vocab_theme: str
    questions: list[dict]          # {kind, question, options, correct_index, explanation, key}
    intro_caption: str = ""
    image: bytes = b""
    qa: dict = field(default_factory=dict)

    @property
    def keys(self) -> list[str]:
        return [str(q.get("key") or "") for q in self.questions]

    def to_json(self) -> dict:
        return {"level": self.level, "grammar_focus": self.grammar_focus, "vocab_theme": self.vocab_theme,
                "questions": self.questions, "qa": self.qa}


def quiz_cfg(s: Settings) -> dict:
    q = dict(s.cfg.get("quiz") or {})
    q.setdefault("enabled", True)
    q.setdefault("time", "17:00")
    q.setdefault("days", list(planner.DAYS))
    q.setdefault("grammar", 5)
    q.setdefault("vocab", 5)
    q.setdefault("levels", ["A1", "A2", "B1", "B2"])
    q.setdefault("poll_interval_seconds", 3)
    q.setdefault("hashtag", "test")
    return q


# ------------------------------------------------------------------ tekshiruvlar
def norm_q(text: str) -> str:
    t = cap.norm_item(text)
    return re.sub(r"[\s_]+", " ", t).strip()


EMOJI = re.compile("[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\u2190-\u21FF\u2300-\u23FF\uFE0F\u200D\u20E3]+")
# Variantlar bezagi: bir savolda bitta to'plam (javobga ishora qilmaydi, faqat o'rin belgisi)
DECO_SETS = [["🔴", "🔵", "🟢", "🟡"], ["🍎", "🍋", "🍇", "🍊"], ["🌷", "🌻", "🌹", "🌼"], ["⭐", "🌙", "☀️", "⚡"],
             ["🐱", "🐶", "🦊", "🐼"], ["💎", "🎈", "🎁", "🎀"], ["🚗", "🚲", "🚀", "⛵"], ["🧁", "🍩", "🍪", "🍭"],
             ["🟥", "🟦", "🟩", "🟨"], ["🌊", "🔥", "🍀", "❄️"], ["🎸", "🎺", "🥁", "🎻"], ["🦋", "🐝", "🐞", "🐬"]]
KIND_DEFAULT_EMOJI = {GRAMMAR: "✍️", VOCAB: "🔤"}


def has_emoji(t: str) -> bool:
    return bool(EMOJI.search(t))


def fix_apostrophes(t: str) -> str:
    """O'zbekcha o', g' va tutuq belgisi uchun bitta standart belgi."""
    return re.sub(r"(?<=[A-Za-z])[ʻʼ’‘`´](?=[A-Za-z]|\b)", "'", t)


def clean_question(raw: dict, kind: str | None = None) -> dict | None:
    """Model javobini standart ko'rinishga keltiradi. Yaroqsiz bo'lsa None."""
    if not isinstance(raw, dict):
        return None
    k = str(raw.get("kind") or kind or "").lower().strip()
    k = VOCAB if k.startswith(("voc", "kel", "word", "lug")) else GRAMMAR if k.startswith("gra") else k
    if k not in (GRAMMAR, VOCAB):
        return None
    q = str(raw.get("question") or "").replace("\\n", "\n").strip()
    q = re.sub(r"<[^>]+>", "", q)
    q = re.sub(r"\n{3,}", "\n\n", q)
    opts = [re.sub(r"\s+", " ", str(o)).strip() for o in (raw.get("options") or [])]
    opts = [re.sub(r"^[A-Da-d][\).:]\s+", "", o) for o in opts]
    opts = [re.sub(r"\s+", " ", EMOJI.sub("", o)).strip() for o in opts]      # bezakni tizim qo'yadi
    corr = re.sub(r"\s+", " ", str(raw.get("correct") or "")).strip()
    corr = re.sub(r"^[A-Da-d][\).:]\s+", "", corr)
    corr = re.sub(r"\s+", " ", EMOJI.sub("", corr)).strip()
    if isinstance(raw.get("correct_index"), int) and 0 <= raw["correct_index"] < len(opts) and not corr:
        corr = opts[raw["correct_index"]]
    expl = str(raw.get("explanation") or "").replace("\\n", "\n").strip()
    expl = re.sub(r"<[^>]+>", "", expl)
    q, expl = fix_apostrophes(q), fix_apostrophes(expl)
    q = re.sub(r"_{2,}", "___", q)
    q = re.sub(r"___\s+([.,!?;:])", r"___\1", q)
    if q and not has_emoji(q.split("\n", 1)[0]):
        q = f"{KIND_DEFAULT_EMOJI[k]} {q}"
    if expl and not has_emoji(expl[:3]):
        expl = f"💡 {expl}"
    return {"kind": k, "question": q, "options": opts, "correct": corr, "explanation": expl,
            "key": str(raw.get("key") or "").strip()[:60]}


def problems(q: dict, prefix_len: int) -> list[str]:
    out = []
    if not q["question"]:
        out.append("bo'sh savol")
    if len(q["question"]) + prefix_len > Q_LIMIT:
        out.append("savol juda uzun")
    if len(q["options"]) != N_OPTIONS:
        out.append(f"{len(q['options'])} ta variant (4 ta kerak)")
    if any(not o or len(o) > OPT_LIMIT - 4 for o in q["options"]):
        out.append("variant bo'sh yoki juda uzun")
    if len({cap.norm_item(o) for o in q["options"]}) != len(q["options"]):
        out.append("bir xil variantlar")
    matches = [o for o in q["options"] if o == q["correct"]] or \
              [o for o in q["options"] if cap.norm_item(o) == cap.norm_item(q["correct"])]
    if len(matches) != 1:
        out.append("to'g'ri javob variantlar orasida yo'q")
    if not q["explanation"] or len(q["explanation"]) > EXPL_LIMIT or q["explanation"].count("\n") > 2:
        out.append("izoh bo'sh yoki juda uzun")
    if CYRILLIC.search(q["question"] + q["explanation"] + "".join(q["options"])):
        out.append("kirill harflari bor")
    if "bo'sh joy" in q["question"].lower() and q["question"].count("___") != 1:
        out.append("bo'sh joy (___) bitta bo'lishi kerak")
    if any(cap.norm_item(o) in cap.norm_item(q["question"]).split() for o in q["options"]
           if len(o) > 3 and q["kind"] == VOCAB and "___" in q["question"]):
        out.append("javob savol ichida ko'rinib turibdi")
    return out


def finalize(q: dict, rng: random.Random) -> dict:
    """Variantlarni aralashtiradi (to'g'ri javob har doim A bo'lib qolmasligi uchun)."""
    opts = list(q["options"])
    correct = next(o for o in opts if o == q["correct"] or cap.norm_item(o) == cap.norm_item(q["correct"]))
    rng.shuffle(opts)
    return {"kind": q["kind"], "question": q["question"], "options": opts,
            "correct_index": opts.index(correct), "explanation": q["explanation"], "key": q["key"],
            "deco": rng.choice(DECO_SETS)}


def poll_question(q: dict, i: int, total: int) -> str:
    tail = " 🏁" if i == total else ""
    return f"{i}/{total} · {KIND_LABEL[q['kind']]}{tail}\n\n{q['question']}"


def poll_options(q: dict) -> list[str]:
    deco = q.get("deco") or DECO_SETS[0]
    return [f"{d} {o}" for d, o in zip(deco, q["options"])]


def poll_explanation(q: dict) -> str:
    """Izoh: to'g'ri javob + sabab (Telegram: 200 belgi, 2 tagacha qator)."""
    expl = q["explanation"]
    full = f"✅ {q['options'][q['correct_index']]}\n{expl}"
    return full if len(full) <= EXPL_LIMIT and full.count("\n") <= 2 else expl


PREFIX_LEN = len(poll_question({"kind": VOCAB, "question": ""}, 10, 10)) + 4   # + standart emoji


# ------------------------------------------------------------------ agentlar
def _recent(db: DB, days: int) -> list[dict]:
    rows = db.recent(days=days, post_type=QUIZ_TYPE)
    for r in rows:
        try:
            r["quiz"] = json.loads(r.get("qa_json") or "{}")
        except json.JSONDecodeError:
            r["quiz"] = {}
    return rows


async def make_quiz_set(s: Settings, db: DB, gemini: GeminiClient, *, now: datetime,
                        avoid_questions: list[str] | None = None, level: str | None = None,
                        with_image: bool = True) -> QuizSet:
    qc = quiz_cfg(s)
    n = {GRAMMAR: int(qc["grammar"]), VOCAB: int(qc["vocab"])}
    hist = _recent(db, 120)
    used_q = [q["question"] for r in hist for q in r["quiz"].get("questions", [])]
    used_q += list(avoid_questions or [])
    used_norm = {norm_q(x) for x in used_q}
    keys = [k for r in hist[:14] for k in r.get("items", [])]
    if not level:
        level = planner.pick_least_used(qc["levels"], [r["level"] for r in hist if r.get("level")])
    rng = random.Random(zlib.crc32(f"{now:%Y%m%d%H%M}{level}".encode()))
    log.info("Testlar: daraja %s", level)

    chosen: dict[str, list[dict]] = {GRAMMAR: [], VOCAB: []}
    focus, theme = "", ""
    scores: list[int] = []
    rejected: list[str] = []
    for rnd in range(MAX_ROUNDS):
        need = {k: n[k] - len(chosen[k]) for k in n}
        if all(v <= 0 for v in need.values()):
            break
        ask = {k: (v + EXTRA if v > 0 else 0) for k, v in need.items()}
        taken = [q["question"] for v in chosen.values() for q in v]
        prompt = WRITER_TEMPLATE.format(
            n_grammar=ask[GRAMMAR], n_vocab=ask[VOCAB], level=level, date=f"{now.astimezone(s.tz):%Y-%m-%d}",
            avoid_line=("Already chosen for today (write different ones): " + " | ".join(taken)) if taken else "",
            used="\n".join(f"- {x}" for x in used_q[-150:]) or "(none)",
            keys=", ".join(keys[:120]) or "(none)")
        data, _ = await gemini.generate_json(WRITER_SYSTEM.format(level=level), prompt, temperature=0.9)
        focus = focus or str(data.get("grammar_focus") or "").strip()[:70]
        theme = theme or str(data.get("vocab_theme") or "").strip()[:70]
        cands: list[dict] = []
        seen = {norm_q(q["question"]) for v in chosen.values() for q in v}
        for raw in data.get("questions") or []:
            q = clean_question(raw)
            if not q:
                continue
            bad = problems(q, PREFIX_LEN)
            nq = norm_q(q["question"])
            if nq in used_norm or nq in seen:
                bad.append("takror savol")
            if bad:
                rejected.append(f"{q['question'][:40]}…: {', '.join(bad)}")
                continue
            seen.add(nq)
            cands.append(q)
        if not cands:
            log.warning("Raund %s: yaroqli savol chiqmadi", rnd + 1)
            continue

        for q in await review_questions(gemini, level, cands, rng, rejected):
            if len(chosen[q["kind"]]) < n[q["kind"]] and norm_q(q["question"]) not in used_norm:
                chosen[q["kind"]].append(q)
        log.info("Raund %s: grammatika %s/%s, kelime %s/%s", rnd + 1, len(chosen[GRAMMAR]), n[GRAMMAR],
                 len(chosen[VOCAB]), n[VOCAB])

    if len(chosen[GRAMMAR]) < n[GRAMMAR] or len(chosen[VOCAB]) < n[VOCAB]:
        raise RuntimeError("Yetarli sifatli test tayyorlanmadi: " + "; ".join(rejected[-5:]))

    questions = [finalize(q, rng) for q in chosen[GRAMMAR] + chosen[VOCAB]]
    qs = QuizSet(level=level, grammar_focus=focus, vocab_theme=theme, questions=questions,
                 qa={"rejected": len(rejected), "reasons": rejected[-20:]})
    qs.intro_caption = intro_caption(s, qs, rng)
    if with_image:
        qs.image = intro_image(s, qs, rng)
    return qs


async def review_questions(gemini: GeminiClient, level: str, cands: list[dict], rng: random.Random,
                           rejected: list[str]) -> list[dict]:
    """3 bosqich: o'zbekcha muharrir → qattiq tekshiruvchi (tuzatishi mumkin) → mustaqil yechuvchi.
    Qaysidir bosqich ishlamasa yoki shubha bo'lsa — savol tashlanadi."""
    def short(q: dict) -> str:
        return q["question"].replace("\n", " ")[:45] + "…"

    # A) o'zbekcha matnni tahrirlash (turkcha qismlar o'zgarmasligi kod bilan tekshiriladi)
    try:
        ed, _ = await gemini.generate_json(
            EDITOR_SYSTEM, "Items:\n" + json.dumps(
                [{"i": i, "question": q["question"], "explanation": q["explanation"], "correct_answer": q["correct"]}
                 for i, q in enumerate(cands)], ensure_ascii=False, indent=1), temperature=0.2)
        edits = {int(x.get("i", -1)): x for x in ed.get("items") or [] if isinstance(x, dict)}
    except Exception as exc:  # noqa: BLE001
        log.warning("O'zbekcha tahrir ishlamadi: %s", exc)
        edits = {}
    for i, q in enumerate(cands):
        e = edits.get(i)
        if not e:
            continue
        new = dict(q)
        nq = str(e.get("question") or "").replace("\\n", "\n").strip()
        old_tr = turkish_part(q["question"])
        if nq and old_tr is not None and turkish_part(nq) == old_tr:
            new["question"] = nq
        ne = str(e.get("explanation") or "").replace("\\n", "\n").strip()
        if ne:
            new["explanation"] = ne
        if not problems(new, PREFIX_LEN):
            cands[i] = new

    # B) qattiq tekshiruv
    payload = [{"i": i, **{k: q[k] for k in ("kind", "question", "options", "correct", "explanation")}}
               for i, q in enumerate(cands)]
    try:
        rev, _ = await gemini.generate_json(
            CHECKER_SYSTEM.format(level=level),
            "Questions to review:\n" + json.dumps(payload, ensure_ascii=False, indent=1), temperature=0.1)
        results = {int(r.get("i", -1)): r for r in rev.get("results") or [] if isinstance(r, dict)}
    except Exception as exc:  # noqa: BLE001
        log.warning("Test tekshiruvi ishlamadi: %s", exc)
        rejected += [f"{short(q)}: tekshirilmadi" for q in cands]
        return []
    checked: list[dict] = []
    for i, q in enumerate(cands):
        r = results.get(i)
        if r is None:
            rejected.append(f"{short(q)}: tekshirilmadi")
            continue
        try:
            score = int(r.get("score") or 0)
        except (TypeError, ValueError):
            score = 0
        if r.get("ok") and score >= MIN_SCORE:
            checked.append(q)
            continue
        fixed = clean_question(r.get("fixed"), q["kind"]) if r.get("fixed") else None
        if fixed and not problems(fixed, PREFIX_LEN):
            fixed["key"] = fixed["key"] or q["key"]
            checked.append(fixed)       # tuzatilgan savol ham yechuvchidan o'tishi shart
        else:
            rejected.append(f"{short(q)}: {r.get('problem') or f'baho {score}/10'}")
    if not checked:
        return []

    # C) mustaqil yechuvchi: javobni bilmagan holda yechadi, mos kelmasa — tashlanadi
    shuffled = [list(rng.sample(q["options"], len(q["options"]))) for q in checked]
    try:
        sol, _ = await gemini.generate_json(
            SOLVER_SYSTEM, "Questions:\n" + json.dumps(
                [{"i": i, "question": q["question"], "options": shuffled[i]} for i, q in enumerate(checked)],
                ensure_ascii=False, indent=1), temperature=0.0)
        answers = {int(a.get("i", -1)): a for a in sol.get("answers") or [] if isinstance(a, dict)}
    except Exception as exc:  # noqa: BLE001
        log.warning("Yechuvchi ishlamadi: %s", exc)
        rejected += [f"{short(q)}: yechuvchi tekshirmadi" for q in checked]
        return []
    out = []
    for i, q in enumerate(checked):
        a = answers.get(i) or {}
        if a.get("ambiguous"):
            rejected.append(f"{short(q)}: noaniq ({a.get('reason') or 'bir nechta javob'})")
        elif cap.norm_item(str(a.get("choice") or "")) != cap.norm_item(q["correct"]):
            rejected.append(f"{short(q)}: yechuvchi boshqa javob tanladi ({a.get('choice')})")
        else:
            out.append(q)
    log.info("Tekshiruv: %s/%s savol o'tdi", len(out), len(cands))
    return out


def turkish_part(question: str) -> str | None:
    """Savolning turkcha qismi (ko'rsatmadan keyingi qatorlar) — o'zbekcha tahrirda o'zgarmasligi shart.
    Bir qatorli savolda ajratib bo'lmaydi → None (savol matni tahrirlanmaydi, faqat izoh)."""
    parts = question.split("\n", 1)
    return parts[1].strip() if len(parts) == 2 else None


# ------------------------------------------------------------------ kirish posti
def intro_caption(s: Settings, qs: QuizSet, rng: random.Random) -> str:
    qc = quiz_cfg(s)
    ng = sum(q["kind"] == GRAMMAR for q in qs.questions)
    nv = sum(q["kind"] == VOCAB for q in qs.questions)
    def e(x: str) -> str:
        return html.escape(x, quote=False)
    lines = [f"🧠 <b>[{qs.level}] KUNLIK TEST — {len(qs.questions)} ta savol</b>", "",
             e(rng.choice(OPENERS)), "",
             f"📘 <b>{ng} ta grammatika</b>" + (f" — {e(qs.grammar_focus)}" if qs.grammar_focus else ""),
             f"📗 <b>{nv} ta kelime bilgisi</b>" + (f" — {e(qs.vocab_theme)}" if qs.vocab_theme else ""),
             "",
             "✍️ Javobni belgilang: to'g'ri javob darhol ko'rinadi, xato bo'lsa 💡 izohni o'qing.",
             "🏆 Nechta to'g'ri topdingiz? Natijangizni izohlarda yozing 👇",
             "", cap.build_footer(None, s.cfg["signature"], [qc["hashtag"], qs.level])]
    return "\n".join(lines)


def intro_image(s: Settings, qs: QuizSet, rng: random.Random) -> bytes:
    theme = rng.choice(list(graphics.THEMES))
    footer = rng.choice(graphics.FOOTERS)
    ctx = graphics.Ctx(
        title="Bugungi testlar", label="KUNLIK TEST", sublabel=f"{qs.level}  ·  TÜRKÇE",
        items=[f"{sum(q['kind'] == GRAMMAR for q in qs.questions)} ta grammatika",
               f"{sum(q['kind'] == VOCAB for q in qs.questions)} ta kelime bilgisi",
               "Javob va izoh bilan"],
        emojis=rng.choice([["🧠", "✏️", "🏆"], ["🎯", "📝", "⭐"], ["💡", "✅", "🏅"], ["🧩", "📚", "🥇"]]),
        scene=rng.choice(graphics.SCENES), lang="tr", seed=rng.randint(0, 2**31), t=graphics.THEMES[theme])
    img = graphics.LAYOUTS["quiz"](ctx)
    b = io.BytesIO()
    img.save(b, "PNG")
    cfg = s.cfg
    return illustrator.compose(
        b.getvalue(), logo_path=ROOT / "assets" / "logo_white.png", theme=theme, footer=footer,
        label="KUNLIK TEST", sublabel=f"{qs.level}  ·  TÜRKÇE", band=int(cfg["brand"].get("band_height", 150)))


# ------------------------------------------------------------------ admin uchun ko'rinish
def preview_chunks(qs: QuizSet, limit: int = 3800) -> list[str]:
    def e(x: str) -> str:
        return html.escape(x, quote=False)
    blocks = []
    total = len(qs.questions)
    for i, q in enumerate(qs.questions, 1):
        opts = []
        for j, o in enumerate(poll_options(q)):
            mark = " ✅" if j == q["correct_index"] else ""
            opts.append(f"{e(o)}{mark}")
        blocks.append(f"<b>{i}/{total} · {KIND_LABEL[q['kind']]}</b>\n{e(q['question'])}\n"
                      + "\n".join(opts) + f"\n<i>{e(q['explanation'])}</i>")
    chunks, cur = [], ""
    for b in blocks:
        if cur and len(cur) + len(b) + 2 > limit:
            chunks.append(cur)
            cur = ""
        cur = f"{cur}\n\n{b}" if cur else b
    if cur:
        chunks.append(cur)
    return chunks
