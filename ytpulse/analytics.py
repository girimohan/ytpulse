"""Aggregation: quality funnel, sentiment with confidence intervals, entity counts, timeline.

Honesty rules baked in:
  * every sentiment number comes with n and a bootstrap 95% CI;
  * copy-paste clusters are counted once (policy: dedupe) and reported separately;
  * results say "live-chat sample", never "public opinion".
"""
from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from .nlp import text as T
from .nlp.entities import EntityMatcher, discover_candidates

SIGN = {"positive": 1, "neutral": 0, "negative": -1}
STOP = set("""
the and for are was but not you your with this that have has had from they them their there what when where
which who how why can will just all any out one our its his her him she now get got see yes also been were
about than then into over more some very much only still here too like would could should does did done
hai hain nahi nahin kya kyun bhai ho hoga hua tha thi ke ki ka ko se par aur mein main yeh woh ye wo kuch sab
abhi bhi toh to ji ne ek isko uska unka mera apna hum aap tum kar karo kiya raha rahe rahi lekin magar chha cha
ra ni pani lai le ma ho yo tyo hami tapai
है हैं था थी नहीं का की के को में से पर और यह वह क्या कुछ बहुत हम आप तुम मैं भी तो ने एक
छ छन् हुन् र को ले लाई मा पनि यो त्यो हामी तपाई तपाईं
live video chat watch watching
""".split())


COMMON_CAPS = set("""
hello thank thanks proud shame great welcome excellent historic wonderful respect please which where who what
time audio subtitles subtitle total useless nothing fake border issue jai bahut accha live good best love
wow nice happy sir madam namaste hey hii dear hind
""".split())


def bootstrap_ci(values: np.ndarray, n_boot: int = 1000, seed: int = 11) -> tuple[float, float]:
    if len(values) == 0:
        return (0.0, 0.0)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(values), size=(n_boot, len(values)))
    means = values[idx].mean(axis=1)
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def _burst_members(members: pd.DataFrame, window: pd.Timedelta, min_authors: int) -> list:
    """Index labels of messages that sit inside any `window` span holding >= min_authors distinct authors.

    Same text from many accounts *within minutes* is a campaign signal; the same common phrase
    spread across hours is just people agreeing.
    """
    idx, ts, au = list(members.index), list(members["ts"]), list(members["author"])
    keep: set[int] = set()
    lo = 0
    for hi in range(len(idx)):
        while ts[hi] - ts[lo] > window:
            lo += 1
        if len(set(au[lo:hi + 1])) >= min_authors:
            keep.update(range(lo, hi + 1))
    return [idx[i] for i in sorted(keep)]


def apply_quality(df: pd.DataFrame, q: dict) -> tuple[pd.DataFrame, list[dict]]:
    """Add `exclusion` ('' = counted) and `counted`; return coordinated clusters found."""
    df = df.sort_values("ts", kind="stable").reset_index(drop=True)
    df["exclusion"] = ""

    def mark(mask: pd.Series, reason: str) -> None:
        m = mask & (df["exclusion"] == "")
        df.loc[m, "exclusion"] = reason

    flagset = df["flags"].apply(set)
    mark(flagset.apply(lambda f: "empty" in f), "empty")
    mark(flagset.apply(lambda f: bool(f & T.HARD_SPAM)), "spam")

    minute = df["ts"].dt.floor("min")
    mark(df.groupby(["author", minute]).cumcount() >= q["flood_per_minute"], "flood")

    nonempty = df["key"].str.len() > 0
    gap = df[nonempty].groupby(["author", "key"])["ts"].diff()
    dupe = pd.Series(False, index=df.index)
    dupe[gap.index] = gap < pd.Timedelta(seconds=q["self_dupe_window_s"])
    mark(dupe, "self_dupe")

    clusters: list[dict] = []
    candidates = df[(df["exclusion"] == "") & (df["key"].str.len() >= q["coordinated_min_len"])]
    if len(candidates):
        g = candidates.groupby("key").agg(messages=("id", "size"), authors=("author", "nunique"))
        hot = g[g["authors"] >= q["coordinated_min_authors"]]
        window = pd.Timedelta(seconds=q.get("coordinated_window_s", 180))
        policy = q["coordinated_policy"]
        found = []
        for key in hot.index:
            members = df[(df["key"] == key) & (df["exclusion"] == "")]
            burst = _burst_members(members, window, q["coordinated_min_authors"])
            if len(burst) == 0:
                continue
            found.append({"text": members.iloc[0]["clean"], "messages": int(len(burst)),
                          "authors": int(df.loc[burst, "author"].nunique())})
            if policy == "dedupe":
                df.loc[burst[1:], "exclusion"] = "coordinated"
            elif policy == "drop":
                df.loc[burst, "exclusion"] = "coordinated"
        clusters = sorted(found, key=lambda c: -c["messages"])
    df["counted"] = df["exclusion"] == ""
    return df, clusters


