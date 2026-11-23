"""HTML for the published site: a tabbed report page and an index with an "Analyze a video" panel.

Plain HTML/CSS plus a little vanilla JS (no frameworks, no CDN), so the pages work offline and from GitHub Pages.
Without JavaScript the report shows every section in one scroll.
"""
from __future__ import annotations

import html
import json

from .report import LOW_N, _b64, _local, _table, _tone_word, _words, tone_label

e = html.escape

CSS = """
:root{--bg:#f6f6f3;--panel:#fff;--ink:#14140f;--ink2:#5a5a52;--line:#e4e3dc;--accent:#3b4cca;
--pos:#2a9d6f;--neu:#9a9a94;--neg:#d64545;--posbg:#e3f4ec;--negbg:#fbe6e6;--neubg:#ecece8;--shadow:0 1px 2px rgba(0,0,0,.04)}
@media (prefers-color-scheme:dark){:root{--bg:#0e0e0d;--panel:#181817;--ink:#f1f0ec;--ink2:#b9b8ad;--line:#2b2b28;--accent:#8c98ff;
--posbg:#143327;--negbg:#3a1b1b;--neubg:#262624;--shadow:none}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.55 system-ui,-apple-system,"Segoe UI","Nirmala UI",sans-serif}
.wrap{max-width:980px;margin:0 auto;padding:0 16px}
.top{position:sticky;top:0;z-index:5;background:color-mix(in srgb,var(--bg) 88%,transparent);backdrop-filter:blur(8px);border-bottom:1px solid var(--line)}
.top .wrap{display:flex;align-items:center;justify-content:space-between;height:52px}
.brand{font-weight:700;text-decoration:none;color:var(--ink)}.brand b{color:var(--accent)}
a{color:var(--accent)}.ghost{font-size:14px;text-decoration:none}
h1{font-size:26px;line-height:1.25;margin:24px 0 6px}h2{font-size:19px;margin:0 0 10px}h3{font-size:15px;margin:18px 0 8px;color:var(--ink2);text-transform:uppercase;letter-spacing:.04em}
.meta,.sub{color:var(--ink2);font-size:14px}
.card,.panel>section{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:18px 20px;margin:14px 0;box-shadow:var(--shadow)}
.chip{display:inline-block;padding:4px 12px;border-radius:999px;font-weight:700;font-size:15px;background:var(--neubg)}
.chip.pos{background:var(--posbg);color:var(--pos)}.chip.neg{background:var(--negbg);color:var(--neg)}
.bar{display:flex;height:16px;border-radius:8px;overflow:hidden;gap:2px;background:var(--line);margin:14px 0 8px}
.bar span{display:block}.p{background:var(--pos)}.u{background:var(--neu)}.n{background:var(--neg)}
.legend{display:flex;flex-wrap:wrap;gap:4px 18px;font-size:14px}.legend i{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:6px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;margin-top:16px}
.kpi{border:1px solid var(--line);border-radius:12px;padding:12px 14px}.kpi b{display:block;font-size:26px;line-height:1.2}
.kpi span{color:var(--ink2);font-size:13px}
.tabs{display:flex;gap:4px;overflow-x:auto;border-bottom:1px solid var(--line);margin:18px 0 4px}
.tabs button{background:none;border:0;border-bottom:3px solid transparent;color:var(--ink2);font:inherit;font-weight:600;padding:10px 14px;cursor:pointer;white-space:nowrap}
.tabs button[aria-selected=true]{color:var(--ink);border-color:var(--accent)}
.js .panel{display:none}.js .panel.on{display:block}.tabs{display:none}.js .tabs{display:flex}
.note{background:var(--neubg);border-radius:10px;padding:10px 14px;font-size:14px;color:var(--ink2);margin:14px 0}
.warn,.demo{padding:10px 14px;border-radius:10px;font-weight:600;margin:12px 0}.warn{background:#fab219;color:#14140f}.demo{background:#e34948;color:#fff}
.share{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:16px;align-items:start}
figure{margin:0}img{max-width:100%;height:auto;border-radius:10px;display:block}
figcaption{margin-top:8px}.btn{display:inline-block;padding:8px 14px;border-radius:10px;background:var(--accent);color:#fff;text-decoration:none;font-weight:600;font-size:14px;border:0;cursor:pointer;font-family:inherit}
.btn.sec{background:var(--neubg);color:var(--ink)}
ul.clean{margin:0;padding-left:20px}ul.clean li{margin:6px 0}
table{border-collapse:collapse;width:100%;font-size:14px;display:block;overflow-x:auto}
th,td{text-align:left;padding:7px 10px;border-bottom:1px solid var(--line);white-space:nowrap}th{color:var(--ink2);font-weight:600}
.cols{display:grid;grid-template-columns:1fr 1fr;gap:16px}@media(max-width:640px){.cols{grid-template-columns:1fr}h1{font-size:22px}}
blockquote{margin:6px 0;padding:8px 12px;border-left:3px solid var(--line);background:var(--neubg);border-radius:0 8px 8px 0;font-size:14px}
footer{color:var(--ink2);font-size:13px;padding:24px 0 48px}
"""

