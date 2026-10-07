"""Agentlar zanjiri: tadqiqot → yozish → sifat nazorati → rasm + audio."""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime

from . import caption as cap
from . import planner
from .agents import illustrator, qa, research, voice, writer
from .db import DB
from .eleven import ElevenClient
from .gemini import GeminiClient
from .settings import ROOT, Settings

log = logging.getLogger(__name__)

STRICT_DEDUPE_TYPES = {"yangi_sozlar", "mavzuli_lugat", "en_sozlar", "kunlik_iboralar", "en_iboralar"}
MAX_REVISIONS = 3
MAX_TOPICS = 2


class PipelineError(RuntimeError):
    pass


@dataclass
class PostResult:
    post_type: str
    lang: str
    level: str
    style_id: str
    topic: str
    title: str
    caption_html: str          # imzo va xeshteglar bilan tayyor matn
    image: bytes
    audio: bytes
    audio_title: str
    items: list[str]
    sources: list[str]
    qa: dict = field(default_factory=dict)


class Pipeline:
    def __init__(self, s: Settings, db: DB, gemini: GeminiClient, eleven: ElevenClient):
        self.s, self.db, self.gemini, self.eleven = s, db, gemini, eleven

    # ---------- kontekst ----------
    def _context(self, type_key: str, lang: str) -> dict:
        same_type = self.db.recent(days=45, post_type=type_key)
        same_lang = self.db.recent(days=75, lang=lang)
        recent_items: list[str] = []
        for r in same_lang:
            recent_items.extend(r["items"])
        week = self.db.recent(days=7, lang=lang)
        week_items: list[str] = []
        for r in week:
            if r["post_type"] != "haftalik_takrorlash":
                week_items.extend(r["items"])
        exams = []
        for r in same_type:
            try:
                ex = json.loads(r.get("qa_json") or "{}").get("exam")
            except json.JSONDecodeError:
                ex = None
            if ex:
                exams.append(ex)
        return {
            "recent_topics": [r["topic"] for r in same_type if r.get("topic")],
            "recent_levels": [r["level"] for r in same_type if r.get("level")],
            "recent_styles": [r["style_id"] for r in same_type if r.get("style_id")],
            "recent_exams": exams,
            "recent_items": recent_items,
            "recent_items_norm": {cap.norm_item(i) for i in recent_items},
            "week_items": week_items[:120],
            **self._recent_visuals(),
        }

    def _recent_visuals(self) -> dict:
        """Kanaldagi oxirgi postlarning maketi va sahnasi (ketma-ket takrorlamaslik uchun)."""
        layouts, scenes = [], []
        for r in self.db.recent(days=14):
            try:
                q = json.loads(r.get("qa_json") or "{}")
            except json.JSONDecodeError:
                q = {}
            layouts.append(q.get("layout"))
            scenes.append(q.get("scene"))
        return {"recent_layouts": layouts, "recent_scenes": scenes}

    # ---------- asosiy ----------
    async def run(self, type_key: str, *, now: datetime, avoid_topics: list[str] | None = None,
                  exclude_style: str | None = None) -> PostResult:
        s = self.s
        pt = s.post_type(type_key)
        lang = pt.get("lang", "tr")
        ctx = self._context(type_key, lang)
        level = planner.pick_least_used(pt["levels"], ctx["recent_levels"])
        style = planner.pick_style(s.styles, type_key, ctx["recent_styles"], exclude=exclude_style)
        exam = planner.pick_least_used(pt["exams"], ctx["recent_exams"]) if pt.get("exams") else None
        footer = cap.build_footer(pt.get("audio_line") if s.audio_enabled else None, s.cfg["signature"],
                                  [pt.get("hashtag", type_key), level])
        _, footer_text = cap.sanitize(footer)
        body_limit = cap.CAPTION_LIMIT - cap.visible_len(footer_text) - 30
        avoid = list(avoid_topics or [])
        log.info("Post: %s | daraja %s | uslub %s | imtihon %s", type_key, level, style["id"], exam)

        last_issues: list[str] = []
        for topic_try in range(MAX_TOPICS):
            if type_key == "haftalik_takrorlash" and ctx["week_items"]:
                res = {"topic": "Haftalik takrorlash", "angle": "review of this week's posts",
                       "material": ctx["week_items"], "facts": [],
                       "image_idea": "a student happily reviewing flashcards with Turkish tea on the desk",
                       "sources": []}
            else:
                res = await research.research(
                    self.gemini, now=now.astimezone(s.tz), post_type=pt, type_key=type_key, lang=lang,
                    level=level, exam=exam, recent_topics=ctx["recent_topics"], avoid_topics=avoid)
            log.info("1-agent mavzu: %s", res.get("topic"))

            draft = await writer.write(
                self.gemini, post_type=pt, type_key=type_key, lang=lang, level=level, style=style,
                research=res, avoid_items=ctx["recent_items"], body_limit=body_limit, exam=exam,
                week_items=ctx["week_items"] if type_key == "haftalik_takrorlash" else None)

            qa_result: dict = {}
            approved = False
            for rev in range(MAX_REVISIONS + 1):
                draft["caption_html"] = cap.strip_footer_like(draft["caption_html"])
                body_html, body_text = cap.sanitize(draft["caption_html"])
                draft["caption_html"] = body_html
                issues = cap.code_checks(
                    body_html=body_html, body_text=body_text, footer_text=footer_text, level=level,
                    audio=draft["audio"], items=draft["items"], recent_items=ctx["recent_items_norm"],
                    strict_dedupe=type_key in STRICT_DEDUPE_TYPES, has_levels=True)
                if not issues:
                    qa_result = await qa.review(
                        self.gemini, draft=draft, type_title=pt["title"], lang=lang, level=level,
                        body_limit=body_limit, recent_items=ctx["recent_items"], exam=exam)
                    log.info("5-agent: %s %s", qa_result["verdict"], qa_result["issues"])
                    if qa_result["verdict"] == "pass":
                        approved = True
                        break
                    if qa_result["verdict"] == "fix" and not (qa_result.get("caption_html")
                                                              or qa_result.get("audio")):
                        qa_result["verdict"] = "fail"   # tuzatish qaytarilmagan → yozuvchi tuzatadi
                    if qa_result["verdict"] == "fix":
                        fixed = dict(draft)
                        if qa_result.get("caption_html"):
                            fixed["caption_html"] = cap.strip_footer_like(qa_result["caption_html"])
                        if isinstance(qa_result.get("audio"), list) and qa_result["audio"]:
                            fixed["audio"] = writer._normalize(
                                {"caption_html": "x", "audio": qa_result["audio"]})["audio"]
                        fb_html, fb_text = cap.sanitize(fixed["caption_html"])
                        fixed["caption_html"] = fb_html
                        fix_issues = cap.code_checks(
                            body_html=fb_html, body_text=fb_text, footer_text=footer_text, level=level,
                            audio=fixed["audio"], items=fixed["items"],
                            recent_items=ctx["recent_items_norm"],
                            strict_dedupe=type_key in STRICT_DEDUPE_TYPES, has_levels=True)
                        if not fix_issues:
                            draft = fixed
                            approved = True
                            break
                        issues = qa_result["issues"] + fix_issues
                    else:
                        issues = qa_result["issues"] or ["quality too low, rewrite"]
                last_issues = issues
                if rev == MAX_REVISIONS:
                    break
                log.info("2-agent qayta yozadi (%s): %s", rev + 1, issues)
                draft = await writer.revise(self.gemini, draft=draft, issues=issues, lang=lang,
                                            narrator=pt.get("narrator", "female"),
                                            body_limit=body_limit)
            if approved:
                break
            avoid.append(str(res.get("topic")))
            log.warning("Mavzu rad etildi, boshqa mavzu olinadi: %s", last_issues)
        else:
            raise PipelineError("Sifat nazoratidan o'tmadi: " + "; ".join(last_issues[:5]))

        full_caption = draft["caption_html"].rstrip() + "\n\n" + footer
        label = pt["title"].upper()
        sublabel = f"{level}  ·  {'ENGLISH' if lang == 'en' else 'TÜRKÇE'}"

        image_task = illustrator.illustrate(
            self.gemini, cfg=s.cfg, root=ROOT, lang=lang,
            brief=draft.get("image_brief") or res.get("image_idea", ""),
            topic=draft.get("title") or draft.get("topic") or res.get("topic", ""), label=label,
            sublabel=sublabel, items=draft.get("items"), post_type=type_key, style_id=style["id"],
            visual=draft.get("visual"), lines=draft.get("audio"),
            recent_layouts=ctx["recent_layouts"], recent_scenes=ctx["recent_scenes"])
        if s.audio_enabled:
            audio_task = voice.synthesize(
                self.eleven, lines=draft["audio"], voices=s.cfg["elevenlabs"]["voices"], lang=lang,
                pause_ms=int(s.cfg["elevenlabs"].get("pause_ms", 650)))
            (image, visual_meta), audio = await asyncio.gather(image_task, audio_task)
        else:
            (image, visual_meta), audio = await image_task, b""

        qa_meta = {"verdict": qa_result.get("verdict"), "score": qa_result.get("score"),
                   "issues": qa_result.get("issues", []), "exam": exam,
                   "layout": visual_meta.get("layout"), "scene": visual_meta.get("scene")}
        return PostResult(
            post_type=type_key, lang=lang, level=level, style_id=style["id"],
            topic=str(draft.get("topic") or res.get("topic")), title=str(draft.get("title", "")),
            caption_html=full_caption, image=image, audio=audio,
            audio_title=str(draft.get("audio_title") or draft.get("title") or pt["title"]),
            items=draft["items"], sources=res.get("sources", []), qa=qa_meta)
