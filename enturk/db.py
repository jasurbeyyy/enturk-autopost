"""SQLite: postlar tarixi (takrorlanmaslik uchun) va qoralamalar holati."""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS drafts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slot_at TEXT NOT NULL,            -- rejalashtirilgan chiqish vaqti (ISO, UTC)
    post_type TEXT NOT NULL,
    lang TEXT NOT NULL,
    level TEXT,
    style_id TEXT,
    topic TEXT,
    title TEXT,
    caption TEXT,
    image_path TEXT,
    audio_path TEXT,
    audio_title TEXT,
    items_json TEXT DEFAULT '[]',
    sources_json TEXT DEFAULT '[]',
    qa_json TEXT DEFAULT '{}',
    status TEXT NOT NULL,             -- generating|ready|previewed|publishing|published|cancelled|failed|expired
    publish_at TEXT,
    control_chat_id INTEGER,
    control_msg_id INTEGER,
    is_test INTEGER DEFAULT 0,
    parent_id INTEGER,
    error TEXT,
    created_at TEXT NOT NULL,
    published_at TEXT,
    channel_msg_id INTEGER
);
CREATE INDEX IF NOT EXISTS idx_drafts_status ON drafts(status);
CREATE INDEX IF NOT EXISTS idx_drafts_type ON drafts(post_type);
CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT);
"""

LIVE_STATUSES = ("ready", "previewed", "publishing", "published")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        raise ValueError("naive datetime")
    return dt.astimezone(timezone.utc).isoformat()


def parse_iso(s: str | None) -> datetime | None:
    return datetime.fromisoformat(s) if s else None


class DB:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    # ---------- umumiy ----------
    def _exec(self, sql: str, args: tuple = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self.conn.execute(sql, args)
            self.conn.commit()
            return cur

    def _rows(self, sql: str, args: tuple = ()) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self.conn.execute(sql, args).fetchall()]

    # ---------- kv ----------
    def get_kv(self, k: str, default: str | None = None) -> str | None:
        rows = self._rows("SELECT v FROM kv WHERE k=?", (k,))
        return rows[0]["v"] if rows else default

    def set_kv(self, k: str, v: str) -> None:
        self._exec("INSERT INTO kv(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, v))

    # ---------- drafts ----------
    def create_draft(self, *, slot_at: datetime, post_type: str, lang: str,
                     is_test: bool = False, parent_id: int | None = None) -> int:
        cur = self._exec(
            "INSERT INTO drafts(slot_at, post_type, lang, status, is_test, parent_id, created_at) "
            "VALUES(?,?,?,?,?,?,?)",
            (iso(slot_at), post_type, lang, "generating", int(is_test), parent_id, iso(_now())),
        )
        return int(cur.lastrowid)

    def update(self, draft_id: int, **fields: Any) -> None:
        if not fields:
            return
        for k in ("items", "sources", "qa"):
            if k in fields:
                fields[f"{k}_json"] = json.dumps(fields.pop(k), ensure_ascii=False)
        for k, v in list(fields.items()):
            if isinstance(v, datetime):
                fields[k] = iso(v)
        cols = ", ".join(f"{k}=?" for k in fields)
        self._exec(f"UPDATE drafts SET {cols} WHERE id=?", (*fields.values(), draft_id))

    def get(self, draft_id: int) -> dict | None:
        rows = self._rows("SELECT * FROM drafts WHERE id=?", (draft_id,))
        return rows[0] if rows else None

    def set_status_if(self, draft_id: int, expected: tuple[str, ...], new: str) -> bool:
        """Holatni faqat kutilgan holatda bo'lsa o'zgartiradi (ikki marta chiqarishning oldini oladi)."""
        marks = ",".join("?" * len(expected))
        cur = self._exec(
            f"UPDATE drafts SET status=? WHERE id=? AND status IN ({marks})",
            (new, draft_id, *expected),
        )
        return cur.rowcount == 1

    def by_status(self, *statuses: str) -> list[dict]:
        marks = ",".join("?" * len(statuses))
        return self._rows(f"SELECT * FROM drafts WHERE status IN ({marks}) ORDER BY id", statuses)

    def active_for_slot(self, slot_at: datetime) -> list[dict]:
        return self._rows(
            "SELECT * FROM drafts WHERE slot_at=? AND is_test=0 AND status IN "
            "('generating','ready','previewed','publishing','published')",
            (iso(slot_at),),
        )

    def for_slot(self, slot_at: datetime) -> list[dict]:
        return self._rows("SELECT * FROM drafts WHERE slot_at=? AND is_test=0 ORDER BY id", (iso(slot_at),))

    # ---------- tarix (agentlar uchun) ----------
    def recent(self, *, days: int, post_type: str | None = None, lang: str | None = None,
               include_tests: bool = False) -> list[dict]:
        since = iso(_now() - timedelta(days=days))
        sql = f"SELECT * FROM drafts WHERE created_at>=? AND status IN {LIVE_STATUSES}"
        args: list[Any] = [since]
        if post_type:
            sql += " AND post_type=?"
            args.append(post_type)
        if lang:
            sql += " AND lang=?"
            args.append(lang)
        if not include_tests:
            sql += " AND (is_test=0 OR status='published')"
        sql += " ORDER BY id DESC"
        rows = self._rows(sql, tuple(args))
        for r in rows:
            r["items"] = json.loads(r.get("items_json") or "[]")
        return rows
