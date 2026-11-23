"""Helpers used by the GitHub Actions workflow: a short run summary and a Pages index of reports."""
from __future__ import annotations

import json
from pathlib import Path

from .report import LOW_N, _tone_word, tone_label


def summary_markdown(report_json: str | Path, page_url: str = "") -> str:
    s = json.loads(Path(report_json).read_text(encoding="utf-8"))
    se, f, m = s["sentiment"], s["funnel"], s["meta"]
    n = max(se["n"], 1)
    pct = {k: round(100 * se[k] / n) for k in ("positive", "neutral", "negative")}
    lines = [f"## {tone_label(se)}: {m['title']}", "",
             f"**{pct['positive']}% positive · {pct['neutral']}% neutral · {pct['negative']}% negative** "
             f"(net {se['net']:+.0f}, likely {se['ci_low']:+.0f} to {se['ci_high']:+.0f}) "
             f"from {se['n']:,} of {f['total']:,} {('comments' if m.get('source_kind') == 'comment' else 'messages')} "
             f"after filtering.", ""]
    rows = sorted((e for k in ("person", "topic") for e in s["entities"].get(k, [])), key=lambda e: -e["mentions"])[:5]
    if rows:
        lines += ["| Most talked about | Mentions | Tone |", "|---|---:|---|"]
        lines += [f"| {e['name']} | {e['mentions']:,} | {_tone_word(e)} |" for e in rows]
        lines.append("")
    if page_url:
        lines += [f"**[Open the full report]({page_url})**  (share cards are on that page)", ""]
    lines += ["The full report and share cards are also attached to this run as the `report` artifact.", "",
              "_A sample of comments scored by software, not a poll. Sarcasm and slang are often misread._"]
    if se["n"] < max(LOW_N, 100):
        lines.insert(1, f"> Small sample (n={se['n']}): treat as anecdotal.\n")
    return "\n".join(lines) + "\n"


def build_index(site_dir: str | Path, repo: str = "") -> Path:
    """Write site_dir/index.html listing every <video_id>/report.json, newest first."""
    from .web import _chip_class, _split, render_index
    site = Path(site_dir)
    items = []
    for js in site.glob("*/report.json"):
        s = json.loads(js.read_text(encoding="utf-8"))
        se, m = s["sentiment"], s["meta"]
        items.append({"gen": m["generated_at"], "id": js.parent.name, "title": m["title"], "channel": m.get("channel", ""),
                      "tone": tone_label(se), "chip": _chip_class(se), "pct": _split(se), "net": se["net"], "n": se["n"],
                      "msgs": "comments" if m.get("source_kind") == "comment" else "messages", "date": m["generated_at"][:10]})
    items.sort(key=lambda x: x["gen"], reverse=True)
    out = site / "index.html"
    out.write_text(render_index(items, repo), encoding="utf-8")
    (site / ".nojekyll").write_text("", encoding="utf-8")
    return out
