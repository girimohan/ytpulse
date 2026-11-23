"""CLI-level tests: source auto-selection for `analyze`, and `purge`. No network, no ML."""
import os
import time

import pytest

from ytpulse import cli, config
from ytpulse.models import ChatMessage
from ytpulse.sources import youtube

VID = "abcdefghijk"


class FakeComments:
    def __init__(self, client, video_id, max_pages):
        FakeComments.max_pages = max_pages
        self.video_id = video_id

    def batches(self, stop):
        texts = ["great interview, very good", "bakwas waste of time", "what time is it",
                 "Modi ji ne kamaal kar diya", "this is a lie, shameful"]
        yield [ChatMessage(id=f"c{i}", video_id=self.video_id, source="comment",
                           ts=f"2026-11-23T08:0{i}:00+00:00", author_id=f"u{i}", text=t)
               for i, t in enumerate(texts)]


class FakeLive:
    def __init__(self, *a, **k):
        FakeLive.used = True

    def batches(self, stop):
        return iter(())


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config, "api_key", lambda: "test-key")
    monkeypatch.setattr(youtube, "CommentsSource", FakeComments)
    monkeypatch.setattr(youtube, "LiveChatSource", FakeLive)
    monkeypatch.setattr(cli, "_video_meta", lambda vid, store, cfg: {
        "video_id": vid, "url": "", "title": "T", "channel": "C",
        "utc_offset_minutes": 330, "timezone_label": "IST"})
    FakeLive.used = False
    return tmp_path


def video(state, chat_id=None):
    return {"snippet": {"liveBroadcastContent": state, "title": "T"},
            "liveStreamingDetails": {"activeLiveChatId": chat_id} if chat_id else {}}


def test_analyze_uses_comments_for_normal_video(env, monkeypatch, capsys):
    monkeypatch.setattr(youtube, "video_info", lambda c, v: video("none"))
    rc = cli.main(["analyze", f"https://www.youtube.com/watch?v={VID}", "--backend", "lexicon",
                   "--no-open", "--max-comments", "250"])
    assert rc == 0
    assert FakeComments.max_pages == 3 and not FakeLive.used
    assert (env / "reports" / VID / "report.html").exists()
    assert (env / "data" / f"{VID}.db").exists()
    assert "net sentiment" in capsys.readouterr().out


def test_analyze_prefers_live_chat_when_live(env, monkeypatch):
    monkeypatch.setattr(youtube, "video_info", lambda c, v: video("live", "CHAT"))
    cli.main(["analyze", VID, "--backend", "lexicon", "--no-open", "--minutes", "0.01"])
    assert FakeLive.used


def test_analyze_comments_flag_overrides_live(env, monkeypatch):
    monkeypatch.setattr(youtube, "video_info", lambda c, v: video("live", "CHAT"))
    cli.main(["analyze", VID, "--backend", "lexicon", "--no-open", "--comments"])
    assert not FakeLive.used


def test_analyze_refuses_upcoming_stream(env, monkeypatch):
    monkeypatch.setattr(youtube, "video_info", lambda c, v: video("upcoming"))
    assert cli.main(["analyze", VID, "--backend", "lexicon", "--no-open"]) == 2


def test_analyze_rejects_bad_url(env):
    assert cli.main(["analyze", "https://example.com/nothing", "--backend", "lexicon"]) == 2


def test_purge_is_dry_run_by_default_and_spares_demo(env, capsys):
    (env / "data").mkdir()
    (env / "reports" / "old").mkdir(parents=True)
    old, fresh, demo = (env / "data" / n for n in ("old.db", "fresh.db", "demo.db"))
    for p in (old, fresh, demo):
        p.write_text("x")
    stamp = time.time() - 40 * 86400
    for p in (old, demo):
        os.utime(p, (stamp, stamp))

    assert cli.main(["purge"]) == 0
    assert old.exists()  # dry run
    assert cli.main(["purge", "--yes"]) == 0
    assert not old.exists() and not (env / "reports" / "old").exists()
    assert fresh.exists() and demo.exists()


def test_summary_and_site_index(env, capsys):
    assert cli.main(["demo"]) == 0
    capsys.readouterr()
    assert cli.main(["summary", "reports/demo", "--url", "https://x.example/r"]) == 0
    md = capsys.readouterr().out
    assert "Open the full report" in md and "https://x.example/r" in md and "not a poll" in md

    site = env / "site"
    (site / "demo").mkdir(parents=True)
    for f in ("report.json",):
        (site / "demo" / f).write_bytes((env / "reports" / "demo" / f).read_bytes())
    assert cli.main(["site-index", "site"]) == 0
    index = (site / "index.html").read_text(encoding="utf-8")
    assert "demo/report.html" in index and (site / ".nojekyll").exists()
    assert "Analyze a video" in index and "api.github.com" in index


def test_report_has_plain_language_header_and_share_cards(env):
    assert cli.main(["demo"]) == 0
    page = (env / "reports" / "demo" / "report.html").read_text(encoding="utf-8")
    assert "class=\"chip" in page and "Share cards" in page and "cards/summary.png" in page
    assert "role='tab'" in page and "../" in page
    assert "not a poll" in page


@pytest.mark.parametrize("raw", ["2026-11-23T08:00:01.5Z", "2026-11-23T08:00:01Z", "2026-11-23T08:00:01.123456789Z",
                                 "2026-11-23T13:30:01.25+05:30"])
def test_timestamps_with_any_fraction_length_parse(raw):
    from ytpulse.models import to_utc_iso
    assert to_utc_iso(raw).startswith("2026-11-23T0") or to_utc_iso(raw).startswith("2026-11-23T08")
