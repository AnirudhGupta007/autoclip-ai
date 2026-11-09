# Observability & evaluation

How to watch what the agent actually does, and how to measure whether the
clips are any good. Four layers, cheapest first:

| Layer | Answers | Tool |
|---|---|---|
| **Tracing** | What did the agent call, in what order, and what did each step cost? | LangSmith |
| **Format matrix** | Does it honour the length/aspect ratio you asked for? | `scripts/test_matrix.py` |
| **Retrieval accuracy** | Are the moments it picks the *right* moments? | `scripts/eval.py` (precision@k) |
| **Movie eval** | End to end through the chat API, against a human-labelled film: right moment, right category, right format, at what cost? | `scripts/eval_movie.py` |

---

## 1. Tracing with LangSmith

Every LLM call goes through LangChain/LangGraph, so tracing needs no code
changes — only env vars. They're already wired in `config.py` and
`docker-compose.yml`.

```bash
# .env
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=lsv2_pt_...
LANGSMITH_PROJECT=autoclip
```

```bash
docker compose up -d backend    # picks up the new env
```

> Tracing is **off by default on purpose** (`LANGSMITH_TRACING=false` in both
> `config.py` and `.env.example`). With a placeholder key and tracing enabled,
> every single LLM call logs a 403 — it's noisy and it slows the run. Turn it
> on only with a real key.

### What to look at once traces land

| Question | Where in LangSmith |
|---|---|
| Did the agent skip analysis and call production directly? | Trace tree for `/api/chat/message` — look for `ingest_and_analyze_video` before `select_and_produce_clips` |
| Which step burns the tokens? | Run table → sort by tokens. Expect `chunk_analyzer` to dominate on long videos |
| Why did a run return zero clips? | Open the `select_and_produce_clips` tool span → check its `status` field (`video_not_found` / `not_analyzed` / `no_match` / `ok`) |
| Is the agent hallucinating success? | Compare the final AI message against the tool result immediately above it |

That last row is the one worth a saved view. The failure mode this project hit
repeatedly was the model narrating a plausible result that the tool never
returned — a trace makes it obvious in seconds.

### Useful without LangSmith

```bash
curl -s localhost:8000/api/telemetry | python3 -m json.tool   # per-model call/token counts (vision, lite_scoring, lite_title)
docker compose logs -f backend | grep -iE "chunk_analyzer|failed|error"
```

---

## 2. Format matrix — one video, many asks

The moment map is computed once and cached, so after the first analysis every
extra format is a cheap retrieval plus an ffmpeg cut. One long video therefore
tests a dozen behaviours for roughly the price of one.

```bash
# against an already-analysed video
python backend/scripts/test_matrix.py --video-id abc123 --out MATRIX.md

# or upload first
python backend/scripts/test_matrix.py --upload ~/Videos/movie.mkv --out MATRIX.md --json matrix.json
```

> **Raise the quota first.** Every ask is a `POST /api/chat/message`, which
> is metered at `DAILY_QUERY_LIMIT` (default **2**) per IP per day. With the
> default, asks 3–10 get HTTP 429 and show up as "produced nothing". Set e.g.
> `DAILY_QUERY_LIMIT=50` in `.env` and `docker compose up -d backend` before
> running it locally — and don't point it at the public demo.

It runs ten asks spanning 10s→60s and 9:16 / 1:1 / 16:9, including
content-driven ones ("the most emotional moment", "where it gets tense"), then
reports:

- **Aspect-ratio adherence** — did a request for 1:1 actually return 1:1?
- **Length adherence** — delivered duration within ±25% of what was asked
- **Wall time and measured cost per request** (read from the OpenRouter credits
  endpoint, not estimated)
- **Every request that produced nothing**, with the assistant's own explanation

Length adherence is the metric to watch. Clips are snapped to scene and word
boundaries, so exact durations are neither expected nor desirable — but a 15s
request coming back as 3.8s is a bug, and this table catches it.

---

## 3. Retrieval accuracy — precision@k

