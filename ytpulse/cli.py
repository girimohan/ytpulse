from __future__ import annotations

import argparse
import logging
import sys
import threading
from pathlib import Path

import requests

from . import config
from .analytics import summarize
from .nlp.entities import EntityMatcher
from .nlp.sentiment import build_model
from .pipeline import Enricher, enrich_pending, run_live
from .sources import extract_video_id
from .store import Store

log = logging.getLogger("ytpulse")


def _setup(args):
    cfg = config.load_settings(args.config)
    if getattr(args, "backend", None):
        cfg["sentiment"]["backend"] = args.backend
    matcher = EntityMatcher(config.load_entities(args.entities))
    return cfg, matcher


def _video_meta(video_id: str, store: Store, cfg: dict) -> dict:
    """Title / channel via the public oEmbed endpoint (no API quota, no key)."""
    title, channel = store.get_meta(f"title:{video_id}"), store.get_meta(f"channel:{video_id}")
    if not title:
        try:
            r = requests.get("https://www.youtube.com/oembed", timeout=10,
                             params={"url": f"https://www.youtube.com/watch?v={video_id}", "format": "json"})
            if r.ok:
                title, channel = r.json().get("title", ""), r.json().get("author_name", "")
                store.set_meta(f"title:{video_id}", title)
                store.set_meta(f"channel:{video_id}", channel)
        except requests.RequestException:
            pass
    d = cfg["display"]
    return {"video_id": video_id, "url": f"https://www.youtube.com/watch?v={video_id}",
            "title": title or video_id, "channel": channel or "",
            "utc_offset_minutes": d["utc_offset_minutes"], "timezone_label": d["timezone_label"]}


def make_report(store: Store, cfg, matcher, video_id: str, out_dir: str, model_name: str = "") -> dict:
    from .report import write_report  # matplotlib import is slow; keep CLI start snappy

    df = store.frame(video_id)
    if df.empty:
        log.warning("nothing enriched yet; no report written")
        return {}
    if (df["source"] == "synthetic").any():
        meta = {"video_id": video_id, "url": "", "title": "Synthetic demo stream", "channel": "demo",
                "utc_offset_minutes": cfg["display"]["utc_offset_minutes"],
                "timezone_label": cfg["display"]["timezone_label"]}
    else:
        meta = _video_meta(video_id, store, cfg)
    meta["sentiment_model"] = model_name or cfg["sentiment"]["backend"]
    meta["source_kind"] = str(df["source"].iloc[0])  # 'comment' | 'live' | ... drives wording in the cards
    s = summarize(df, cfg, matcher, meta)
    paths = write_report(s, out_dir)
    log.info("report written: %s", paths["html"])
    return paths


def _execute(source, vid: str, cfg: dict, matcher, db: str, out: str, minutes: float | None) -> int:
    """Ingest -> enrich -> report for one video. Shared by `run` and `analyze`."""
    model = build_model(cfg["sentiment"])
    enricher = Enricher(model, matcher, cfg)

    def report_fn(store: Store):
        make_report(store, cfg, matcher, vid, out, model.name)

    try:
        run_live(source, db, enricher, cfg, vid, report_fn, minutes)
    except Exception as e:
        from .sources.youtube import ApiError  # local import: requests-only dependency chain
        if isinstance(e, ApiError):
            log.error("%s", e)
            return 2
        raise
    return 0


def _auto_backend() -> str:
    """hybrid when the ML extras are installed, otherwise the dependency-free lexicon."""
    import importlib.util as iu
    if iu.find_spec("transformers") and iu.find_spec("torch"):
        return "hybrid"
    log.warning("ML extras are not installed, so the weak lexicon backend is used (poor on Nepali/Hindi). "
                "Install them with: pip install -e \".[ml]\"")
    return "lexicon"


def _print_summary(json_path: Path) -> None:
    import json
    s = json.loads(json_path.read_text(encoding="utf-8"))
    se, f, low = s["sentiment"], s["funnel"], s["meta"].get("low_sample")
    print(f"\n{s['meta']['title']}")
    print(f"  {se['n']} of {f['total']} messages counted after filtering "
          f"(spam {f['spam']}, repeats {f['self_dupe'] + f['flood']}, copy-paste {f['coordinated']})")
    print(f"  net sentiment {se['net']:+.0f}  (95% CI {se['ci_low']:+.0f} to {se['ci_high']:+.0f})   "
          f"positive {se['positive']} / neutral {se['neutral']} / negative {se['negative']}")
    rows = [e for k in ("person", "topic", "country") for e in s["entities"].get(k, [])]
    rows.sort(key=lambda e: -e["mentions"])
    for e in rows[:5]:
        net = f"net {e['net']:+.0f}" if e["n"] >= 30 else "too few for a net score"
        print(f"  {e['name']:<32} {e['mentions']:>4} mentions   {net}")
    if low or se["n"] < 100:
        print("  NOTE: small sample, so treat these numbers as anecdotal.")


