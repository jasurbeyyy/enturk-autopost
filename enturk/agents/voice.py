"""4-agent: Diktor — ElevenLabs orqali audio yaratadi (diologda ikki ovoz)."""
from __future__ import annotations

import asyncio
import io
import logging
import re

from pydub import AudioSegment

from ..eleven import ElevenClient

log = logging.getLogger(__name__)
EMOJI = re.compile(r"[\U0001F000-\U0001FAFF☀-➿️]")


def clean_line(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text)
    text = EMOJI.sub("", text)
    text = text.replace("›", "").replace("→", ",")
    return re.sub(r"\s+", " ", text).strip(" -–—•")


def voice_for(voices: dict, lang: str, speaker: str) -> str:
    key = f"{lang}_{speaker}"
    vid = voices.get(key) or voices.get(f"{lang}_female")
    if not vid or vid.startswith("PUT_"):
        raise ValueError(f"config.yaml → elevenlabs.voices.{key} ovoz ID'si kiritilmagan")
    return vid


def concat(chunks: list[bytes], pause_ms: int) -> bytes:
    out = AudioSegment.silent(duration=250)
    gap = AudioSegment.silent(duration=pause_ms)
    for c in chunks:
        out += AudioSegment.from_file(io.BytesIO(c), format="mp3") + gap
    buf = io.BytesIO()
    out.export(buf, format="mp3", bitrate="128k")
    return buf.getvalue()


async def synthesize(eleven: ElevenClient, *, lines: list[dict], voices: dict, lang: str,
                     pause_ms: int = 650, concurrency: int = 3) -> bytes:
    sem = asyncio.Semaphore(concurrency)
    jobs = []
    for line in lines:
        text = clean_line(line.get("text", ""))
        if not text:
            continue
        vid = voice_for(voices, lang, line.get("speaker", "female"))

        async def one(text: str = text, vid: str = vid) -> bytes:
            async with sem:
                return await eleven.tts(text, vid, language_code=lang)
        jobs.append(one())
    if not jobs:
        raise ValueError("Audio uchun matn yo'q")
    chunks = await asyncio.gather(*jobs)
    return await asyncio.to_thread(concat, list(chunks), pause_ms)
