"""Source adapters. Each yields lists (batches) of ChatMessage until stopped or exhausted."""
from __future__ import annotations

import re
from typing import Iterator, Protocol
import threading

from ..models import ChatMessage


class Source(Protocol):
    def batches(self, stop: threading.Event) -> Iterator[list[ChatMessage]]: ...


_ID_RE = re.compile(r"(?:v=|youtu\.be/|/live/|/shorts/|/embed/)([\w-]{11})")


def extract_video_id(value: str) -> str:
    """Accept a full URL (watch, youtu.be, live, shorts, embed) or a bare 11-char id."""
    value = value.strip()
    if re.fullmatch(r"[\w-]{11}", value):
        return value
    m = _ID_RE.search(value)
    if not m:
        raise ValueError(f"Cannot find a YouTube video id in {value!r}")
    return m.group(1)
