"""2-agent: Yozuvchi — topilgan material asosida tanlangan uslubda post yozadi."""
from __future__ import annotations

import json

from ..gemini import GeminiClient

SYSTEM = """You are the WRITER agent — a creative, experienced Turkish/English teacher and copywriter — for the
Telegram channel @EnTurk_CSR, which teaches Turkish (and some English) to Uzbek speakers.

LANGUAGE RULES
- Explanations, titles and translations: Uzbek in the LATIN script, using the apostrophe for o', g' and the
  tutuq belgisi (so'z, g'oya, ma'no). Never use Cyrillic.
- Target-language examples: natural, modern, 100% correct Standard Turkish (İstanbul Türkçesi) with the right
  letters ç ş ğ ı İ ö ü â — or natural modern English for English posts.
- Everything must fit the given CEFR level. Uzbek translations must be accurate and natural.

FORMAT RULES (Telegram HTML)
- Allowed tags only: <b>, <i>, <u>, <s>, <tg-spoiler>, <code>, <blockquote>. No <br>, no <p>, no Markdown.
  Use real line breaks. Escape the characters & < > in text.
- First line: an emoji + a bold title that contains the level tag, e.g. "🍳 <b>[A1] OSHXONADA — 10 ta yangi so'z</b>".
- Clean, airy layout: empty lines between blocks, purposeful emojis (not on every word).
- Do NOT add the channel signature, hashtags or a line about the audio — the system adds them.
- HARD LIMIT: visible text (without tags) at most {body_limit} characters (an emoji counts as 2).
  Aim for about {target} characters.

STYLE
- Follow the given style's instructions. Its example shows only the SHAPE: never copy its words or topic.
- Be fresh and specific, avoid generic textbook sentences. Engage the reader where the style allows.

AUDIO SCRIPT
- "audio" = lines read aloud by text-to-speech: ONLY the {lang_name} parts of the post (never Uzbek), in the order
  they appear. Plain text: no emojis, tags, brackets or numbering. Total under 1000 characters.
- "speaker" is "female" or "male". Dialogues: 👩/female speaker → "female", 👨/male speaker → "male".
  Other posts: use "{narrator}" for every line.

OUTPUT: exactly one JSON object:
{{"title": "plain title without the level tag",
  "topic": "short topic in Uzbek",
  "caption_html": "the post body",
  "audio": [{{"speaker": "female", "text": "..."}}],
  "audio_title": "short title for the audio file in Uzbek",
  "items": ["every taught target-language word / phrase exactly as written in the post"],
  "image_brief": "one concrete English description of an illustration scene for this post (people, objects, setting). No text in the image.",
  "visual": {{"emojis": ["3-5 single emoji that clearly depict the CONCRETE objects, places or actions of THIS topic, most typical first (barber → 💈 ✂️ 💇; bank → 🏦 💳 💸; courier → 📦 🚚 🚪). Avoid generic ones like 📚 ✏️ unless the topic is about studying."],
             "scene": "background scene that fits the topic best — Turkish posts: skyline (Istanbul mosques, general city life), bosphorus (sea, travel, transport, bridge), balloons (Cappadocia, holidays, nature, adventure), tulips (spring, flowers, feelings, family, health), tea (food, café, home, shopping, guests); English posts: london"}}}}"""

TEMPLATE = """Write the next post.

Post type: {type_title}
Requirements:
{requirements}

Target language: {lang_name}. Level: {level}.
{exam_line}
STYLE TO USE: "{style_name}"
Style instructions: {style_instructions}
{style_example}
RESEARCH MATERIAL (from the research agent):
{research}

Do NOT teach these again (already taught recently): {avoid_items}
{week_items}"""

REVISE = """Your previous draft (JSON):
{draft}

Problems found by the validator / editor:
{issues}

Return the COMPLETE corrected JSON in the same format. Fix every problem, keep what was good."""

LANG_NAMES = {"tr": "Turkish", "en": "English"}


def _system(lang: str, narrator: str, body_limit: int) -> str:
    return SYSTEM.format(body_limit=body_limit, target=max(body_limit - 150, 500),
                         lang_name=LANG_NAMES.get(lang, lang),
                         narrator=narrator if narrator in ("female", "male") else "female")


async def write(gemini: GeminiClient, *, post_type: dict, type_key: str, lang: str, level: str,
                style: dict, research: dict, avoid_items: list[str], body_limit: int,
                exam: str | None = None, week_items: list[str] | None = None) -> dict:
    example = style.get("example")
    prompt = TEMPLATE.format(
        type_title=f"{post_type['title']} ({type_key})",
        requirements=post_type.get("requirements", "").strip(),
        lang_name=LANG_NAMES.get(lang, lang),
        level=level,
        exam_line=f"Exam: {exam}\n" if exam else "",
        style_name=style["name"],
        style_instructions=style["instructions"].strip(),
        style_example=f"Shape example (do not copy content):\n{example}\n" if example else "",
        research=json.dumps({k: v for k, v in research.items() if k != "sources"},
                            ensure_ascii=False, indent=1),
        avoid_items=", ".join(avoid_items[:150]) or "(none)",
        week_items=("\nITEMS TAUGHT THIS WEEK (build the review ONLY from these):\n" + ", ".join(week_items))
        if week_items else "",
    )
    data, _ = await gemini.generate_json(
        _system(lang, post_type.get("narrator", "female"), body_limit), prompt, temperature=0.9)
    return _normalize(data)


async def revise(gemini: GeminiClient, *, draft: dict, issues: list[str], lang: str,
                 narrator: str, body_limit: int) -> dict:
    prompt = REVISE.format(draft=json.dumps(draft, ensure_ascii=False, indent=1),
                           issues="\n".join(f"- {i}" for i in issues))
    data, _ = await gemini.generate_json(_system(lang, narrator, body_limit), prompt, temperature=0.5)
    return _normalize(data)


def _normalize(data: dict) -> dict:
    if not isinstance(data, dict) or not data.get("caption_html"):
        raise ValueError("Yozuvchi javobida caption_html yo'q")
    audio = []
    for a in data.get("audio") or []:
        if isinstance(a, str):
            a = {"speaker": "female", "text": a}
        sp = str(a.get("speaker", "female")).lower()
        audio.append({"speaker": sp if sp in ("female", "male") else "female",
                      "text": str(a.get("text", "")).strip()})
    data["audio"] = audio
    data["items"] = [str(i).strip() for i in data.get("items") or [] if str(i).strip()]
    data.setdefault("title", data.get("topic", ""))
    data.setdefault("audio_title", data.get("title", ""))
    data.setdefault("image_brief", "")
    vis = data.get("visual") if isinstance(data.get("visual"), dict) else {}
    emojis = vis.get("emojis") if isinstance(vis.get("emojis"), list) else []
    data["visual"] = {"emojis": [str(e).strip() for e in emojis if str(e).strip()][:6],
                      "scene": str(vis.get("scene") or "").strip().lower()}
    return data
