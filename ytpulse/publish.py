"""Helpers used by the GitHub Actions workflow: a short run summary and a Pages index of reports."""
from __future__ import annotations

import html
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


def build_index(site_dir: str | Path) -> Path:
    """Write site_dir/index.html listing every <video_id>/report.json, newest first."""
    site = Path(site_dir)
    items = []
    for js in site.glob("*/report.json"):
        s = json.loads(js.read_text(encoding="utf-8"))
        items.append((s["meta"]["generated_at"], js.parent.name, s))
    items.sort(reverse=True)
    rows = "".join(
        f"<li><a href='{html.escape(vid)}/report.html'>{html.escape(s['meta']['title'])}</a>"
        f"<span>{html.escape(tone_label(s['sentiment']))} · net {s['sentiment']['net']:+.0f} · "
        f"n={s['sentiment']['n']:,} · {html.escape(gen[:10])}</span></li>"
        for gen, vid, s in items)
    out = site / "index.html"
    out.write_text(f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Sentiment reports</title>
<style>:root{{--bg:#f9f9f7;--ink:#0b0b0b;--ink2:#52514e;--line:#e1e0d9}}
@media(prefers-color-scheme:dark){{:root{{--bg:#0d0d0d;--ink:#f0efec;--ink2:#c3c2b7;--line:#2c2c2a}}}}
body{{margin:0;background:var(--bg);color:var(--ink);font:16px/1.5 system-ui,"Segoe UI","Nirmala UI",sans-serif}}
main{{max-width:760px;margin:0 auto;padding:24px 16px 64px}}h1{{font-size:24px}}
ul{{list-style:none;padding:0}}li{{padding:12px 0;border-bottom:1px solid var(--line)}}
a{{color:inherit;font-weight:600}}span{{display:block;color:var(--ink2);font-size:14px}}</style></head>
<body><main><h1>Sentiment reports</h1>{'<ul>' + rows + '</ul>' if rows else '<p>No reports yet.</p>'}</main></body></html>""",
                   encoding="utf-8")
    (site / ".nojekyll").write_text("", encoding="utf-8")
    return out
