"""5-agent: Sifat nazorati — grammatika, tarjima, faktlar, format va audio skriptni tekshiradi."""
from __future__ import annotations

import json

from ..gemini import GeminiClient

SYSTEM = """You are the QUALITY CONTROL agent: a meticulous native-level Turkish editor, an experienced English
editor and an Uzbek (Latin script) proofreader. You review a Telegram post for @EnTurk_CSR before it is published.

Check:
1. Target language: grammar, spelling, Turkish letters (ı/i, ş, ç, ğ, ö, ü, â), vowel harmony in suffixes,
   natural modern usage. For English posts: correct, natural English.
2. Uzbek: accurate and natural translations; correct Latin spelling (o', g', sh, ch, ng); no Cyrillic.
3. Facts: every factual claim must be correct, especially about exams (format, sections, scores, dates, fees).
   {search_note}
4. Level: content matches the stated CEFR level.
5. Format: valid Telegram HTML (only b, i, u, s, tg-spoiler, code, blockquote), first line is a bold title with
   the level tag, no hashtags or channel signature inside the body, clean layout.
6. Audio script: only target-language text, matches the post, correct speaker assignment, no Uzbek, no emojis.
7. Answers hidden in spoilers are correct.
8. Nothing offensive, political, religiously sensitive or unsuitable for students of any age.

Verdict:
- "pass": publishable as is.
- "fix": only small problems — you MUST return the COMPLETE corrected "caption_html" and/or "audio" (not a diff).
  Keep the style, the structure and the length (visible text at most {body_limit} characters).
- "fail": serious problems (facts you cannot confidently fix, off-topic, many errors, weak quality).
Be strict about correctness; do not nitpick matters of taste.

Output exactly one JSON object:
{{"verdict": "pass|fix|fail", "issues": ["..."], "caption_html": "... or null", "audio": [...] or null, "score": 1-10}}"""

TEMPLATE = """Post type: {type_title}. Target language: {lang}. Level: {level}.
{exam_line}
Items already taught in recent posts (flag repeats of more than two): {recent_items}

POST BODY (Telegram HTML):
{caption}

AUDIO SCRIPT:
{audio}

TAUGHT ITEMS: {items}"""

IMAGE_SYSTEM = """You check illustrations for an educational Telegram channel. Answer with one JSON object only."""
IMAGE_PROMPT = """This illustration is for a post about: "{topic}". Intended scene: "{brief}".
Return JSON: {{"has_text": true/false (any letters, words, numbers or pseudo-text visible anywhere),
"on_topic": true/false, "appropriate": true/false (suitable for students, no disturbing content),
"problems": "short description or empty"}}"""


async def review(gemini: GeminiClient, *, draft: dict, type_title: str, lang: str, level: str,
                 body_limit: int, recent_items: list[str], exam: str | None = None) -> dict:
    factual = exam is not None
    system = SYSTEM.format(
        body_limit=body_limit,
        search_note="Use Google Search to verify exam facts against official sources."
        if factual else "Language facts must match standard dictionaries and grammar.",
    )
    prompt = TEMPLATE.format(
        type_title=type_title, lang=lang, level=level,
        exam_line=f"Exam: {exam}" if exam else "",
        recent_items=", ".join(recent_items[:150]) or "(none)",
        caption=draft["caption_html"],
        audio=json.dumps(draft.get("audio", []), ensure_ascii=False, indent=1),
        items=", ".join(draft.get("items", [])),
    )
    data, _ = await gemini.generate_json(system, prompt, search=factual, temperature=0.2)
    verdict = str(data.get("verdict", "fail")).lower().strip()
    if verdict not in ("pass", "fix", "fail"):
        verdict = "fail"
    data["verdict"] = verdict
    data["issues"] = [str(i) for i in data.get("issues") or []]
    return data


async def check_image(gemini: GeminiClient, image_jpeg: bytes, *, topic: str, brief: str) -> dict:
    data, _ = await gemini.generate_json(
        IMAGE_SYSTEM, IMAGE_PROMPT.format(topic=topic, brief=brief),
        images=[image_jpeg], temperature=0.0)
    return data
