"""1-agent: Tadqiqotchi — rubrika bo'yicha internetdan yangi mavzu va xom material topadi."""
from __future__ import annotations

import json
from datetime import datetime

from ..gemini import GeminiClient

SYSTEM = """You are the RESEARCH agent of an automated content team for the Telegram channel @EnTurk_CSR.
The channel teaches Turkish (and sometimes English) to Uzbek speakers. Posts explain in Uzbek (Latin script)
and give examples in the target language.

Your job: use Google Search to find ONE fresh, genuinely useful topic for the next post and collect accurate
raw material for the writer agent.

Principles:
- Prefer real-life, practical, current topics: what people really say in Türkiye today, seasonal / holiday /
  news hooks for the current date, real situations Uzbek learners face (studying, working, travelling,
  living in Türkiye, taking exams), real exam requirements.
- Verify language material against reliable sources (TDK Güncel Türkçe Sözlük, Yunus Emre Enstitüsü,
  university Turkish-teaching materials; Cambridge / Oxford dictionaries for English).
- For exam topics use only official or clearly reliable sources and give the URL next to every fact.
  Never invent dates, fees, scores or rules.
- Do not repeat the recent topics listed by the user; pick a clearly different theme.
- Output ONLY one JSON object, no extra text."""

TEMPLATE = """Today: {date} ({weekday}). Target language: {lang_name}. CEFR level: {level}.

Post type: {type_title}
Requirements for this post type:
{requirements}
{exam_line}
Recent topics of this post type (DO NOT repeat these themes):
{recent_topics}
{avoid_line}
Search the web and return JSON:
{{
  "topic": "short topic title in Uzbek (Latin)",
  "angle": "why this is useful / interesting now (1-2 sentences)",
  "material": ["10-15 candidate target-language words / phrases / example ideas with short glosses"],
  "facts": ["verified facts with source URL (mainly for exam posts; may be empty)"],
  "image_idea": "one concrete visual scene for an illustration, in English"
}}"""

LANG_NAMES = {"tr": "Turkish", "en": "English"}


async def research(gemini: GeminiClient, *, now: datetime, post_type: dict, type_key: str,
                   lang: str, level: str, exam: str | None, recent_topics: list[str],
                   avoid_topics: list[str]) -> dict:
    prompt = TEMPLATE.format(
        date=now.strftime("%Y-%m-%d"),
        weekday=now.strftime("%A"),
        lang_name=LANG_NAMES.get(lang, lang),
        level=level,
        type_title=f"{post_type['title']} ({type_key})",
        requirements=post_type.get("requirements", "").strip(),
        exam_line=f"\nExam to cover in this post: {exam}\n" if exam else "",
        recent_topics="\n".join(f"- {t}" for t in recent_topics[:30]) or "- (none yet)",
        avoid_line=("\nThe admin rejected these topics, choose something different:\n"
                    + "\n".join(f"- {t}" for t in avoid_topics)) if avoid_topics else "",
    )
    data, sources = await gemini.generate_json(SYSTEM, prompt, search=True, temperature=1.0)
    if not isinstance(data, dict) or not data.get("topic"):
        raise ValueError(f"Tadqiqot natijasi noto'g'ri: {json.dumps(data, ensure_ascii=False)[:300]}")
    data["sources"] = sources
    return data
