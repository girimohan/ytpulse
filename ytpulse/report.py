"""Render a summary dict into report.json, a self-contained report.html and share-ready PNG cards.

Colour: sentiment is a diverging pair (blue = positive, red = negative, grey = neutral);
identity/magnitude uses a single violet so colour never means two things on one chart.
Cards are dark-surface and carry a methodology footer (n, filtering, "chat sample").
"""
from __future__ import annotations

import base64
import html
import io
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import font_manager  # noqa: E402

logging.getLogger("matplotlib.font_manager").setLevel(logging.ERROR)

BG, PANEL = "#1a1a19", "#242422"
INK, INK2, MUTED, GRID = "#f0efec", "#c3c2b7", "#898781", "#2c2c2a"
POS, NEU, NEG, MAG = "#3987e5", "#6b6a66", "#e66767", "#9085e9"

_avail = {f.name for f in font_manager.fontManager.ttflist}
plt.rcParams["font.family"] = [f for f in ("Segoe UI", "Nirmala UI", "Helvetica Neue", "Arial") if f in _avail] + ["DejaVu Sans"]
plt.rcParams.update({"text.color": INK, "axes.labelcolor": INK2, "xtick.color": MUTED, "ytick.color": MUTED,
                     "axes.edgecolor": GRID, "figure.facecolor": BG, "axes.facecolor": BG, "savefig.facecolor": BG})


def _local(iso: str, offset_min: int) -> str:
    dt = datetime.fromisoformat(iso).astimezone(timezone(timedelta(minutes=offset_min)))
    return dt.strftime("%H:%M")


def _fmt_net(v: float) -> str:
    return f"{v:+.0f}"


def _png(fig) -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=fig.dpi)
    plt.close(fig)
    return buf.getvalue()


LOW_N = 30  # below this an entity's net score is too noisy to print as a headline number


def _words(s: dict) -> dict:
    """Wording that matches the data source: live chat vs ordinary video comments."""
    if s["meta"].get("source_kind") == "comment":
        return {"msgs": "comments", "who": "commenters", "src": "YouTube comments", "head": "COMMENT PULSE",
                "time": "COMMENTS OVER TIME", "h2h": "Who got more attention?"}
    return {"msgs": "live-chat messages", "who": "chatters", "src": "YouTube live chat", "head": "LIVE CHAT PULSE",
            "time": "CHAT OVER TIME", "h2h": "Who dominated the chat?"}


def _net_label(e: dict) -> str:
    return f"net {_fmt_net(e['net'])}" if e["n"] >= LOW_N else f"n={e['n']} · too few for a net score"


def _footer(fig, s: dict, y: float = 0.025) -> None:
    m, f = s["meta"], s["funnel"]
    w = _words(s)
    left = (f"Sample: {s['sentiment']['n']:,} of {f['total']:,} {w['msgs']} after spam / flood / copy-paste "
            f"filtering  ·  not a representative poll")
    fig.text(0.05, y + 0.022, left, color=MUTED, fontsize=9.5, ha="left", va="bottom")
    fig.text(0.05, y, f"Source: {w['src']} · {m.get('channel', '')} · {m.get('title', '')[:70]}",
             color=MUTED, fontsize=9.5, ha="left", va="bottom")
    if m.get("synthetic"):
        fig.text(0.5, 0.5, "DEMO DATA · SYNTHETIC", color="#ffffff", alpha=0.10, fontsize=54, rotation=30,
                 ha="center", va="center", fontweight="bold")


def _stack(ax, y, neg, neu, pos, height=0.55):
    """Single normalised diverging bar: negative | neutral | positive, 2px surface gaps."""
    tot = max(neg + neu + pos, 1)
    x = 0.0
    for v, c in ((neg, NEG), (neu, NEU), (pos, POS)):
        w = 100 * v / tot
        if w > 0:
            ax.barh(y, w, left=x, height=height, color=c, edgecolor=BG, linewidth=1.5)
            if w >= 9:
                ax.text(x + w / 2, y, f"{w:.0f}%", ha="center", va="center", color="#ffffff", fontsize=10, fontweight="bold")
        x += w


def _style(ax) -> None:
    for sp in ax.spines.values():
        sp.set_visible(False)
    ax.tick_params(length=0)


