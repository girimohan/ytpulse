from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class ChatMessage:
    """One chat message or comment, as produced by any source adapter."""

    id: str
    video_id: str
    source: str  # live_chat | comment | replay | synthetic
    ts: str  # ISO-8601 UTC
    author_id: str  # raw channel id; hashed by the store, never persisted raw
    text: str
    kind: str = "text"  # text | superchat | sticker | membership
    amount: str | None = None  # e.g. "₹100.00" for super chats
    author_name: str | None = None  # dropped by the store unless privacy.store_author_names


def to_utc_iso(value: str | datetime) -> str:
    """Normalise a timestamp (YouTube uses RFC 3339, sometimes with 'Z') to UTC ISO."""
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat(timespec="milliseconds")
