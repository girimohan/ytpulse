"""Orchestration: enrichment (per-message NLP) and the live ingest+enrich+report loop."""
from __future__ import annotations

import logging
import re
import threading
import time
from pathlib import Path

from .nlp import text as T
from .nlp.entities import EntityMatcher
from .nlp.sentiment import SentimentModel, to_label
from .store import ENRICH_VERSION, Store

log = logging.getLogger("ytpulse.pipeline")

# Clause boundaries: punctuation and contrast words (English / Hinglish / Hindi / Nepali).
_CLAUSE = re.compile(
    rf"[.!?;,\n|।]+|(?<![{T.WORD}])(?:but|however|though|lekin|magar|par|parantu|तर|लेकिन|परंतु|मगर|तथापि)(?![{T.WORD}])",
    re.IGNORECASE,
)
_ATTRIBUTABLE = {"person", "country", "place"}


def clause_spans(text: str) -> list[tuple[int, int]]:
    spans, pos = [], 0
    for m in _CLAUSE.finditer(text):
        if m.start() > pos:
            spans.append((pos, m.start()))
        pos = m.end()
    if pos < len(text):
        spans.append((pos, len(text)))
    return [(s, e) for s, e in spans if text[s:e].strip()]


class Enricher:
    def __init__(self, model: SentimentModel, matcher: EntityMatcher, cfg: dict):
        self.model, self.matcher, self.cfg = model, matcher, cfg
        sc, qc = cfg["sentiment"], cfg["quality"]
        self.pos, self.neg, self.max_len = sc["pos_threshold"], sc["neg_threshold"], qc["max_len"]

    def enrich(self, rows) -> list[dict]:
        prepared = []
        for r in rows:
            raw = r["text"] or ""
            clean = T.normalize(raw)
            em = T.emojis(clean)
            prepared.append(dict(
                id=r["id"], raw=raw, clean=clean, emojis=em, lang=T.detect_lang(clean),
                key=T.message_key(clean, em), hashtags=T.hashtags(clean),
                flags=T.spam_flags(raw, clean, em, self.max_len),
                hits=self.matcher.find(clean),
            ))
        # 1) message-level sentiment, one batched model call
        scorable = [i for i, p in enumerate(prepared) if p["clean"]]
        scores = self.model.predict([prepared[i]["clean"] for i in scorable])
        for i, s in zip(scorable, scores):
            prepared[i]["score"] = s
        # 2) clause-level sentiment only where it matters: >=2 distinct people/countries AND >=2 clauses
        clause_jobs: list[tuple[int, list[tuple[int, int]]]] = []
        texts: list[str] = []
        for i, p in enumerate(prepared):
            ids = {h.id for h in p["hits"] if self.matcher.type(h.id) in _ATTRIBUTABLE}
            if len(ids) >= 2:
                spans = clause_spans(p["clean"])
                if len(spans) >= 2:
                    clause_jobs.append((i, spans))
                    texts.extend(p["clean"][s:e] for s, e in spans)
        clause_scores = iter(self.model.predict(texts)) if texts else iter(())
        for i, spans in clause_jobs:
            prepared[i]["clauses"] = [(s, e, next(clause_scores)) for s, e in spans]

        out = []
        for p in prepared:
            score = p.get("score", 0.0)
            ents: dict[str, float] = {}
            for h in p["hits"]:
                es = score
                for s, e, cs in p.get("clauses", []):
                    if s <= h.start < e or (h.start < s and h.end > s):
                        es = cs
                        break
                # keep the most extreme attribution if an entity occurs twice
                if h.id not in ents or abs(es) > abs(ents[h.id]):
                    ents[h.id] = es
            out.append(dict(
                id=p["id"], clean=p["clean"], lang=p["lang"], key=p["key"], flags=p["flags"],
                sentiment=round(score, 4), label=to_label(score, self.pos, self.neg),
                entities=[{"id": k, "s": round(v, 4), "l": to_label(v, self.pos, self.neg)} for k, v in ents.items()],
                hashtags=p["hashtags"], emojis=p["emojis"], model=self.model.name, version=ENRICH_VERSION,
            ))
        return out


def enrich_pending(store: Store, enricher: Enricher, batch: int = 500) -> int:
    done = 0
    while True:
        rows = store.pending(limit=batch)
        if not rows:
            return done
        store.save_enriched(enricher.enrich(rows))
        done += len(rows)


def ingest_worker(source, db_path: str, store_names: bool, stop: threading.Event,
                  errors: list, deadline: float | None = None) -> None:
    """Runs in its own thread with its own SQLite connection."""
    store = Store(db_path, store_names)
    total = 0
    try:
        for batch in source.batches(stop):
            total += store.insert_messages(batch)
            if deadline and time.time() >= deadline:
                log.info("duration reached, stopping ingest")
                break
        log.info("ingest finished: %d new messages stored", total)
    except Exception as e:  # surfaced to the main loop; never silently swallowed
        log.exception("ingest failed")
        errors.append(e)
    finally:
        store.close()
        stop.set()


def run_live(source, db_path: str, enricher: Enricher, cfg: dict, video_id: str,
             report_fn, minutes: float | None = None) -> None:
    """Ingest in a thread; enrich every N seconds; regenerate reports every M seconds."""
    stop, errors = threading.Event(), []
    deadline = time.time() + minutes * 60 if minutes else None
    store = Store(db_path, cfg["privacy"]["store_author_names"])
    t = threading.Thread(target=ingest_worker, daemon=True,
                         args=(source, db_path, cfg["privacy"]["store_author_names"], stop, errors, deadline))
    t.start()
    ic = cfg["ingest"]
    last_report = 0.0
    try:
        while t.is_alive():
            n = enrich_pending(store, enricher)
            now = time.time()
            if n:
                log.info("enriched %d (total stored %d)", n, store.count(video_id))
            if now - last_report >= ic["report_every_seconds"] and store.count(video_id):
                report_fn(store)
                last_report = now
            t.join(timeout=ic["enrich_every_seconds"])
    except KeyboardInterrupt:
        log.info("interrupted, finishing up")
        stop.set()
        t.join(timeout=15)
    finally:
        enrich_pending(store, enricher)
        if store.count(video_id):
            report_fn(store)
        store.close()
    if errors:
        raise errors[0]
