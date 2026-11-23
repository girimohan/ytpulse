"""Official YouTube Data API v3 sources: live chat and video comments.

Uses only documented endpoints (no scraping), so it stays inside YouTube's ToS.
Quota notes (default project quota is 10,000 units/day):
  liveChatMessages.list  ~5 units per call   -> polling every 5s burns ~3,600 units/hour
  commentThreads.list     1 unit per call
  videos.list             1 unit per call
The client counts units locally so you can see the burn rate in the logs.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Iterator

import requests

from ..models import ChatMessage, to_utc_iso

log = logging.getLogger("ytpulse.youtube")
API = "https://www.googleapis.com/youtube/v3"

UNIT_COST = {"liveChat/messages": 5, "videos": 1, "commentThreads": 1}


class ApiError(RuntimeError):
    pass


class QuotaExceeded(ApiError):
    pass


class ChatEnded(ApiError):
    pass


class YouTubeClient:
    def __init__(self, key: str, session: requests.Session | None = None,
                 timeout: float = 20, max_retries: int = 5, sleep=time.sleep):
        self.key = key
        self.session = session or requests.Session()
        self.timeout = timeout
        self.max_retries = max_retries
        self.sleep = sleep
        self.units_used = 0

    def get(self, path: str, **params) -> dict:
        params["key"] = self.key
        delay = 1.0
        for attempt in range(1, self.max_retries + 1):
            try:
                r = self.session.get(f"{API}/{path}", params=params, timeout=self.timeout)
            except requests.RequestException as e:  # network blip
                log.warning("network error (%s), retry %d/%d", e, attempt, self.max_retries)
                self.sleep(delay)
                delay = min(delay * 2, 30)
                continue
            self.units_used += UNIT_COST.get(path, 1)
            if r.status_code == 200:
                return r.json()
            reason, message = _error_reason(r)
            if r.status_code in (500, 502, 503, 504) or reason == "rateLimitExceeded":
                log.warning("transient API error %s %s, retry %d/%d",
                            r.status_code, reason, attempt, self.max_retries)
                self.sleep(delay)
                delay = min(delay * 2, 60)
                continue
            if reason in ("quotaExceeded", "dailyLimitExceeded"):
                raise QuotaExceeded(f"{message} (local estimate: {self.units_used} units used)")
            if reason in ("liveChatEnded", "liveChatNotFound", "liveChatDisabled"):
                raise ChatEnded(f"{reason}: {message}")
            raise ApiError(f"HTTP {r.status_code} {reason}: {message}")
        raise ApiError(f"Giving up on {path} after {self.max_retries} attempts")


def _error_reason(r: requests.Response) -> tuple[str, str]:
    try:
        err = r.json()["error"]
        return (err.get("errors") or [{}])[0].get("reason", ""), err.get("message", "")
    except Exception:
        return "", r.text[:200]


def video_info(client: YouTubeClient, video_id: str) -> dict:
    data = client.get("videos", part="snippet,liveStreamingDetails", id=video_id)
    items = data.get("items") or []
    if not items:
        raise ApiError(f"Video {video_id} not found (private, removed, or wrong id).")
    return items[0]


def parse_live_item(item: dict, video_id: str) -> ChatMessage | None:
    """Convert one liveChatMessages item. Returns None for non-message events."""
    sn = item.get("snippet", {})
    typ = sn.get("type", "")
    author = item.get("authorDetails", {})
    base = dict(
        id=item["id"], video_id=video_id, source="live_chat",
        ts=to_utc_iso(sn["publishedAt"]),
        author_id=author.get("channelId", "unknown"),
        author_name=author.get("displayName"),
    )
    if typ == "textMessageEvent":
        text = (sn.get("textMessageDetails") or {}).get("messageText") or sn.get("displayMessage", "")
        return ChatMessage(text=text, kind="text", **base)
    if typ == "superChatEvent":
        d = sn.get("superChatDetails") or {}
        return ChatMessage(text=d.get("userComment", ""), kind="superchat",
                           amount=d.get("amountDisplayString"), **base)
    if typ == "superStickerEvent":
        d = sn.get("superStickerDetails") or {}
        return ChatMessage(text="", kind="sticker", amount=d.get("amountDisplayString"), **base)
    if typ in ("newSponsorEvent", "memberMilestoneChatEvent"):
        d = sn.get("memberMilestoneChatDetails") or {}
        return ChatMessage(text=d.get("userComment", ""), kind="membership", **base)
    return None  # deletions, bans, chatEnded, poll events ...


class LiveChatSource:
    def __init__(self, client: YouTubeClient, video_id: str,
                 min_poll: float = 3.0, max_poll: float = 30.0):
        self.client, self.video_id = client, video_id
        self.min_poll, self.max_poll = min_poll, max_poll
        self.page_token: str | None = None

    def resolve_chat_id(self) -> str:
        info = video_info(self.client, self.video_id)
        details = info.get("liveStreamingDetails") or {}
        chat_id = details.get("activeLiveChatId")
        if not chat_id:
            state = info["snippet"].get("liveBroadcastContent", "none")
            raise ChatEnded(
                f"No active live chat for {self.video_id} (liveBroadcastContent={state}). "
                "The stream is not live, has ended, or chat is disabled. Chat replay is not "
                "available through the API, so live chat must be captured while it is live."
            )
        return chat_id

    def batches(self, stop: threading.Event) -> Iterator[list[ChatMessage]]:
        chat_id = self.resolve_chat_id()
        log.info("live chat id resolved; polling")
        while not stop.is_set():
            params = dict(liveChatId=chat_id, part="snippet,authorDetails", maxResults=2000)
            if self.page_token:
                params["pageToken"] = self.page_token
            resp = self.client.get("liveChat/messages", **params)
            ended = any(i.get("snippet", {}).get("type") == "chatEndedEvent"
                        for i in resp.get("items", []))
            msgs = [m for i in resp.get("items", [])
                    if (m := parse_live_item(i, self.video_id)) is not None]
            self.page_token = resp.get("nextPageToken")
            yield msgs
            if ended:
                log.info("chat ended event received")
                return
            wait = float(resp.get("pollingIntervalMillis", 5000)) / 1000.0
            wait = min(max(wait, self.min_poll), self.max_poll)
            log.debug("polled %d msgs, quota~%d, sleeping %.1fs", len(msgs), self.client.units_used, wait)
            if stop.wait(wait):
                return


class CommentsSource:
    """Top-level comments on any video (live or not). Newest first, bounded by max_pages."""

    def __init__(self, client: YouTubeClient, video_id: str, max_pages: int = 50):
        self.client, self.video_id, self.max_pages = client, video_id, max_pages

    def batches(self, stop: threading.Event) -> Iterator[list[ChatMessage]]:
        token = None
        for _ in range(self.max_pages):
            if stop.is_set():
                return
            params = dict(part="snippet", videoId=self.video_id, order="time",
                          maxResults=100, textFormat="plainText")
            if token:
                params["pageToken"] = token
            resp = self.client.get("commentThreads", **params)
            out = []
            for it in resp.get("items", []):
                top = it["snippet"]["topLevelComment"]
                s = top["snippet"]
                out.append(ChatMessage(
                    id=top["id"], video_id=self.video_id, source="comment",
                    ts=to_utc_iso(s["publishedAt"]),
                    author_id=(s.get("authorChannelId") or {}).get("value", "unknown"),
                    author_name=s.get("authorDisplayName"),
                    text=s.get("textOriginal") or s.get("textDisplay", ""),
                ))
            yield out
            token = resp.get("nextPageToken")
            if not token:
                return
