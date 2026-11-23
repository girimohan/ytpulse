"""Replay a JSONL file (one message per line) - for tests, backfills and other platforms.

Line format: {"id","ts","author","text"} plus optional "kind","amount","video_id".
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Iterator

from ..models import ChatMessage, to_utc_iso


class JsonlSource:
    def __init__(self, path: str, video_id: str = "replay", batch_size: int = 500):
        self.path, self.video_id, self.batch_size = Path(path), video_id, batch_size

    def batches(self, stop: threading.Event) -> Iterator[list[ChatMessage]]:
        buf: list[ChatMessage] = []
        with self.path.open(encoding="utf-8") as fh:
            for line in fh:
                if stop.is_set():
                    break
                line = line.strip()
                if not line:
                    continue
                d = json.loads(line)
                buf.append(ChatMessage(
                    id=str(d["id"]), video_id=d.get("video_id", self.video_id), source="replay",
                    ts=to_utc_iso(d["ts"]), author_id=str(d.get("author", "unknown")),
                    text=d.get("text", ""), kind=d.get("kind", "text"), amount=d.get("amount"),
                ))
                if len(buf) >= self.batch_size:
                    yield buf
                    buf = []
        if buf:
            yield buf
