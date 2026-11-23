# ytpulse

Live-chat and comment sentiment pipeline for YouTube. Captures chat while a stream is live, cleans it,
scores sentiment, extracts and counts names/topics, and produces a report plus share-ready images.

```
YouTube Data API ──► ingest (thread) ──► SQLite (WAL) ──► enrich ──► aggregate ──► report.html
 liveChat / comments     poll, retry,       raw messages     clean, lang,   quality funnel,   report.json
 replay JSONL            quota-aware        + salted author  spam flags,    bootstrap CIs,    cards/*.png
 synthetic (demo)        resume cursor      hashes           sentiment,     timeline
                                                             entities
```

## Use it

Paste a link, get a report. Works for live streams and regular videos.

```powershell
.\analyze.ps1 "https://www.youtube.com/watch?v=VIDEO_ID"
```

First run only: it creates `.venv`, installs the dependencies (including the multilingual model, ~1 GB, downloaded
once) and opens `.env` so you can paste your **YouTube Data API v3 key** (get one in Google Cloud console: enable the
API, then Credentials, then API key). After that each run takes about a minute.

What it does automatically:

* **Normal video** -> fetches the newest comments (default cap 5,000; `--max-comments N`).
* **Live now** -> captures live chat until you press Ctrl-C (or `--minutes N`). Chat replay is not available through
  the API, so live chat has to be captured while the stream is on. `--comments` uses comments instead.
* Writes `reports/<video_id>/report.html`, `report.json` and share cards in `cards/`, prints a short summary and
  opens the report.

```powershell
.\analyze.ps1 <url> --no-open --max-comments 2000
.\.venv\Scripts\python.exe -m ytpulse purge --days 30        # dry run; add --yes to delete old data
.\.venv\Scripts\python.exe -m ytpulse demo                   # synthetic data, no API key needed
.\.venv\Scripts\python.exe -m pytest -q                      # tests
```

Without the ML extras it falls back to the lexicon backend and warns you; that backend is weak on Nepali and Hindi.

**Names are per video.** `ytpulse/data/entities.yaml` lists who/what to count (people, parties, topics, with
Devanagari and Latin spellings). Add the guest and topics of the video you are analysing; the report's "emerging
names" section suggests candidates you have not listed yet. After editing, rebuild with
`python -m ytpulse report --db data/<id>.db --reenrich`.

### From GitHub (no setup on your machine)

1. Repo **Settings > Secrets and variables > Actions > New repository secret**: name `YOUTUBE_API_KEY`, value your key.
2. **Settings > Pages**: Source = *Deploy from a branch*, branch `gh-pages`, folder `/ (root)` (the branch appears after the
   first run; GitHub Pages on a private repo needs a paid plan, otherwise make the repo public or just use the download).
3. **Actions > analyze > Run workflow**, paste the link. When it finishes (about 5 minutes) the run page shows a
   short summary with a link to the full report; the same files are attached as the `report` artifact (zip with
   `report.html` and `cards/*.png`) to download and post.

Reports are published at `https://<user>.github.io/<repo>/<video_id>/report.html`, with an index at the root.
Untick *publish* to keep a report as a download only. The workflow reads comments only (live chat needs a
long-running local session, not a CI job).

### Lower-level commands

```powershell
python -m ytpulse run --video <url> --source live        # explicit source: live | comments | jsonl | synthetic
python -m ytpulse report --db data/<id>.db               # rebuild a report from stored data
```

## Choosing the sentiment backend (measure it, don't guess)

```powershell
pip install -e ".[ml]"      # note: sentencepiece 0.2.3 clashes with protobuf 6.x; the extra pins <0.2.3
python -m ytpulse analyze <url> --backend hybrid
```

Backends: `lexicon` (fast, transparent baseline), `transformer`
(`cardiffnlp/twitter-xlm-roberta-base-sentiment`, ~24 s per 1,300 messages on CPU), `hybrid` (blend).

**No backend has been validated on real Hindi/Nepali/Hinglish chat yet.** On the built-in synthetic data the
lexicon scores highest, but that data was written alongside the lexicon, so it proves nothing about real chat.
Before you publish numbers, label ~300 real messages from your first capture (CSV: `text,label`) and run:

```powershell
python -m ytpulse eval labeled.csv
```

and use whichever backend wins on *your* data. Expect weaker results on sarcasm and romanized Hinglish.

## What it measures

| Output | How |
|---|---|
| Net sentiment (%pos - %neg) | per-message score, bootstrap 95% CI, n always shown |
| Name counts + share of voice | YAML gazetteer, Devanagari/Nepali suffix aware (`बालेनले`, `मोदीजी`) |
| Sentiment *per name* | clause-level when a message names two people ("Modi was great but Balen ...") |
| Topics | same gazetteer (border dispute, trade, energy, ...) |
| Emerging names | capitalised words not in the gazetteer, to extend it |
| Quality funnel | empty, spam/links, flooding, same-user repeats, copy-paste bursts |
| Timeline | volume + net sentiment on one time axis |

Edit `ytpulse/data/entities.yaml` (or pass `--entities`) to add names; tune thresholds in
`ytpulse/data/default_settings.yaml` (pass `--config`). After changing the gazetteer or model, run
`report --reenrich`.

## Quota

`liveChatMessages.list` costs ~5 units per call; the default project quota is 10,000 units/day. Polling at
the server-suggested 5-10 s uses roughly 1,800-3,600 units per hour, so a multi-hour stream can hit the
cap. The client logs its running estimate and stops cleanly with a `QuotaExceeded` message. Request a quota
extension from Google if you need more.

## Publishing responsibly

* Frame it as **"live-chat sample"**, never "public opinion". Chat is self-selected and can be brigaded;
  every card carries n, the filtering note and "not a representative poll".
* Say whether copy-paste repeats were included (the report prints a sensitivity number).
* Authors are stored as salted hashes; names are dropped unless `--store-names`. Don't publish handles.
* Review the "sample messages" before quoting any; the pipeline does not do toxicity screening.
* Synthetic runs watermark every output `DEMO DATA`; never post those numbers.
* Stored API data: YouTube's developer policies expect you to refresh or delete API data periodically
  (currently 30 days). Delete old `data/*.db` files.

## Layout

```
ytpulse/sources/    youtube.py (API client, live chat, comments) · replay.py · synthetic.py
ytpulse/nlp/        text.py (normalise, language, spam rules) · entities.py · sentiment.py
ytpulse/pipeline.py enrichment + threaded live loop      ytpulse/analytics.py  quality + aggregates
ytpulse/report.py   HTML + PNG cards                     ytpulse/store.py      SQLite layer
```
