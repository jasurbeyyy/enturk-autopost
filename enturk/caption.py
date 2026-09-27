"""Telegram HTML matnini tozalash, uzunlikni o'lchash va kod darajasidagi tekshiruvlar."""
from __future__ import annotations

import re
from html import escape
from html.parser import HTMLParser

CAPTION_LIMIT = 1024          # Telegram: rasm ostidagi matn chegarasi
ALLOWED = {"b", "strong", "i", "em", "u", "ins", "s", "strike", "del",
           "tg-spoiler", "code", "pre", "blockquote", "a"}
CYRILLIC = re.compile(r"[Ѐ-ӿ]")
LEVEL_RE = re.compile(r"\[(?:A1|A2|B1|B2|C1|C2)(?:\s*[–-]\s*(?:A1|A2|B1|B2|C1|C2))?\]")


class _Sanitizer(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.text: list[str] = []
        self.stack: list[str] = []
        self.span_stack: list[bool] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag == "br":
            self.out.append("\n")
            self.text.append("\n")
            return
        if tag == "span":
            is_spoiler = any(k == "class" and v and "tg-spoiler" in v for k, v in attrs)
            self.span_stack.append(is_spoiler)
            if not is_spoiler:
                return
            tag = "tg-spoiler"
        if tag not in ALLOWED:
            return
        if tag == "strong":
            tag = "b"
        if tag == "em":
            tag = "i"
        attr = ""
        if tag == "a":
            href = dict(attrs).get("href")
            if not href:
                return
            attr = f' href="{escape(href, quote=True)}"'
        if tag == "blockquote" and any(k == "expandable" for k, _ in attrs):
            attr = " expandable"
        self.out.append(f"<{tag}{attr}>")
        self.stack.append(tag)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "p":
            self.out.append("\n")
            self.text.append("\n")
            return
        if tag == "span":
            if not self.span_stack or not self.span_stack.pop():
                return
            tag = "tg-spoiler"
        tag = {"strong": "b", "em": "i"}.get(tag, tag)
        if tag not in self.stack:
            return
        while self.stack:
            t = self.stack.pop()
            self.out.append(f"</{t}>")
            if t == tag:
                break

    def handle_data(self, data: str) -> None:
        self.out.append(escape(data, quote=False))
        self.text.append(data)

    def result(self) -> tuple[str, str]:
        while self.stack:
            self.out.append(f"</{self.stack.pop()}>")
        return "".join(self.out), "".join(self.text)


def _tidy(s: str) -> str:
    s = s.replace("\r\n", "\n")
    s = re.sub(r"[ \t]+\n", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def sanitize(html: str) -> tuple[str, str]:
    """(xavfsiz_html, ko'rinadigan_matn) qaytaradi."""
    p = _Sanitizer()
    p.feed(html or "")
    p.close()
    out, text = p.result()
    return _tidy(out), _tidy(text)


def visible_len(text: str) -> int:
    """Telegram uzunlikni UTF-16 birliklarida hisoblaydi (emoji = 2)."""
    return len(text.encode("utf-16-le")) // 2


def strip_footer_like(html: str) -> str:
    """Yozuvchi agent o'zi qo'shib yuborgan imzo/xeshteg qatorlarini olib tashlash."""
    keep = []
    for line in html.split("\n"):
        plain = re.sub(r"<[^>]+>", "", line).strip()
        if re.fullmatch(r"(#[\w']+\s*)+", plain):
            continue
        if "@EnTurk_CSR" in plain and len(plain) < 40:
            continue
        keep.append(line)
    return "\n".join(keep)


def build_footer(audio_line: str | None, signature: str, hashtags: list[str]) -> str:
    lines = []
    if audio_line:
        lines.append(audio_line)
    lines.append(signature)
    tags = " ".join("#" + re.sub(r"[^\w]", "", t) for t in hashtags if t)
    if tags:
        lines.append(tags)
    return "\n".join(escape(x, quote=False) for x in lines)


def norm_item(s: str) -> str:
    s = s.replace("İ", "i").replace("I", "ı").lower()
    s = re.sub(r"<[^>]+>", "", s)
    return s.strip(" .,!?:;\"'«»()—-")


def code_checks(*, body_html: str, body_text: str, footer_text: str, level: str | None,
                audio: list[dict], items: list[str], recent_items: set[str],
                strict_dedupe: bool, has_levels: bool) -> list[str]:
    """Qat'iy (dasturiy) tekshiruvlar. Bo'sh ro'yxat = hammasi joyida."""
    issues: list[str] = []
    total = visible_len(body_text) + 2 + visible_len(footer_text)
    if total > CAPTION_LIMIT:
        over = total - CAPTION_LIMIT
        issues.append(
            f"Too long: caption is {total} characters, limit is {CAPTION_LIMIT}. "
            f"Cut at least {over + 40} characters (shorter examples / fewer lines), keep the structure.")
    if visible_len(body_text) < 250:
        issues.append("Too short: the post body must be a complete, useful post (at least ~300 characters).")
    if CYRILLIC.search(body_text):
        issues.append("Uzbek must be written in the LATIN alphabet only; Cyrillic letters found.")
    first = body_text.split("\n", 1)[0]
    if has_levels and level and not LEVEL_RE.search(first):
        issues.append(f"The first line (title) must contain the level tag like [{level}].")
    if not audio:
        issues.append("audio script is empty")
    else:
        bad = [a for a in audio if not str(a.get("text", "")).strip()]
        if bad:
            issues.append("audio script contains empty lines")
        audio_chars = sum(len(str(a.get("text", ""))) for a in audio)
        if audio_chars > 1300:
            issues.append(f"audio script too long ({audio_chars} chars) — keep it under 1100 characters")
        if any(CYRILLIC.search(str(a.get("text", ""))) for a in audio):
            issues.append("audio script must not contain Cyrillic text")
    if not items:
        issues.append("items list (taught words/phrases) is empty")
    elif strict_dedupe:
        repeats = sorted({norm_item(i) for i in items} & recent_items)
        if len(repeats) > 2:
            issues.append("These items were already taught recently, replace them with new ones: "
                          + ", ".join(repeats))
    return issues
