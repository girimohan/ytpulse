import threading

import pytest

from ytpulse import config
from ytpulse.analytics import apply_quality, summarize
from ytpulse.models import ChatMessage
from ytpulse.nlp.entities import EntityMatcher
from ytpulse.nlp.sentiment import LexiconModel
from ytpulse.pipeline import Enricher, clause_spans, enrich_pending
from ytpulse.sources.synthetic import SyntheticSource, generate
from ytpulse.store import Store

CFG = config.load_settings()
MATCHER = EntityMatcher(config.load_entities())


def msg(i, text, author="a", ts="2026-11-23T08:00:00+00:00", **kw):
    return ChatMessage(id=f"m{i}", video_id="v", source="test", ts=ts, author_id=author, text=text, **kw)


@pytest.fixture
def store():
    s = Store(":memory:")
    yield s
    s.close()


def enrich(store):
    enrich_pending(store, Enricher(LexiconModel(), MATCHER, CFG))
    return store.frame("v")


def test_insert_is_idempotent_and_hashes_authors(store):
    m = msg(1, "hello", author="UCsecret", author_name="Real Name")
    assert store.insert_messages([m, m]) == 1
    assert store.insert_messages([m]) == 0
    row = store.conn.execute("SELECT author, author_name FROM messages").fetchone()
    assert row["author"] != "UCsecret" and len(row["author"]) == 16
    assert row["author_name"] is None  # names dropped by default


def test_clause_level_entity_sentiment(store):
    store.insert_messages([msg(1, "Modi was great today, but Balen was a disappointment")])
    df = enrich(store)
    got = {e["id"]: e["l"] for e in df.iloc[0]["entities"]}
    assert got == {"modi": "positive", "balen": "negative"}


def test_clause_spans_split_on_contrast_words():
    t = "Modi accha tha lekin Balen ne kuch nahi bola"
    assert len(clause_spans(t)) == 2


def test_quality_filters(store):
    base = "2026-11-23T08:00:%02d+00:00"
    msgs = [msg(0, "great job today", author="x", ts=base % 0)]
    msgs += [msg(1, "great job today", author="x", ts=base % 5)]                       # self dupe
    msgs += [msg(2, "check https://spam.xyz/a", author="y", ts=base % 6)]              # spam
    msgs += [msg(100 + k, f"flood msg number {k}", author="f", ts=base % k) for k in range(20)]  # flood
    msgs += [msg(200 + k, "Balen zindabad support him now", author=f"c{k}", ts=base % (10 + k)) for k in range(8)]  # burst
    store.insert_messages(msgs)
    df, clusters = apply_quality(enrich(store), CFG["quality"])
    ex = df["exclusion"].value_counts().to_dict()
    assert ex["spam"] == 1 and ex["self_dupe"] == 1
    assert ex["flood"] == 20 - CFG["quality"]["flood_per_minute"]
    assert ex["coordinated"] == 7 and clusters[0]["authors"] == 8   # first copy still counted


def test_slow_repeats_are_not_a_campaign(store):
    msgs = [msg(k, "Balen zindabad support him now", author=f"c{k}", ts=f"2026-11-23T0{k}:00:00+00:00") for k in range(8)]
    store.insert_messages(msgs)
    df, clusters = apply_quality(enrich(store), CFG["quality"])
    assert clusters == [] and df["counted"].all()


def test_summary_end_to_end_on_synthetic(store):
    for b in SyntheticSource(800, 5, video_id="v").batches(threading.Event()):
        store.insert_messages(b)
    s = summarize(enrich(store), CFG, MATCHER, {"title": "t", "channel": "c", "video_id": "v"})
    n = s["sentiment"]["n"]
    assert s["meta"]["synthetic"] is True
    assert n == s["funnel"]["counted"] and 0 < n < s["funnel"]["total"]
    assert s["sentiment"]["ci_low"] <= s["sentiment"]["net"] <= s["sentiment"]["ci_high"]
    names = [e["name"] for e in s["entities"]["person"]]
    assert "Narendra Modi" in names and "Balendra Shah (Balen)" in names
    assert s["funnel"]["total"] == len(generate(800, 5))


def test_report_files_are_written(tmp_path, store):
    from ytpulse.report import write_report
    for b in SyntheticSource(500, 2, video_id="v").batches(threading.Event()):
        store.insert_messages(b)
    s = summarize(enrich(store), CFG, MATCHER, {"title": "t", "channel": "c", "video_id": "v",
                                                "utc_offset_minutes": 330, "timezone_label": "IST"})
    paths = write_report(s, tmp_path)
    for k in ("json", "html", "card_summary", "card_timeline", "card_head_to_head"):
        assert paths[k].exists() and paths[k].stat().st_size > 1000
    assert "DEMO DATA" in paths["html"].read_text(encoding="utf-8")