Format adherence says the plumbing works. It says nothing about whether the
moments are *good*. For that you need labelled ground truth.

```bash
# backend/eval/dataset.json
[
  {
    "video_id": "3f9a1c2b7d4e",
    "video_path": "/absolute/path/on/this/machine/movie.mkv",
    "good_windows": [[412, 447], [1985, 2020], [5310, 5352]]
  }
]
```

`video_id` is the id the upload returned (12 hex chars) and `video_path` must
be readable from wherever the harness runs. `good_windows` are `[start, end]` in seconds for moments a human considers
clip-worthy. Twenty to thirty per long video is enough to be meaningful.

```bash
make eval
# or, with options:
cd backend && uv run python -m scripts.eval --dataset eval/dataset.json --k 6
```

It runs on the host, not inside the backend container — the image only copies
`src/`, so `scripts/` and `eval/` don't exist in there. It invokes the
pipeline in-process, so it needs `make setup` and the same `.env` (OpenRouter
key; point `DATABASE_URL`/`REDIS_URL` at the compose services or leave them
unset for the sqlite/in-memory fallbacks). Note it runs the full pipeline,
including a default generation pass, so each row costs real vision + audio +
scoring calls.

A detected moment counts as a hit when it overlaps a labelled window by ≥50% of
the shorter span. The harness reports precision@k, the mean convergence
score, and the per-label prompt-cache hit rate.

**Interpreting it:** precision@6 of 0.5 means half the top six moments were ones
you'd have picked yourself — which for sparse content like a feature film is
respectable. Treat the first run as a baseline, then re-run after changing the
vision model or the chunk size and compare. The absolute number matters less
than the direction it moves.

---

## 4. Movie eval — human ground truth, end to end (`eval_movie.py`)

`scripts/eval.py` scores the pipeline in-process. `scripts/eval_movie.py` scores
**the product**: it sends each ground-truth query to the running backend as a
chat message, exactly as a user would, and measures what comes back against a
human-labelled moment map of a full-length film.

### Ground truth

`backend/eval/movies/<slug>.json`. The first film is *Wild Target* (2010, 98
min; the film proper ends at 5600 s and the end credits follow). It is a
copyrighted film, used for evaluation only. No footage, frames or transcript
are in the repo, and the film is never published.

- **35 moments** `{id, start, end, tags[], grade 1–3, note}`. They were
  labelled in one human pass using 489 frames (one every 12 s), denser frame
  sheets for the key scenes, and an independent transcript. Where the two
  disagreed, visual timing won, because the transcript drifts by about ±20 s.