def cmd_analyze(a) -> int:
    """Paste a link, get a report: picks live chat or comments automatically."""
    import math
    import webbrowser
    from .sources.youtube import ApiError, CommentsSource, LiveChatSource, YouTubeClient, video_info

    try:
        vid = extract_video_id(a.url)
    except ValueError as e:
        log.error("%s", e)
        return 2
    a.backend = a.backend or _auto_backend()
    cfg, matcher = _setup(a)
    cfg["privacy"]["store_author_names"] = False  # hashed ids only; never needed for the report
    client = YouTubeClient(config.api_key())
    try:
        info = video_info(client, vid)
    except ApiError as e:
        log.error("%s", e)
        return 2
    state = info["snippet"].get("liveBroadcastContent", "none")
    chat_id = (info.get("liveStreamingDetails") or {}).get("activeLiveChatId")
    if state == "upcoming":
        log.error("This stream has not started yet. Run again once it is live.")
        return 2
    ic = cfg["ingest"]
    if state == "live" and chat_id and not a.comments:
        log.info("LIVE stream: capturing chat (~5 quota units per poll). Press Ctrl-C when you have enough%s.",
                 f", or it stops after {a.minutes:g} min" if a.minutes else "")
        source = LiveChatSource(client, vid, ic["min_poll_seconds"], ic["max_poll_seconds"])
    else:
        if state == "live":
            log.info("Live chat is unavailable or --comments was given; using regular comments.")
        log.info("Fetching up to %d comments (1 quota unit per 100).", a.max_comments)
        source = CommentsSource(client, vid, math.ceil(a.max_comments / 100))
        a.minutes = None
    out = a.out or f"reports/{vid}"
    rc = _execute(source, vid, cfg, matcher, a.db or f"data/{vid}.db", out, a.minutes)
    html, js = Path(out) / "report.html", Path(out) / "report.json"
    if rc == 0 and js.exists():
        _print_summary(js)
        print(f"\n  report: {html.resolve()}\n  cards:  {(Path(out) / 'cards').resolve()}")
        if not a.no_open:
            webbrowser.open(html.resolve().as_uri())
    elif rc == 0:
        print("No messages were collected (comments disabled, or nothing posted yet).")
    return rc


def cmd_purge(a) -> int:
    """Delete stored data older than N days (YouTube asks API data to be refreshed or removed)."""
    import shutil
    import time
    cutoff = time.time() - a.days * 86400
    old = [p for p in sorted(Path("data").glob("*.db")) if p.stem != "demo" and p.stat().st_mtime < cutoff]
    if not old:
        print(f"Nothing older than {a.days} days.")
        return 0
    for p in old:
        rep = Path("reports") / p.stem
        print(("deleting " if a.yes else "would delete ") + f"{p}" + (f" and {rep}" if rep.exists() else ""))
        if a.yes:
            for ext in ("", "-wal", "-shm"):
                Path(f"{p}{ext}").unlink(missing_ok=True)
            shutil.rmtree(rep, ignore_errors=True)
    if not a.yes:
        print("Dry run. Add --yes to delete.")
    return 0


def cmd_run(a) -> int:
    cfg, matcher = _setup(a)
    cfg["privacy"]["store_author_names"] = cfg["privacy"]["store_author_names"] or a.store_names

    if a.source == "synthetic":
        from .sources.synthetic import SyntheticSource
        vid, source = "DEMO0000000", SyntheticSource(a.n, a.seed)
    elif a.source == "jsonl":
        from .sources.replay import JsonlSource
        vid = extract_video_id(a.video) if a.video else "replay"
        source = JsonlSource(a.file, vid)
    else:
        from .sources.youtube import CommentsSource, LiveChatSource, YouTubeClient
        vid = extract_video_id(a.video)
        client = YouTubeClient(config.api_key())
        ic = cfg["ingest"]
        source = (LiveChatSource(client, vid, ic["min_poll_seconds"], ic["max_poll_seconds"])
                  if a.source == "live" else CommentsSource(client, vid, a.max_pages))

    return _execute(source, vid, cfg, matcher, a.db or f"data/{vid}.db", a.out or f"reports/{vid}", a.minutes)


def cmd_report(a) -> int:
    cfg, matcher = _setup(a)
    store = Store(a.db)
    model = build_model(cfg["sentiment"])
    if a.reenrich:
        with store.conn:
            store.conn.execute("DELETE FROM enriched")
    n = enrich_pending(store, Enricher(model, matcher, cfg))
    if n:
        log.info("enriched %d pending messages", n)
    vid = a.video and extract_video_id(a.video) or store.conn.execute(
        "SELECT video_id FROM messages GROUP BY video_id ORDER BY COUNT(*) DESC LIMIT 1").fetchone()[0]
    paths = make_report(store, cfg, matcher, vid, a.out or f"reports/{vid}", model.name)
    for k, v in paths.items():
        print(f"{k:>14}: {v}")
    return 0


