"""Sifat nazorati tsikli: uzun matn → qayta yozish; QA 'fix' → tuzatilgan matn qabul qilinadi."""
import asyncio
from datetime import datetime, timezone

from enturk.db import DB
from enturk.mock import SAMPLE_BODY, FakeEleven, FakeGemini
from enturk.pipeline import Pipeline
from enturk.settings import load_settings


class ScriptedGemini(FakeGemini):
    def __init__(self):
        super().__init__()
        self.writer_calls = 0
        self.qa_calls = 0

    async def generate_json(self, system, prompt, **kw):
        if "WRITER agent" in system:
            self.writer_calls += 1
            data, src = await super().generate_json(system, prompt, **kw)
            if self.writer_calls == 1:
                data["caption_html"] += "\n" + ("Juda uzun matn. " * 80)   # limitdan oshadi
            return data, src
        if "QUALITY CONTROL" in system:
            self.qa_calls += 1
            fixed = SAMPLE_BODY.format(level="A1").replace("Tencere ocakta.", "Tencere ocağın üstünde.")
            return {"verdict": "fix", "issues": ["more natural example"], "caption_html": fixed,
                    "audio": None, "score": 8}, []
        return await super().generate_json(system, prompt, **kw)


def test_revision_loop(tmp_path):
    s = load_settings()
    s.data_dir = tmp_path
    for k in s.cfg["elevenlabs"]["voices"]:
        s.cfg["elevenlabs"]["voices"][k] = f"mock-{k.split('_')[1]}"
    g = ScriptedGemini()
    p = Pipeline(s, DB(tmp_path / "p.db"), g, FakeEleven())
    r = asyncio.run(p.run("yangi_sozlar", now=datetime.now(timezone.utc)))
    assert g.writer_calls == 2          # 1-marta uzun → validator qaytardi → qayta yozildi
    assert g.qa_calls == 1
    assert "ocağın üstünde" in r.caption_html   # QA tuzatishi qabul qilindi
    assert r.caption_html.rstrip().endswith("#yangi_sozlar #" + r.level)
    assert r.image[:2] == b"\xff\xd8" and len(r.audio) > 1000
