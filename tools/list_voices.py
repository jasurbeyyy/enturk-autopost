"""ElevenLabs'dagi ovozlaringiz ro'yxati — config.yaml uchun voice_id topish.

  python tools/list_voices.py

Eslatma: Voice Library'dagi ovozni ishlatish uchun avval uni elevenlabs.io saytida
"Add to My Voices" orqali o'z ro'yxatingizga qo'shing, keyin shu skriptni ishga tushiring.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from enturk.eleven import ElevenClient  # noqa: E402
from enturk.settings import load_settings  # noqa: E402


async def main() -> None:
    s = load_settings()
    e = ElevenClient(s.eleven_key, s.cfg["elevenlabs"]["model_id"])
    try:
        voices = await e.list_voices()
    finally:
        await e.aclose()
    print(f"{'NOMI':28} {'VOICE_ID':24} TAVSIF")
    for v in voices:
        lab = v.get("labels") or {}
        desc = ", ".join(str(x) for x in (lab.get("gender"), lab.get("accent"), lab.get("language"),
                                          lab.get("age"), lab.get("use_case")) if x)
        print(f"{v.get('name', '')[:27]:28} {v.get('voice_id', ''):24} {desc}")


if __name__ == "__main__":
    asyncio.run(main())
