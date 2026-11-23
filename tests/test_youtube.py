import threading

import pytest

from ytpulse.sources.youtube import (ApiError, ChatEnded, CommentsSource, LiveChatSource, QuotaExceeded,
                                     YouTubeClient, parse_live_item)


class Resp:
    def __init__(self, status, body):
        self.status_code, self._b, self.text = status, body, str(body)

    @property
    def ok(self):
        return self.status_code == 200

    def json(self):
        return self._b


class FakeSession:
    def __init__(self, script):
        self.script, self.calls = list(script), []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, dict(params)))
        r = self.script.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def client(script):
    sess = FakeSession(script)
    return YouTubeClient("KEY", session=sess, sleep=lambda s: None), sess


def err(status, reason, msg="x"):
    return Resp(status, {"error": {"message": msg, "errors": [{"reason": reason}]}})


def text_item(i, text="hi"):
    return {"id": i, "snippet": {"type": "textMessageEvent", "publishedAt": "2026-11-23T08:00:01.5Z",
                                 "textMessageDetails": {"messageText": text}},
            "authorDetails": {"channelId": "UC1", "displayName": "N"}}


VIDEO = Resp(200, {"items": [{"snippet": {"liveBroadcastContent": "live"},
                              "liveStreamingDetails": {"activeLiveChatId": "CHAT"}}]})


def test_parse_items():
    m = parse_live_item(text_item("a", "नमस्ते"), "v")
    assert m.text == "नमस्ते" and m.ts.endswith("+00:00") and m.kind == "text"
    sc = parse_live_item({"id": "b", "snippet": {"type": "superChatEvent", "publishedAt": "2026-11-23T08:00:01Z",
                          "superChatDetails": {"userComment": "yo", "amountDisplayString": "₹100"}},
                          "authorDetails": {"channelId": "U"}}, "v")
    assert sc.kind == "superchat" and sc.amount == "₹100"
    assert parse_live_item({"id": "c", "snippet": {"type": "messageDeletedEvent", "publishedAt": "2026-11-23T08:00:01Z"}}, "v") is None


def test_live_polls_resumes_token_and_stops_on_chat_end():
    c, sess = client([VIDEO,
                      Resp(200, {"items": [text_item("1"), text_item("2")], "nextPageToken": "T1", "pollingIntervalMillis": 1}),
                      Resp(200, {"items": [text_item("3"), {"id": "e", "snippet": {"type": "chatEndedEvent", "publishedAt": "2026-11-23T08:01:00Z"}}],
                                 "nextPageToken": "T2", "pollingIntervalMillis": 1})])
    src = LiveChatSource(c, "v", min_poll=0, max_poll=1)
    got = [m.id for b in src.batches(threading.Event()) for m in b]
    assert got == ["1", "2", "3"]
    assert sess.calls[2][1]["pageToken"] == "T1"   # token carried between polls
    assert "pageToken" not in sess.calls[1][1]
    assert c.units_used == 1 + 5 + 5


def test_not_live_gives_clear_error():
    c, _ = client([Resp(200, {"items": [{"snippet": {"liveBroadcastContent": "none"}}]})])
    with pytest.raises(ChatEnded, match="not live|ended"):
        list(LiveChatSource(c, "v").batches(threading.Event()))


def test_quota_exceeded_is_distinct():
    c, _ = client([err(403, "quotaExceeded", "daily quota")])
    with pytest.raises(QuotaExceeded):
        c.get("videos", id="x")


def test_retries_transient_then_succeeds():
    c, sess = client([err(503, "backendError"), err(403, "rateLimitExceeded"), Resp(200, {"ok": 1})])
    assert c.get("videos", id="x") == {"ok": 1} and len(sess.calls) == 3


def test_gives_up_after_max_retries_and_other_errors_raise():
    c, _ = client([err(503, "backendError")] * 5)
    with pytest.raises(ApiError):
        c.get("videos", id="x")
    c2, _ = client([err(400, "keyInvalid", "bad key")])
    with pytest.raises(ApiError, match="keyInvalid"):
        c2.get("videos", id="x")


def test_comments_pagination():
    def thread(i):
        return {"snippet": {"topLevelComment": {"id": i, "snippet": {
            "publishedAt": "2026-11-23T08:00:00Z", "textOriginal": "nice", "authorChannelId": {"value": "U"}}}}}
    c, sess = client([Resp(200, {"items": [thread("a")], "nextPageToken": "N"}), Resp(200, {"items": [thread("b")]})])
    ids = [m.id for b in CommentsSource(c, "v").batches(threading.Event()) for m in b]
    assert ids == ["a", "b"] and sess.calls[1][1]["pageToken"] == "N"
