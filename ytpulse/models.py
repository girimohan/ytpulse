from __future__ import annotations

import re
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
        value = value.strip().replace("Z", "+00:00")
        # Python < 3.11 only accepts 3 or 6 fractional digits; YouTube may send 1-9.
        value = re.sub(r"\.(\d+)", lambda m: "." + m.group(1)[:6].ljust(6, "0"), value, count=1)
        dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat(timespec="milliseconds")