def cmd_eval(a) -> int:
    """Score each backend against a hand-labelled CSV (columns: text,label) of REAL messages."""
    import csv
    from .nlp import text as T
    from .nlp.sentiment import HybridModel, LexiconModel, TransformerModel, to_label
    cfg = config.load_settings(a.config)
    with open(a.labels, encoding="utf-8-sig", newline="") as fh:
        rows = [(r["text"], r["label"].strip().lower()) for r in csv.DictReader(fh)]
    texts, gold = [T.normalize(t) for t, _ in rows], [l for _, l in rows]
    lex = LexiconModel()
    models = {"lexicon": lex}
    if not a.skip_ml:
        tr = TransformerModel(cfg["sentiment"]["model"], cfg["sentiment"]["batch_size"])
        models |= {"transformer": tr, "hybrid": HybridModel(tr, lex, cfg["sentiment"]["hybrid_model_weight"])}
    labels = ("positive", "neutral", "negative")
    print(f"{len(rows)} labelled messages")
    for name, m in models.items():
        pred = [to_label(s, cfg["sentiment"]["pos_threshold"], cfg["sentiment"]["neg_threshold"]) for s in m.predict(texts)]
        acc = sum(p == g for p, g in zip(pred, gold)) / len(gold)
        f1s = []
        for c in labels:
            tp = sum(p == c and g == c for p, g in zip(pred, gold))
            fp = sum(p == c and g != c for p, g in zip(pred, gold))
            fn = sum(p != c and g == c for p, g in zip(pred, gold))
            f1s.append(2 * tp / (2 * tp + fp + fn) if (2 * tp + fp + fn) else 0.0)
        print(f"{name:12s} accuracy {acc:.3f}   macro-F1 {sum(f1s) / 3:.3f}   (F1 pos/neu/neg: "
              + " / ".join(f"{x:.2f}" for x in f1s) + ")")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser("ytpulse", description=__doc__)
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp):
        sp.add_argument("--config", help="settings YAML overriding defaults")
        sp.add_argument("--entities", help="entity gazetteer YAML (default: built-in)")
        sp.add_argument("--backend", choices=["lexicon", "transformer", "hybrid"], help="sentiment backend")
        sp.add_argument("--db"), sp.add_argument("--out")

    an = sub.add_parser("analyze", help="paste a YouTube link: auto-picks live chat or comments, writes the report")
    common(an)
    an.add_argument("url", help="YouTube URL or 11-char video id")
    an.add_argument("--max-comments", type=int, default=5000, help="comment cap for non-live videos (default 5000)")
    an.add_argument("--comments", action="store_true", help="use regular comments even if the video is live")
    an.add_argument("--minutes", type=float, help="live only: stop capturing after N minutes")
    an.add_argument("--no-open", action="store_true", help="do not open the report in the browser")
    an.set_defaults(fn=cmd_analyze)

    pg = sub.add_parser("purge", help="delete stored data and reports older than N days")
    pg.add_argument("--days", type=int, default=30)
    pg.add_argument("--yes", action="store_true", help="actually delete (default is a dry run)")
    pg.set_defaults(fn=cmd_purge)

    r = sub.add_parser("run", help="ingest + enrich + report (live or one-shot)")
    common(r)
    r.add_argument("--video", help="YouTube URL or 11-char id")
    r.add_argument("--source", choices=["live", "comments", "jsonl", "synthetic"], default="live")
    r.add_argument("--file", help="JSONL file for --source jsonl")
    r.add_argument("--minutes", type=float, help="stop ingesting after N minutes")
    r.add_argument("--max-pages", type=int, default=50, help="comment pages (100 comments each)")
    r.add_argument("--store-names", action="store_true", help="store display names (default: hashed ids only)")
    r.add_argument("--n", type=int, default=1500), r.add_argument("--seed", type=int, default=7)
    r.set_defaults(fn=cmd_run)

    d = sub.add_parser("demo", help="end-to-end run on SYNTHETIC data (no API key needed)")
    common(d)
    d.set_defaults(fn=lambda a: cmd_run(argparse.Namespace(**{**vars(a), "source": "synthetic", "video": None,
                   "file": None, "minutes": None, "max_pages": 0, "store_names": False, "n": 1500, "seed": 7,
                   "db": a.db or "data/demo.db", "out": a.out or "reports/demo"})))

    rp = sub.add_parser("report", help="(re)build reports from an existing database")
    common(rp)
    rp.add_argument("--video"), rp.add_argument("--reenrich", action="store_true",
                                                 help="recompute NLP (after changing model or gazetteer)")
    rp.set_defaults(fn=cmd_report)

    ev = sub.add_parser("eval", help="compare sentiment backends on a hand-labelled CSV of real messages")
    ev.add_argument("labels", help="CSV with columns: text,label (positive|neutral|negative)")
    ev.add_argument("--config"), ev.add_argument("--skip-ml", action="store_true")
    ev.set_defaults(fn=cmd_eval)
    return p


def main(argv: list[str] | None = None) -> int:
    a = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s", datefmt="%H:%M:%S")
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    return a.fn(a)


if __name__ == "__main__":
    raise SystemExit(main())
