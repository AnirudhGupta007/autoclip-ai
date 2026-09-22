# Observability & evaluation

How to watch what the agent actually does, and how to measure whether the
clips are any good. Three layers, cheapest first:

| Layer | Answers | Tool |
|---|---|---|
| **Tracing** | What did the agent call, in what order, and what did each step cost? | LangSmith |
| **Format matrix** | Does it honour the length/aspect ratio you asked for? | `scripts/test_matrix.py` |
| **Retrieval accuracy** | Are the moments it picks the *right* moments? | `scripts/eval.py` (precision@k) |

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

> Tracing is **off by default on purpose**. With a placeholder key and tracing
> enabled, every single LLM call logs a 403 — it's noisy and it slows the run.
> Turn it on only with a real key.

### What to look at once traces land

| Question | Where in LangSmith |
|---|---|
| Did the agent skip analysis and call production directly? | Trace tree for `/api/chat/message` — look for `ingest_and_analyze_video` before `select_and_produce_clips` |
| Which step burns the tokens? | Run table → sort by tokens. Expect `chunk_analyzer` to dominate on long videos |
| Why did a run return zero clips? | Open the `select_and_produce_clips` tool span → check its `status` field (`not_analyzed` / `no_match` / `ok`) |
| Is the agent hallucinating success? | Compare the final AI message against the tool result immediately above it |

That last row is the one worth a saved view. The failure mode this project hit
repeatedly was the model narrating a plausible result that the tool never
returned — a trace makes it obvious in seconds.

### Useful without LangSmith

```bash
curl -s localhost:8000/api/telemetry | python3 -m json.tool   # per-model call/token counts
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
    "video_id": "movie01",
    "video_path": "/app/uploads/movie01/source.mkv",
    "good_windows": [[412, 447], [1985, 2020], [5310, 5352]]
  }
]
```

`good_windows` are `[start, end]` in seconds for moments a human considers
clip-worthy. Twenty to thirty per long video is enough to be meaningful.

```bash
docker compose exec backend python -m scripts.eval --dataset eval/dataset.json --k 6
```

A detected moment counts as a hit when it overlaps a labelled window by ≥50% of
the shorter span. The harness reports precision@k plus the mean convergence
score.

**Interpreting it:** precision@6 of 0.5 means half the top six moments were ones
you'd have picked yourself — which for sparse content like a feature film is
respectable. Treat the first run as a baseline, then re-run after changing the
vision model or the chunk size and compare. The absolute number matters less
than the direction it moves.

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
4. **One run is not a benchmark.** Model sampling varies between runs. Run the
   matrix three times before concluding a change helped.