TAB_JS = """(function(){var d=document;d.documentElement.classList.add('js');
var tabs=[].slice.call(d.querySelectorAll('[role=tab]')),panels=[].slice.call(d.querySelectorAll('.panel'));
function show(id){if(!d.getElementById(id))id='overview';
tabs.forEach(function(t){t.setAttribute('aria-selected',String(t.dataset.t===id))});
panels.forEach(function(p){p.classList.toggle('on',p.id===id)})}
tabs.forEach(function(t){t.addEventListener('click',function(){show(t.dataset.t);history.replaceState(null,'','#'+t.dataset.t)})});
show((location.hash||'#overview').slice(1))})();"""


def _split(se: dict) -> dict[str, int]:
    n = max(se["n"], 1)
    return {k: round(100 * se[k] / n) for k in ("positive", "neutral", "negative")}


def _bar(pct: dict, label: bool = True) -> str:
    return (f'<div class="bar" role="img" aria-label="positive {pct["positive"]}%, neutral {pct["neutral"]}%, '
            f'negative {pct["negative"]}%"><span class="p" style="width:{pct["positive"]}%"></span>'
            f'<span class="u" style="width:{pct["neutral"]}%"></span><span class="n" style="width:{pct["negative"]}%"></span></div>')


def _chip_class(se: dict) -> str:
    return "pos" if se["ci_low"] > 0 else "neg" if se["ci_high"] < 0 else ""


def _quote_list(items: list[str]) -> str:
    return "".join(f"<blockquote>{e(t)}</blockquote>" for t in items) or "<p class='sub'>None.</p>"