def _bucket_minutes(span_min: float, cfg_value) -> int:
    if cfg_value != "auto":
        return int(cfg_value)
    for b in (1, 2, 5, 10, 15, 30, 60):
        if span_min / b <= 60:
            return b
    return 120


def _share(counted: pd.DataFrame) -> dict:
    n = len(counted)
    c = counted["label"].value_counts()
    return {k: int(c.get(k, 0)) for k in ("positive", "neutral", "negative")} | {"n": n}


def _net(labels: pd.Series, n_boot: int) -> dict:
    vals = labels.map(SIGN).to_numpy(dtype=float)
    lo, hi = bootstrap_ci(vals, n_boot)
    return {"net": round(float(vals.mean() * 100) if len(vals) else 0.0, 1),
            "ci_low": round(lo * 100, 1), "ci_high": round(hi * 100, 1), "n": int(len(vals))}


def summarize(df: pd.DataFrame, cfg: dict, matcher: EntityMatcher, meta: dict) -> dict:
    a, q = cfg["analysis"], cfg["quality"]
    df, clusters = apply_quality(df, q)
    counted = df[df["counted"]]
    n_total, n_counted = len(df), len(counted)
    t0, t1 = df["ts"].min(), df["ts"].max()
    span_min = max((t1 - t0).total_seconds() / 60, 1.0)

    funnel = {"total": n_total}
    for reason in ("empty", "spam", "flood", "self_dupe", "coordinated"):
        funnel[reason] = int((df["exclusion"] == reason).sum())
    funnel["counted"] = n_counted

    # ---- sentiment overall -------------------------------------------------
    sent = _share(counted) | _net(counted["label"], a["bootstrap"])
    sent["mean_score"] = round(float(counted["sentiment"].mean()), 3) if n_counted else 0.0
    # sensitivity check: what if copy-paste repeats were kept? (a chanting crowd is real sentiment too)
    incl = df[df["exclusion"].isin(["", "coordinated"])]["label"].map(SIGN)
    sent["net_incl_repeats"] = round(float(incl.mean() * 100), 1) if len(incl) else 0.0

    # ---- entities ------------------------------------------------------------
    rows = []
    for r in counted.itertuples():
        for e in r.entities:
            rows.append((e["id"], r.author, e["l"], e["s"], r.ts))
    ent_df = pd.DataFrame(rows, columns=["id", "author", "label", "score", "ts"])
    entities = []
    if len(ent_df):
        for eid, g in ent_df.groupby("id"):
            if len(g) < a["min_entity_mentions"]:
                continue
            entities.append({
                "id": eid, "name": matcher.name(eid), "type": matcher.type(eid),
                "mentions": int(len(g)), "authors": int(g["author"].nunique()),
                **{k: int((g["label"] == k).sum()) for k in ("positive", "neutral", "negative")},
                **_net(g["label"], a["bootstrap"]),
            })
        entities.sort(key=lambda e: -e["mentions"])
    total_mentions = sum(e["mentions"] for e in entities if e["type"] == "person") or 1
    for e in entities:
        e["share_of_voice"] = round(100 * e["mentions"] / total_mentions, 1) if e["type"] == "person" else None
    by_type = {t: [e for e in entities if e["type"] == t][: a["top_n"]]
               for t in ("person", "country", "place", "topic")}

    # co-mentions of people
    pair_counts: Counter = Counter()
    for r in counted.itertuples():
        ids = sorted({e["id"] for e in r.entities if matcher.type(e["id"]) == "person"})
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                pair_counts[(ids[i], ids[j])] += 1
    co_mentions = [{"a": matcher.name(x), "b": matcher.name(y), "messages": c}
                   for (x, y), c in pair_counts.most_common(5)]

    # ---- timeline ------------------------------------------------------------
    bucket = _bucket_minutes(span_min, a["bucket_minutes"])
    freq = f"{bucket}min"
    all_v = df.set_index("ts").resample(freq, origin="start").size()
    cnt = counted.set_index("ts")
    timeline = []
    for ts, vol in all_v.items():
        sl = cnt[(cnt.index >= ts) & (cnt.index < ts + pd.Timedelta(minutes=bucket))]
        lab = sl["label"].map(SIGN)
        timeline.append({
            "t": ts.isoformat(), "volume": int(vol), "counted": int(len(sl)),
            "net": round(float(lab.mean() * 100), 1) if len(sl) >= 5 else None,
        })
    peaks = sorted(timeline, key=lambda x: -x["volume"])[:3]

    # ---- language, words, emoji, hashtags -----------------------------------
    lang = counted["lang"].value_counts().to_dict()
    word_df: Counter = Counter()
    for t in counted["clean"]:
        seen = set()
        for w in T.tokens(t):
            if w in STOP or w in matcher.alias_tokens or w.isdigit() or w in seen:
                continue
            if (w.isascii() and len(w) >= 3) or (not w.isascii() and len(w) >= 2):
                seen.add(w)
        word_df.update(seen)
    emoji_c = Counter(e for lst in counted["emojis"] for e in lst)
    tag_c = Counter(h for lst in counted["hashtags"] for h in lst)
    cands = discover_candidates(list(counted["clean"]), matcher.alias_tokens, STOP | COMMON_CAPS,
                                min_count=3, top_n=a["top_n"])

    # ---- samples (no author info) --------------------------------------------
    def samples(frame: pd.DataFrame, positive: bool, k: int = 3) -> list[str]:
        f = frame[(frame["clean"].str.len().between(20, 160))]
        f = f.sort_values("sentiment", ascending=not positive)
        return list(dict.fromkeys(f["clean"]))[:k]

    top_people = [e for e in entities if e["type"] == "person"][:2]
    entity_samples = {}
    for e in top_people:
        mine = counted[counted["entities"].apply(lambda L: any(x["id"] == e["id"] for x in L))]
        entity_samples[e["name"]] = {"positive": samples(mine, True), "negative": samples(mine, False)}

    supers = df[df["kind"] == "superchat"]
    super_info = {"count": int(len(supers)), "amounts": [str(x) for x in supers["amount"].dropna().head(10)]}

    synthetic = bool((df["source"] == "synthetic").any())
    low_n = n_counted < a["low_sample_n"]
    highlights = _highlights(sent, entities, funnel, clusters, peaks, bucket, low_n)

    return {
        "meta": {**meta, "synthetic": synthetic, "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                 "window_start": t0.isoformat(), "window_end": t1.isoformat(), "span_minutes": round(span_min, 1),
                 "bucket_minutes": bucket, "low_sample": low_n,
                 "sentiment_model": meta.get("sentiment_model", cfg["sentiment"]["backend"])},
        "funnel": funnel, "authors": int(counted["author"].nunique()),
        "sentiment": sent, "entities": by_type, "co_mentions": co_mentions,
        "timeline": timeline, "peaks": peaks, "languages": lang,
        "top_words": word_df.most_common(a["top_n"] + 5), "top_emojis": emoji_c.most_common(a["top_n"]),
        "top_hashtags": tag_c.most_common(a["top_n"]), "emerging_names": cands,
        "coordinated_clusters": clusters[:5], "samples": entity_samples,
        "overall_samples": {"positive": samples(counted, True), "negative": samples(counted, False)},
        "superchats": super_info, "highlights": highlights,
        "method": ("Counts are of messages (live chat or comments, per the source) after removing empty, spam, flooding, repeated and "
                   "copy-paste messages. Chat participants are not a representative sample of the public. "
                   "Net sentiment = %positive - %negative, with a bootstrap 95% interval."),
    }