# ---------------------------------------------------------------- charts
def fig_sentiment(s: dict):
    se = s["sentiment"]
    fig, ax = plt.subplots(figsize=(9, 1.9), dpi=110)
    _stack(ax, 0, se["negative"], se["neutral"], se["positive"], height=0.7)
    ax.set_xlim(0, 100), ax.set_ylim(-0.6, 0.6), ax.axis("off")
    for x, lab, c in ((0, "Negative", NEG), (50, "Neutral", INK2), (100, "Positive", POS)):
        ax.text(x, -0.55, lab, ha=("left", "center", "right")[(0, 50, 100).index(x)], color=INK2, fontsize=10, va="top")
    fig.subplots_adjust(left=0.01, right=0.99, top=0.95, bottom=0.2)
    return fig


def fig_timeline(s: dict):
    fig = plt.figure(figsize=(9, 5.2), dpi=110)
    _timeline_axes(fig, s, (0.08, 0.10, 0.90, 0.86))
    return fig


def _timeline_axes(fig, s: dict, box: tuple[float, float, float, float], fs: float = 9) -> None:
    """Two stacked panels on ONE shared x-axis (volume above, net sentiment below): no dual y-axis."""
    l, b, w, h = box
    a1 = fig.add_axes([l, b + h * 0.53, w, h * 0.47])
    a2 = fig.add_axes([l, b, w, h * 0.47], sharex=a1)
    plt.setp(a1.get_xticklabels(), visible=False)
    tl, off = s["timeline"], s["meta"].get("utc_offset_minutes", 330)
    labels = [_local(p["t"], off) for p in tl]
    xs = list(range(len(tl)))
    a1.bar(xs, [p["volume"] for p in tl], color=MAG, width=0.8)
    a1.set_ylabel("messages / bucket", fontsize=fs)
    pts = [(i, p["net"]) for i, p in enumerate(tl) if p["net"] is not None]
    if pts:
        px, py = zip(*pts)
        a2.axhline(0, color=GRID, lw=1.2)
        a2.plot(px, py, color=INK, lw=2, solid_capstyle="round")
        a2.scatter(px, py, s=[28] * len(px), c=[POS if v >= 0 else NEG for v in py], edgecolors=BG, linewidths=1.5, zorder=3)
    a2.set_ylabel("net sentiment", fontsize=fs)
    a2.set_ylim(-100, 100)
    step = max(1, len(tl) // 8)
    a2.set_xticks(xs[::step]), a2.set_xticklabels(labels[::step], fontsize=fs)
    a2.set_xlabel(f"{s['meta'].get('timezone_label', 'local')} time", fontsize=fs)
    for a in (a1, a2):
        _style(a)
        a.tick_params(labelsize=fs)
        a.grid(axis="y", color=GRID, lw=0.8)
        a.set_axisbelow(True)


def fig_entities(items: list[dict], title: str):
    items = items[:8][::-1]
    h = 0.55 * len(items) + 1.2
    fig, ax = plt.subplots(figsize=(9, max(h, 2.2)), dpi=110)
    for i, e in enumerate(items):
        _stack(ax, i, e["negative"], e["neutral"], e["positive"])
        ax.text(-1.5, i, e["name"], ha="right", va="center", color=INK, fontsize=10.5)
        ax.text(101.5, i, f"{e['mentions']:,}  ·  net {_fmt_net(e['net'])}", ha="left", va="center", color=INK2, fontsize=10)
    ax.set_xlim(0, 100), ax.set_ylim(-0.6, len(items) - 0.4), ax.axis("off")
    ax.set_title(title, loc="left", color=INK, fontsize=12, pad=8, x=-0.3)
    fig.subplots_adjust(left=0.28, right=0.80, top=0.88, bottom=0.04)
    return fig


def fig_funnel(s: dict):
    f = s["funnel"]
    rows = [("All messages", f["total"]), ("Empty", f["empty"]), ("Spam / links", f["spam"]),
            ("Flooding", f["flood"]), ("Same-user repeats", f["self_dupe"]),
            ("Copy-paste duplicates", f["coordinated"]), ("Counted", f["counted"])]
    fig, ax = plt.subplots(figsize=(9, 3.2), dpi=110)
    for i, (lab, v) in enumerate(rows[::-1]):
        ax.barh(i, v, color=MAG if lab not in ("All messages", "Counted") else INK2, height=0.55)
        ax.text(-max(f["total"], 1) * 0.02, i, lab, ha="right", va="center", fontsize=10, color=INK)
        ax.text(v + max(f["total"], 1) * 0.01, i, f"{v:,}", ha="left", va="center", fontsize=10, color=INK2)
    ax.set_xlim(0, f["total"] * 1.12 or 1), ax.axis("off")
    fig.subplots_adjust(left=0.27, right=0.97, top=0.97, bottom=0.03)
    return fig


# ---------------------------------------------------------------- cards
def _card(w_px: int, h_px: int):
    fig = plt.figure(figsize=(w_px / 100, h_px / 100), dpi=100)
    fig.patch.set_facecolor(BG)
    return fig


def card_summary(s: dict) -> bytes:
    fig = _card(1080, 1350)
    m, se = s["meta"], s["sentiment"]
    w = _words(s)
    fig.text(0.05, 0.945, w["head"], color=MAG, fontsize=15, fontweight="bold")
    title = m.get("title", "")
    fig.text(0.05, 0.905, title if len(title) < 52 else title[:50] + "…", color=INK, fontsize=24, fontweight="bold")
    fig.text(0.05, 0.875, f"{m.get('channel', '')} · {se['n']:,} counted {w['msgs']} · {s['authors']:,} {w['who']}",
             color=INK2, fontsize=13)
    # hero number
    fig.text(0.05, 0.775, _fmt_net(se["net"]), color=INK, fontsize=96, fontweight="bold")
    fig.text(0.05, 0.745, f"net sentiment  (95% CI {_fmt_net(se['ci_low'])} to {_fmt_net(se['ci_high'])})",
             color=INK2, fontsize=14)
    ax = fig.add_axes([0.05, 0.655, 0.9, 0.07])
    _stack(ax, 0, se["negative"], se["neutral"], se["positive"], height=0.8)
    ax.set_xlim(0, 100), ax.set_ylim(-0.6, 0.6), ax.axis("off")
    for x, lab, ha in ((0.05, "Negative", "left"), (0.5, "Neutral", "center"), (0.95, "Positive", "right")):
        fig.text(x, 0.642, lab, color=INK2, fontsize=11, ha=ha)
    # people
    people = [e for e in s["entities"]["person"] if e["n"] >= 10][:4]
    if people:
        fig.text(0.05, 0.585, "WHO PEOPLE ARE TALKING ABOUT", color=MUTED, fontsize=12, fontweight="bold")
        ax2 = fig.add_axes([0.28, 0.40, 0.46, 0.17])
        for i, e in enumerate(people[::-1]):
            _stack(ax2, i, e["negative"], e["neutral"], e["positive"], height=0.6)
            fig.text(0.27, 0.40 + 0.17 * (i + 0.5) / len(people), e["name"], color=INK, fontsize=13, ha="right", va="center")
            fig.text(0.755, 0.40 + 0.17 * (i + 0.5) / len(people),
                     f"{e['mentions']:,}  ·  {_net_label(e) if e['n'] >= LOW_N else 'low sample'}",
                     color=INK2, fontsize=12, ha="left", va="center")
        ax2.set_xlim(0, 100), ax2.set_ylim(-0.5, len(people) - 0.5), ax2.axis("off")
    topics = [e for e in s["entities"]["topic"] if e["n"] >= 8][:5]
    if topics:
        fig.text(0.05, 0.335, "TOP TOPICS", color=MUTED, fontsize=12, fontweight="bold")
        for i, e in enumerate(topics):
            y = 0.305 - i * 0.043
            fig.text(0.05, y, f"{i + 1}. {e['name']}", color=INK, fontsize=14, va="center")
            fig.text(0.95, y, f"{e['mentions']:,} msgs · " + (_net_label(e) if e["n"] >= LOW_N else "low sample"),
                     color=INK2, fontsize=12, ha="right", va="center")
    _footer(fig, s, y=0.03)
    return _png(fig)


def card_h2h(s: dict) -> bytes | None:
    people = s["entities"]["person"][:2]
    if len(people) < 2 or min(e["n"] for e in people) < LOW_N:
        return None  # a head-to-head built on a handful of messages is not worth posting
    w = _words(s)
    fig = _card(1080, 1080)
    fig.text(0.05, 0.93, "HEAD TO HEAD", color=MAG, fontsize=15, fontweight="bold")
    fig.text(0.05, 0.885, w["h2h"], color=INK, fontsize=28, fontweight="bold")
    for k, e in enumerate(people):
        x0 = 0.05 + k * 0.48
        fig.text(x0, 0.80, e["name"], color=INK, fontsize=20, fontweight="bold")
        fig.text(x0, 0.69, f"{e['mentions']:,}", color=INK, fontsize=64, fontweight="bold")
        fig.text(x0, 0.655, f"mentions · {e['authors']:,} {w['who']}", color=INK2, fontsize=12)
        fig.text(x0, 0.56, _fmt_net(e["net"]), color=INK, fontsize=64, fontweight="bold")
        fig.text(x0, 0.525, f"net sentiment (CI {_fmt_net(e['ci_low'])} to {_fmt_net(e['ci_high'])})", color=INK2, fontsize=12)
        ax = fig.add_axes([x0, 0.40, 0.42, 0.07])
        _stack(ax, 0, e["negative"], e["neutral"], e["positive"], height=0.8)
        ax.set_xlim(0, 100), ax.set_ylim(-0.6, 0.6), ax.axis("off")
        fig.text(x0, 0.385, "negative · neutral · positive", color=MUTED, fontsize=10)
    co = s["co_mentions"]
    if co:
        fig.text(0.05, 0.27, f"Mentioned together in {co[0]['messages']:,} messages", color=INK2, fontsize=14)
    _footer(fig, s, y=0.04)
    return _png(fig)


def card_timeline(s: dict) -> bytes:
    fig = _card(1600, 900)
    m = s["meta"]
    fig.text(0.04, 0.93, _words(s)["time"], color=MAG, fontsize=16, fontweight="bold")
    fig.text(0.04, 0.88, (m.get("title", "")[:80]), color=INK, fontsize=22, fontweight="bold")
    _timeline_axes(fig, s, (0.07, 0.14, 0.90, 0.68), fs=12)
    _footer(fig, s, y=0.02)
    return _png(fig)


# ---------------------------------------------------------------- html
def _b64(png: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(png).decode()


def _table(rows: list[list], head: list[str]) -> str:
    th = "".join(f"<th>{html.escape(str(h))}</th>" for h in head)
    body = "".join("<tr>" + "".join(f"<td>{html.escape(str(c))}</td>" for c in r) + "</tr>" for r in rows)
    return f"<table><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table>"


def _tone_word(e: dict) -> str:
    if e["n"] < LOW_N:
        return "too few messages to judge"
    return "mostly positive" if e["net"] >= 10 else "mostly negative" if e["net"] <= -10 else "mixed"


def tone_label(se: dict) -> str:
    lo, hi = se["ci_low"], se["ci_high"]
    return ("Positive-leaning" if lo >= 5 else "Negative-leaning" if hi <= -5 else
            "Slightly positive" if lo > 0 else "Slightly negative" if hi < 0 else "Mixed, no clear lean")


def write_report(s: dict, out_dir: str | Path) -> dict[str, Path]:
    out = Path(out_dir)
    (out / "cards").mkdir(parents=True, exist_ok=True)
    imgs = {"sentiment": _png(fig_sentiment(s)), "timeline": _png(fig_timeline(s)), "funnel": _png(fig_funnel(s))}
    if s["entities"]["person"]:
        imgs["people"] = _png(fig_entities(s["entities"]["person"], "People: share of positive / neutral / negative, mentions, net"))
    if s["entities"]["topic"]:
        imgs["topics"] = _png(fig_entities(s["entities"]["topic"], "Topics"))
    paths = {"json": out / "report.json", "html": out / "report.html"}
    paths["json"].write_text(json.dumps(s, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    cards = {"summary": card_summary(s)}
    h2h = card_h2h(s)
    if h2h:
        cards["head_to_head"] = h2h
    cards["timeline"] = card_timeline(s)
    from .web import render_report  # web imports helpers from this module
    paths["html"].write_text(render_report(s, imgs, tuple(cards)), encoding="utf-8")
    for stale in (out / "cards").glob("*.png"):  # a card from an older run (e.g. head-to-head) must not linger
        stale.unlink()
    for name, data in cards.items():
        p = out / "cards" / f"{name}.png"
        p.write_bytes(data)
        paths[f"card_{name}"] = p
    return paths
