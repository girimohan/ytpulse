"""SQLite store (WAL). Idempotent inserts, resumable cursors, salted author hashes."""
from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import pandas as pd

from .models import ChatMessage

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS messages(
  id TEXT PRIMARY KEY,
  video_id TEXT NOT NULL,
  source TEXT,
  ts TEXT NOT NULL,
  author TEXT NOT NULL,
  author_name TEXT,
  text TEXT NOT NULL,
  kind TEXT,
  amount TEXT,
  ingested_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_messages_video_ts ON messages(video_id, ts);
CREATE TABLE IF NOT EXISTS enriched(
  id TEXT PRIMARY KEY,
  clean TEXT,
  lang TEXT,
  key TEXT,
  flags TEXT,
  sentiment REAL,
  label TEXT,
  entities TEXT,
  hashtags TEXT,
  emojis TEXT,
  model TEXT,
  version INTEGER
);
CREATE TABLE IF NOT EXISTS cursors(
  video_id TEXT, name TEXT, value TEXT,
  PRIMARY KEY(video_id, name)
);
"""

ENRICH_VERSION = 1


class Store:
    """One instance per thread (SQLite connections are not shared across threads)."""

    def __init__(self, path: str, store_names: bool = False):
        self.path = path
        self.store_names = store_names
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path, timeout=30)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.executescript(SCHEMA)
        self._salt = self._get_or_create_salt()

    # ---- meta / cursors -------------------------------------------------
    def get_meta(self, key: str, default: str | None = None) -> str | None:
        r = self.conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return r["value"] if r else default

    def set_meta(self, key: str, value: str) -> None:
        with self.conn:
            self.conn.execute("INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)", (key, value))

    def _get_or_create_salt(self) -> str:
        salt = self.get_meta("author_salt")
        if not salt:
            salt = secrets.token_hex(16)
            self.set_meta("author_salt", salt)
        return salt

    def get_cursor(self, video_id: str, name: str) -> str | None:
        r = self.conn.execute(
            "SELECT value FROM cursors WHERE video_id=? AND name=?", (video_id, name)
        ).fetchone()
        return r["value"] if r else None

    def set_cursor(self, video_id: str, name: str, value: str) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT OR REPLACE INTO cursors(video_id,name,value) VALUES(?,?,?)",
                (video_id, name, value),
            )

    # ---- messages -------------------------------------------------------
    def hash_author(self, raw: str) -> str:
        return hashlib.sha256((self._salt + raw).encode()).hexdigest()[:16]

    def insert_messages(self, msgs: Iterable[ChatMessage]) -> int:
        """Insert; duplicates (same id) are ignored. Returns number of NEW rows."""
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        rows = [
            (
                m.id, m.video_id, m.source, m.ts, self.hash_author(m.author_id),
                m.author_name if self.store_names else None,
                m.text, m.kind, m.amount, now,
            )
            for m in msgs
        ]
        if not rows:
            return 0
        with self.conn:
            before = self.conn.total_changes
            self.conn.executemany(
                "INSERT OR IGNORE INTO messages(id,video_id,source,ts,author,author_name,"
                "text,kind,amount,ingested_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                rows,
            )
            return self.conn.total_changes - before

    def count(self, video_id: str | None = None) -> int:
        q, a = "SELECT COUNT(*) c FROM messages", ()
        if video_id:
            q, a = q + " WHERE video_id=?", (video_id,)
        return self.conn.execute(q, a).fetchone()["c"]

    def pending(self, limit: int = 1000, version: int = ENRICH_VERSION) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT m.* FROM messages m LEFT JOIN enriched e ON e.id=m.id "
            "WHERE e.id IS NULL OR e.version < ? ORDER BY m.ts LIMIT ?",
            (version, limit),
        ).fetchall()

    def save_enriched(self, rows: list[dict]) -> None:
        if not rows:
            return
        with self.conn:
            self.conn.executemany(
                "INSERT OR REPLACE INTO enriched(id,clean,lang,key,flags,sentiment,label,"
                "entities,hashtags,emojis,model,version) VALUES("
                ":id,:clean,:lang,:key,:flags,:sentiment,:label,:entities,:hashtags,:emojis,"
                ":model,:version)",
                [
                    {
                        **r,
                        "flags": json.dumps(r["flags"]),
                        "entities": json.dumps(r["entities"], ensure_ascii=False),
                        "hashtags": json.dumps(r["hashtags"], ensure_ascii=False),
                        "emojis": json.dumps(r["emojis"], ensure_ascii=False),
                    }
                    for r in rows
                ],
            )

    def frame(self, video_id: str | None = None) -> pd.DataFrame:
        q = (
            "SELECT m.id, m.video_id, m.source, m.ts, m.author, m.text, m.kind, m.amount, "
            "e.clean, e.lang, e.key, e.flags, e.sentiment, e.label, e.entities, e.hashtags, "
            "e.emojis FROM messages m JOIN enriched e ON e.id=m.id"
        )
        params: tuple = ()
        if video_id:
            q += " WHERE m.video_id=?"
            params = (video_id,)
        df = pd.read_sql_query(q + " ORDER BY m.ts", self.conn, params=params)
        for col in ("flags", "entities", "hashtags", "emojis"):
            df[col] = df[col].apply(json.loads)
        df["ts"] = pd.to_datetime(df["ts"], utc=True, format="ISO8601")
        return df

    def close(self) -> None:
        self.conn.close()