def render_report(s: dict, imgs: dict[str, bytes], cards: tuple[str, ...] = ()) -> str:
    m, se, w = s["meta"], s["sentiment"], _words(s)
    off = m.get("utc_offset_minutes", 330)
    pct = _split(se)
    people = sorted(s["entities"].get("person", []), key=lambda x: -x["mentions"])
    top_all = sorted((x for k in ("person", "topic") for x in s["entities"].get(k, [])), key=lambda x: -x["mentions"])
    img = lambda k, alt: f"<img alt='{e(alt)}' src='{_b64(imgs[k])}'>" if k in imgs else ""

    banner = ("<div class='demo'>DEMO DATA: synthetic messages. Do not publish these numbers.</div>"
              if m.get("synthetic") else "")
    banner += ("<div class='warn'>Small sample: numbers are indicative only.</div>" if m.get("low_sample") else "")

    top_kpi = (f"<div class='kpi'><b>{e(top_all[0]['name'])}</b><span>most mentioned · {top_all[0]['mentions']:,} messages "
               f"· {_tone_word(top_all[0])}</span></div>") if top_all else ""
    hero = f"""<section class="card hero">
<span class="chip {_chip_class(se)}">{e(tone_label(se))}</span>
{_bar(pct)}
<div class="legend"><span><i class="p"></i>Positive {pct['positive']}%</span><span><i class="u"></i>Neutral {pct['neutral']}%</span><span><i class="n"></i>Negative {pct['negative']}%</span></div>
<div class="kpis">
<div class="kpi"><b>{se['n']:,}</b><span>{w['msgs']} counted (of {s['funnel']['total']:,} fetched)</span></div>
<div class="kpi"><b>{se['net']:+.0f}</b><span>net score (positive minus negative) · likely {se['ci_low']:+.0f} to {se['ci_high']:+.0f}</span></div>
{top_kpi}</div>
<p class="note">A sample of {w['msgs']} scored by software, not a poll of the public. Sarcasm and slang are often misread,
so trust the direction more than the exact number.</p></section>"""

    pretty = {"summary": "Summary", "head_to_head": "Head to head", "timeline": "Timeline"}
    share = "".join(
        f"<figure><img alt='{e(pretty.get(c, c))} card' src='cards/{c}.png' loading='lazy'><figcaption>"
        f"<a class='btn' href='cards/{c}.png' download='{e(m['video_id'])}-{c}.png'>Download {e(pretty.get(c, c))}</a></figcaption></figure>"
        for c in cards)
    share_sec = (f"<section><h2>Share cards</h2><p class='sub'>Ready-to-post images with the sample size and a "
                 f"\"not a poll\" note on each.</p><div class='share'>{share}</div></section>") if cards else ""
    takeaways = "".join(f"<li>{e(x)}</li>" for x in s["highlights"])
    talked = "".join(f"<li><b>{e(x['name'])}</b>: {x['mentions']:,} mentions, {e(_tone_word(x))}</li>" for x in top_all[:6])
    overview = f"""{share_sec}<section><h2>Key takeaways</h2><ul class="clean">{takeaways}</ul></section>
{f'<section><h2>Most talked about</h2><ul class="clean">{talked}</ul></section>' if talked else ''}"""

    head = ["Name", "Mentions", w["who"].capitalize(), "Pos", "Neu", "Neg", "Net (95% CI)"]
    rows = lambda L: [[x["name"], x["mentions"], x["authors"], x["positive"], x["neutral"], x["negative"],
                       f"{x['net']:+.0f} ({x['ci_low']:+.0f} to {x['ci_high']:+.0f})"] for x in L]
    tables = "".join(f"<h3>{lab}</h3>{_table(rows(s['entities'][k]), head)}"
                     for k, lab in (("person", "People"), ("topic", "Topics"), ("country", "Countries"), ("place", "Places"))
                     if s["entities"].get(k))
    emerging = ", ".join(f"{e(n)} ({c})" for n, c in s["emerging_names"]) or "none"
    names = f"""<section><h2>People and topics</h2><p class="sub">Net score needs at least {LOW_N} messages to be meaningful;
smaller groups are marked "too few".</p>{img('people', 'people sentiment')}{img('topics', 'topic sentiment')}{tables}
<p class="sub">Names found in the {w['msgs']} but not in your name list yet (add to <code>ytpulse/data/entities.yaml</code>): {emerging}</p></section>"""

    timeline = f"<section><h2>Over time</h2>{img('timeline', 'volume and net sentiment over time')}</section>"

    samples = "".join(
        f"<h3>{e(name)}</h3><div class='cols'><div><b>Most positive</b>{_quote_list(d['positive'])}</div>"
        f"<div><b>Most negative</b>{_quote_list(d['negative'])}</div></div>" for name, d in s["samples"].items())
    ov = s["overall_samples"]
    words = ", ".join(f"{e(a)} ({c})" for a, c in s["top_words"][:15])
    emojis = " ".join(f"{e(a)}×{c}" for a, c in s["top_emojis"])
    tags = ", ".join(f"{e(a)} ({c})" for a, c in s["top_hashtags"]) or "none"
    langs = ", ".join(f"{e(k)} {v}" for k, v in s["languages"].items())
    messages = f"""<section><h2>What people wrote</h2><p><b>Top words:</b> {words}</p><p><b>Emoji:</b> {emojis}</p>
<p><b>Hashtags:</b> {tags}</p><p><b>Languages:</b> {langs}</p></section>
<section><h2>Sample messages</h2><p class="sub">No usernames. Read these before quoting any.</p>
<div class='cols'><div><b>Most positive overall</b>{_quote_list(ov['positive'])}</div><div><b>Most negative overall</b>{_quote_list(ov['negative'])}</div></div>{samples}</section>"""

    clusters = (_table([[c["text"][:80], c["messages"], c["authors"]] for c in s["coordinated_clusters"]],
                       ["Repeated text", "Messages", "Accounts"]) if s["coordinated_clusters"] else "<p>None detected.</p>")
    data = f"""<section><h2>Data quality</h2>{img('funnel', 'filtering funnel')}<h3>Copy-paste clusters</h3>{clusters}</section>
<section><h2>Method</h2><p>{e(s['method'])}</p><p class="sub">Model: {e(str(m.get('sentiment_model', '')))}. Generated {e(m['generated_at'][:16].replace('T', ' '))} UTC.</p></section>"""

    tab_defs = [("overview", "Overview", overview), ("people", "People & topics", names), ("timeline", "Timeline", timeline),
                ("messages", "Messages", messages), ("data", "Data & method", data)]
    tabs = "".join(f"<button role='tab' data-t='{i}' aria-selected='{str(k == 0).lower()}'>{e(t)}</button>"
                   for k, (i, t, _) in enumerate(tab_defs))
    panels = "".join(f"<div class='panel{' on' if k == 0 else ''}' id='{i}'>{body}</div>"
                     for k, (i, _, body) in enumerate(tab_defs))
    when = f"{_local(m['window_start'], off)} to {_local(m['window_end'], off)} {m.get('timezone_label', '')}"
    link = f"<a class='ghost' href='{e(m['url'])}' target='_blank' rel='noopener'>Watch video ↗</a>" if m.get("url") else ""
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{e(m.get('title', 'Sentiment report'))} · Sentiment Pulse</title>
<style>{CSS}</style></head><body>
<header class="top"><div class="wrap"><a class="brand" href="../">◐ <b>Sentiment</b> Pulse</a>{link}</div></header>
<main class="wrap"><h1>{e(m.get('title', 'Sentiment report'))}</h1>
<div class="meta">{e(m.get('channel', ''))} · {e(when)} · {s['authors']:,} {w['who']} · {e(w['src'])}</div>
{banner}{hero}<nav class="tabs" role="tablist">{tabs}</nav>{panels}
<footer>Made with ytpulse. Numbers describe this sample of {w['msgs']} only.</footer></main>
<script>{TAB_JS}</script></body></html>"""


# --------------------------------------------------------------------------- index
ANALYZE_JS = r"""(function(){
var root=document.getElementById('analyze'),repo=root.dataset.repo;
if(!repo){var o=location.hostname.split('.')[0],r=location.pathname.split('/')[1];repo=o+'/'+r}
var API='https://api.github.com/repos/'+repo,KEY='ytpulse_gh_token';
var $=function(id){return document.getElementById(id)},status=$('status'),form=$('form'),tokBox=$('tokbox');
function tok(){try{return localStorage.getItem(KEY)||''}catch(e){return ''}}
function setTok(v){try{v?localStorage.setItem(KEY,v):localStorage.removeItem(KEY)}catch(e){}}
function say(t,cls){status.className='note '+(cls||'');status.textContent=t;status.hidden=false}
function vid(u){var m=u.match(/(?:v=|youtu\.be\/|\/live\/|\/shorts\/|\/embed\/)([\w-]{11})/);return m?m[1]:(/^[\w-]{11}$/.test(u.trim())?u.trim():'')}
function hdr(){return{'Authorization':'Bearer '+tok(),'Accept':'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28'}}
function refreshTok(){var has=!!tok();if(has)tokBox.hidden=true;$('forget').hidden=!has}
refreshTok();
$('savetok').addEventListener('click',function(){var v=$('tok').value.trim();if(v){setTok(v);$('tok').value='';refreshTok();say('Token saved in this browser. Press Analyze.')}});
$('forget').addEventListener('click',function(){setTok('');refreshTok();say('Token removed from this browser.')});
function sleep(ms){return new Promise(function(r){setTimeout(r,ms)})}
async function waitReport(id){for(var i=0;i<30;i++){try{var r=await fetch(id+'/report.html',{method:'HEAD',cache:'no-store'});if(r.ok)return true}catch(e){}await sleep(10000)}return false}
form.addEventListener('submit',async function(ev){
 ev.preventDefault();var url=$('url').value.trim(),id=vid(url);
 if(!id){say('That does not look like a YouTube link.','bad');return}
 if(!tok()){tokBox.hidden=false;say('One-time setup: paste a GitHub token below (steps shown), then press Analyze again.');return}
 var go=$('go');go.disabled=true;var t0=Date.now()-60000;
 try{
  var r=await fetch(API+'/actions/workflows/analyze.yml/dispatches',{method:'POST',headers:hdr(),
   body:JSON.stringify({ref:'main',inputs:{url:url,max_comments:$('max').value,publish:'true'}})});
  if(r.status===401||r.status===403||r.status===404){say('GitHub refused the request ('+r.status+'). The token needs Actions: Read and write on '+repo+'.','bad');go.disabled=false;return}
  if(r.status!==204){say('Could not start the analysis (HTTP '+r.status+').','bad');go.disabled=false;return}
  say('Started. Reading comments and scoring them takes about 3-5 minutes.');
  var run=null;
  for(var i=0;i<120;i++){await sleep(8000);
   var q=await fetch(API+'/actions/workflows/analyze.yml/runs?event=workflow_dispatch&per_page=5',{headers:hdr()});
   if(!q.ok)continue;var j=await q.json();
   run=(j.workflow_runs||[]).find(function(x){return new Date(x.created_at).getTime()>=t0})||null;
   if(run){say('Status: '+(run.status==='completed'?run.conclusion:run.status.replace('_',' '))+' ...');if(run.status==='completed')break}}
  if(!run||run.conclusion!=='success'){say('The run did not succeed. Open the run to see why.','bad');
   if(run){var a=document.createElement('a');a.href=run.html_url;a.textContent=' View run';a.target='_blank';status.appendChild(a)}go.disabled=false;return}
  say('Analysis done. Publishing the page (about a minute) ...');
  if(await waitReport(id)){say('Ready.','ok');var l=document.createElement('a');l.href=id+'/report.html';l.className='btn';l.textContent='Open report';l.style.marginLeft='10px';status.appendChild(l)}
  else say('Finished, but the page is not live yet. Reload this page in a minute.');
 }catch(err){say('Network error: '+err.message,'bad')}
 go.disabled=false});
})();"""

INDEX_CSS = """
.hero-i{padding:28px 0 8px}.hero-i h1{font-size:30px;margin:0 0 6px}
#analyze{margin:18px 0}#analyze form{display:flex;flex-wrap:wrap;gap:10px;margin-top:10px}
#analyze input[type=text],#analyze input[type=password],#analyze select{font:inherit;padding:10px 12px;border-radius:10px;border:1px solid var(--line);background:var(--bg);color:var(--ink)}
#url{flex:1 1 320px;min-width:0}#analyze .btn{padding:10px 18px;font-size:15px}
#analyze .btn[disabled]{opacity:.6;cursor:wait}
#status{margin-top:12px}#status.bad{background:var(--negbg);color:var(--neg)}#status.ok{background:var(--posbg);color:var(--pos)}
details.setup{margin-top:10px;font-size:14px;color:var(--ink2)}details.setup ol{padding-left:20px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(290px,1fr));gap:14px;margin-top:12px}
.rcard{display:block;text-decoration:none;color:inherit;background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:16px;box-shadow:var(--shadow)}
.rcard:hover{border-color:var(--accent)}.rcard h3{margin:10px 0 2px;font-size:16px;text-transform:none;letter-spacing:0;color:var(--ink);line-height:1.35}
.rcard .bar{margin:12px 0 6px;height:10px}.rcard .sub{font-size:13px}
.empty{padding:28px;text-align:center;color:var(--ink2);border:1px dashed var(--line);border-radius:14px}
"""

SETUP_STEPS = """<details class="setup"><summary>One-time setup: how to get the token</summary><ol>
<li>Open <a href="https://github.com/settings/personal-access-tokens/new" target="_blank" rel="noopener">GitHub → New fine-grained token</a>.</li>
<li>Repository access: <b>Only select repositories</b>, pick this repository.</li>
<li>Permissions → Repository → <b>Actions: Read and write</b>. Nothing else.</li>
<li>Generate, copy, paste it above. It is stored only in this browser and sent only to api.github.com.</li></ol>
<p>Prefer not to use a token? Open the <a id="alt" href="#" target="_blank" rel="noopener">Actions page</a> and press "Run workflow".</p></details>"""


def render_index(items: list[dict], repo: str = "") -> str:
    cards = ""
    for it in items:
        pct = it["pct"]
        cards += (f"<a class='rcard' href='{e(it['id'])}/report.html'>"
                  f"<span class='chip {it['chip']}'>{e(it['tone'])}</span><h3>{e(it['title'])}</h3>"
                  f"<div class='sub'>{e(it['channel'])}</div>{_bar(pct)}"
                  f"<div class='sub'>{pct['positive']}% positive · {pct['negative']}% negative · net {it['net']:+.0f}<br>"
                  f"{it['n']:,} {e(it['msgs'])} · {e(it['date'])}</div></a>")
    body = f"<div class='grid'>{cards}</div>" if cards else "<div class='empty'>No reports yet. Analyze your first video above.</div>"
    alt = f"https://github.com/{repo}/actions/workflows/analyze.yml" if repo else "#"
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Sentiment Pulse</title>
<style>{CSS}{INDEX_CSS}</style></head><body>
<header class="top"><div class="wrap"><span class="brand">◐ <b>Sentiment</b> Pulse</span>
{f"<a class='ghost' href='https://github.com/{e(repo)}' target='_blank' rel='noopener'>GitHub ↗</a>" if repo else ""}</div></header>
<main class="wrap"><div class="hero-i"><h1>YouTube comment sentiment</h1>
<p class="sub">Paste a video link. About five minutes later you get a plain-language report and share cards.</p></div>
<section class="card" id="analyze" data-repo="{e(repo)}"><b>Analyze a video</b>
<form id="form"><input id="url" type="text" placeholder="https://www.youtube.com/watch?v=..." aria-label="YouTube link" required>
<select id="max" aria-label="Max comments"><option value="1000">1,000 comments</option><option value="3000" selected>3,000 comments</option><option value="5000">5,000 comments</option></select>
<button class="btn" id="go" type="submit">Analyze</button></form>
<div id="tokbox" hidden><p class="sub" style="margin:12px 0 6px">GitHub token (stored only in this browser):</p>
<div style="display:flex;gap:8px;flex-wrap:wrap"><input id="tok" type="password" autocomplete="off" placeholder="github_pat_..." style="flex:1 1 260px;min-width:0">
<button class="btn sec" id="savetok" type="button">Save token</button></div>{SETUP_STEPS.replace('href="#" target', f'href="{alt}" target')}</div>
<p style="margin:8px 0 0"><a id="forget" href="#" hidden onclick="return false" class="sub">Remove saved token</a></p>
<div id="status" class="note" hidden role="status"></div></section>
<h2>Reports</h2>{body}
<footer>Reports are samples of comments scored by software, not polls of the public.</footer></main>
<script>{ANALYZE_JS}</script></body></html>"""