def _highlights(sent, entities, funnel, clusters, peaks, bucket, low_n) -> list[str]:
    h = []
    if low_n:
        h.append(f"Small sample (n={sent['n']}): treat every number below as indicative only.")
    h.append(f"Net sentiment {sent['net']:+.1f} (95% CI {sent['ci_low']:+.1f} to {sent['ci_high']:+.1f}) "
             f"across {sent['n']:,} counted messages.")
    people = [e for e in entities if e["type"] == "person"]
    if len(people) >= 2:
        a, b = people[0], people[1]
        ratio = a["mentions"] / max(b["mentions"], 1)
        h.append(f"{a['name']} was mentioned {a['mentions']:,} times vs {b['name']} {b['mentions']:,} "
                 f"({ratio:.1f}x). Net sentiment: {a['net']:+.0f} vs {b['net']:+.0f}.")
    elif people:
        h.append(f"{people[0]['name']} was mentioned {people[0]['mentions']:,} times (net {people[0]['net']:+.0f}).")
    topics = [e for e in entities if e["type"] == "topic"]
    if topics:
        h.append(f"Top topic: {topics[0]['name']} ({topics[0]['mentions']:,} messages, net {topics[0]['net']:+.0f}).")
    removed = funnel["total"] - funnel["counted"]
    if funnel["total"]:
        h.append(f"{100 * removed / funnel['total']:.0f}% of raw messages were filtered "
                 f"(spam {funnel['spam']}, flooding {funnel['flood']}, repeats {funnel['self_dupe']}, "
                 f"copy-paste {funnel['coordinated']}).")
    if clusters:
        c = clusters[0]
        h.append(f"Burst of repeated text detected: \"{c['text'][:60]}\" posted {c['messages']}x by {c['authors']} accounts (counted once).")
        if abs(sent["net_incl_repeats"] - sent["net"]) >= 3:
            h.append(f"Sensitivity: keeping those repeats would move net sentiment from {sent['net']:+.0f} to "
                     f"{sent['net_incl_repeats']:+.0f}. Say which you used when you post.")
    if peaks and peaks[0]["volume"]:
        h.append(f"Activity peaked in the {bucket}-minute window starting {peaks[0]['t'][11:16]} UTC ({peaks[0]['volume']} messages).")
    return h