- **6 queries** `{id, prompt, count, length, frame, tags[], truth[3]}`. Each
  query has a ranked top-3 of moment ids. For example, `q_tense` ("the most
  tense moment, 20 seconds, 1:1") has the truth `m32` (the climax gun-to-head),
  then `m06` (the car-park ambush), then `m30` (the gunpoint standoff). The
  `message` field is the exact chat text sent. It matches the baseline run, so
  live runs stay comparable to it.

### Run it

```bash
# Re-score an existing run. Sends no chat messages and costs nothing.
python3 backend/scripts/eval_movie.py --gt backend/eval/movies/wild_target.json \
    --from-results backend/eval/movies/wild_target_baseline/report.json

# Live run against the local stack, diffed against the committed baseline
# (needs DAILY_QUERY_LIMIT ≥ 6 × runs; see section 2)
python3 backend/scripts/eval_movie.py --gt backend/eval/movies/wild_target.json \
    --base http://127.0.0.1:8000 --video-id <id> --runs 3 --budget-usd 3 \
    --baseline backend/eval/movies/wild_target_baseline/report.json   # exit 2 on regression

# Print the chat messages without sending them
python3 backend/scripts/eval_movie.py --gt backend/eval/movies/wild_target.json --dry-run

# Unit tests for the metrics (hand-computed cases)
uv run --no-project --with pytest pytest backend/tests/test_evallib.py -q
```

The harness uses only the standard library and runs with the system `python3`.
Each run writes `reports/eval/<slug>/<UTC-ts>/{report.md, report.json, clips.csv}`.
`report.json` embeds the normalised run, so you can feed it back through
`--from-results` to re-score after the ground truth or the metrics change.
Other options:

- `--upload PATH` uploads the film instead of using `--video-id`.
- `--queries q_action,q_tense` runs a subset of the queries.
- `--fail-on-regression 0.05` is the absolute drop that counts as a regression.
  It applies to any rate metric. Any increase in credits violations also counts.
- `--no-probe` skips the ffmpeg checks.

Exit codes:

| Code | Meaning |
|---|---|
| 0 | OK |
| 1 | Error |
| 2 | Regression against `--baseline` |
| 3 | Incomplete run: a 429 quota response or `--budget-usd` stopped it. Queries that did not run are excluded from scoring rather than counted as misses. |

**Background analysis.** If a chat reply says analysis has started instead of
returning clips, the harness polls `GET /api/chat/analysis/{id}` until the
moment count is final, then sends the query again. That re-send uses a second
quota slot.

**Where the data comes from:**

- **Clips:** the chat responses. The harness takes the new ids in each
  response. Old clips that the response sends again are counted as *stale*.
- **Moments:** a moments endpoint if one exists. Otherwise a read-only
  `SELECT` against the `moments` table, via `docker exec autoclip-ai-postgres-1 psql`.
- **Transcript coverage:** only the word *timings* from
  `/app/outputs/<id>/transcript.json`, never the text.
- **Clip measurements:** ffprobe and ffmpeg run on the host if available,
  otherwise through `docker exec autoclip-ai-backend-1`.
- **Cost:** deltas of the OpenRouter `/credits` endpoint. The credits figure
  covers the whole account, so anything else using the key during a run is
  counted too.

### What it measures

All matching uses one rule: a clip matches a human moment when they **overlap
by at least 50% of the shorter span**.

| Group | Metrics |
|---|---|
| Query quality | **hit@1, hit@3, MRR** (the delivered clips, in order, against the human top-3). **Best truth rank.** **Tag precision** (does a clip asked to be funny land on *any* moment tagged funny?). **Clip precision** (does it land on any labelled moment at all?). |
| Analysis | **Moment recall and precision @10/25/all** (moments ranked by convergence score, matched one-to-one by greedy tIoU). **Recall per tenth of the film.** **Gaps of 5 min or more with no moments.** **Within-chunk position histogram** (where in each 120 s chunk moments are found). **How far into the film analysis reached.** **Transcript minute coverage.** |
| Delivery | **Length adherence** within ±10% and within ±25%, from ffprobe. **Aspect adherence.** **Duplicate rate.** **Stale clips sent again.** **Credits violations** (clips or moments that start after `film_end`). **Captions visible** (bottom-third pixel difference between `final.mp4` and `reframed.mp4`). **Letterbox share** (`cropdetect`). |
| Cost | OpenRouter USD and wall time, per query and in total |

The metric code is in `backend/scripts/evallib/metrics.py`. It is pure
functions, and `backend/tests/test_evallib.py` unit-tests it.

### Baseline: the pre-fix app (2026-10-01)

The full baseline report is
[`backend/eval/movies/wild_target_baseline/report.md`](backend/eval/movies/wild_target_baseline/report.md).
It covers 6 chat turns and 9 clips returned to the user. It cost $1.45 in
total, and the first turn took 18.6 min because it included analysis.

| Metric | Baseline |
|---|---:|
| Query hit@3 / hit@1 / MRR | **0.00 / 0.00 / 0.00** (none of the 6 queries hit any of its human top-3) |
| Tag precision | **0.11** (1/9 clips lands on a moment of the asked category) |
| Clip precision | **0.22** (2/9 clips land on *any* human moment) |
| Moment recall @10 / @25 / @all | 0.09 / 0.17 / **0.37** (52 moments, 13 of 35 human moments found) |
| Moment precision @25 | 0.24 |
| Length adherence ±10% / ±25% | 0.88 / 1.00 (the 20 s 1:1 clip came back at 22.8 s) |
| Aspect adherence | 1.00 |
| Transcript coverage | **0.03**: 3 of 94 film minutes, with words only between 1:30:01 and 1:32:25 |
| Moments in 2nd half of chunks | 0.42 (229 raw chunk moments) |
| Captions visible | **0.00** |
| Credits violations | 0 |
| Cost / wall time | $1.449 / 1,291 s |

Problems the report flags automatically:

- **The transcript is almost empty.** The app is effectively clipping a
  dialogue-driven comedy with no dialogue, which is why the "one-liner" and
  "funny" asks miss.
- **5 of 54 analysis chunks failed:** chunks 17–19, 26 and 53.
- **There are 4 gaps of 5+ minutes with no moments,** 35 min in total
  (30:32–43:10, 45:27–54:55, 1:14:31–1:20:30, 1:26:12–1:32:54). The first two
  gaps cover the car chase and the hotel-bath shooting, which are the top
  "action" truth.
- **Each chat reply sends every earlier clip again:** 30 stale clips across 6
  turns.
- **Delivered clips are about 24% black bars,** because the film's letterbox is
  kept through the 9:16 reframing.
- **No delivered clip has visible captions.**
- **4 clips were rendered during analysis that nobody asked for.**

When the fixes land, run a live eval with `--baseline
backend/eval/movies/wild_target_baseline/report.json`. The headline numbers to
move are hit@3, tag precision and transcript coverage.

---

## 5. Podcasts — ground truth, the eval matrix and RAGAS

### Ground truth

`backend/eval/podcasts/blocks_russell_peters.json`: *Russell Peters | Blocks
Podcast w/ Neal Brennan* (58.3 min, two people at a desk), CC BY on YouTube
(`yt-dlp --print license` → "Creative Commons Attribution license (reuse
allowed)"). It was downloaded with `yt-dlp` from a local venv, for testing
only. `yt-dlp` is not a backend dependency. There are two local files: the
480p video and its audio track as `.m4a`, which is the same track and so a
like-for-like comparison.

- **40 moments**, in the same schema as the movie files. The tags use the tagger's
  category names (`hot_take` and `advice` are the podcast ones). `money` is a
  topic tag. The moments were labelled in one pass over the whole YouTube
  auto-caption transcript. Timings come from the caption cues and are
  accurate to about ±5 s.
- **6 queries:** funny ×3 at 9:16, a story at 16:9, the spiciest hot take
  at 1:1, real-life advice, the best quote, and money with the old accountant.
  "Funniest" and "spiciest" are one labeller's ranking. Tag precision is the
  less subjective number.

`eval_movie.py` reads this format unchanged. Only its wording was
generalised from "film" to "video".

### Eval matrix (not run yet)

Each arm is one fresh analysis of the same episode plus the 6 queries. That
is 3 full analyses, estimated well under the $4 cap from the film's $0.59 for
98 min. Run them against the local stack:

```bash
set -a; source .env; set +a
E="python3 backend/scripts/eval_movie.py --gt backend/eval/podcasts/blocks_russell_peters.json --base http://localhost --budget-usd 1.3 --ragas"
# 1. video, full vision: 24 frames per chunk
VISION_STATIC_CHECK=0 docker compose up -d backend && $E --upload ~/Videos/autoclip-bench/blocks_russell_peters.mp4
# 2. video, static-frames: the default; static chunks send 4 frames
docker compose up -d backend && $E --upload ~/Videos/autoclip-bench/blocks_russell_peters.mp4
# 3. audio only: an audiogram, transcript-only chunks
$E --upload ~/Videos/autoclip-bench/blocks_russell_peters_audio.m4a
```

Exit bar: audio-only cost at least 60% lower than full vision, with hit@3 no
worse.

**Status (2026-11-10): not run.** The shared OpenRouter balance was $8.89,
below the $10 floor set for paid runs, so no analysis was started. The only
podcast numbers measured so far are the ones that cost nothing (see
BENCHMARKS.md): audiogram encode time, how often the static-shot check fires,
and the upload path.

### RAGAS (`--ragas`, dev-only)

The ID-based metrics above stay primary. `--ragas` adds two judge metrics
that those metrics cannot see. They are in `backend/scripts/evallib/ragas_eval.py`,
and `ragas` is installed only via the `eval` extra (`pip install -e 'backend[eval]'`),
never in the image.

- **Faithfulness**, per clip: does the clip's title claim anything that is
  not in the clip's own transcript? This catches hallucinated titles. It is
  averaged per query. The agent's chat reply is *not* judged, because it
  states lengths, scores and aspect ratios that no transcript contains. A
  first version that judged it scored 0.00 across the board.
- **Context precision**, per query: are the returned clips, in rank order,
  relevant to the request? The judge uses the human notes for the query's
  truth moments as the reference.

The judge is a cheap OpenRouter model (default `google/gemini-2.5-flash-lite`)
through ragas' LangChain wrapper. The step estimates its cost first and
skips itself when that exceeds the `--budget-usd` left after the queries.
Transcript text is held in memory only, and the report stores scores only.
If a run's clips no longer exist (for example after `--fresh`), their dialogue
is rebuilt from the container's `transcript.json` for the clip windows.

Measured 2026-11-10, re-scoring the existing selection-fix runs offline
(`--from-results … --ragas --ragas-model nvidia/nemotron-3.5-super-vl:free`,
$0.00):

| Run (6 queries) | hit@3 | Tag precision | RAGAS faithfulness | RAGAS context precision |
|---|---:|---:|---:|---:|
| Doctorow talk, Gemini 2.5 Flash | 0.33 | 0.62 | 0.81 | 0.50 |
| Wild Target, Gemini 2.5 Flash | 0.33 | 0.33 | 0.69 | 0.47 |

Caveats: the judge is a free model, and one run is noisy. The free Gemma
judges returned 429s from the shared upstream pool. Context precision ≥ 0.5
agrees with hit@3 on only 8 of 12 queries. It is a looser signal: it scored
1.0 on three queries whose clips missed the human top-3, and 0.0 on one
query that hit. Faithfulness judges short titles, so a single loose word
moves a clip's score a lot. Read the per-query tables in each `report.md`
before trusting the means.

---

## Known measurement caveats

Be honest about these when reading any of the numbers above:

1. **Synthetic test clips prove plumbing, not quality.** Colour bars with a sine
   tone make the transcription model hallucinate speech outright. Every accuracy
   number needs real footage with real audio.
2. **Word timestamps are approximated.** OpenRouter has no dedicated ASR
   endpoint, so per-word timings are interpolated across each returned phrase.
   Caption sync is therefore looser than forced alignment would give, and
   boundary snapping inherits that error.
3. **Cost readings lag.** The OpenRouter credits endpoint updates with a short
   delay, so a single request's measured cost can land on the next row. Totals
   across a full matrix run are reliable; individual rows are indicative.
4. **Vision sees a sample of each chunk.** 24 frames are spread evenly across
   each 120 s chunk (one every 5 s). Since the podcast pivot, a chunk whose
   frames show at most 4 distinct looks (a static podcast camera) sends only 4
   frames, and audio uploads send none. On those, moments come from the
   transcript almost entirely.
5. **One run is not a benchmark.** Model sampling varies between runs. Run the
   matrix three times before concluding a change helped.
6. **The overlap rule is lenient on short moments.** A match needs only 50% of
   the *shorter* span. A 5 s app moment that sits anywhere inside a 60 s
   labelled scene therefore counts as a hit. This makes moment recall optimistic
   on films where the app emits many short moments. For clips it is less of an
   issue, because clips are 15–45 s, comparable to the labels. The labels
   themselves come from a single annotator.
