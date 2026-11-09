# Benchmarks

## Podcast pivot: local measurements, 2026-11-10 (no paid model calls)

These runs used the 58.3-min CC BY *Blocks* podcast episode
(`backend/eval/podcasts/`). The backend image was run under `docker run --cpus 2`
to approximate the EC2 t3a.small. No OpenRouter calls were made: the shared
balance ($8.89) was below the $10 floor set for paid runs, so the eval matrix
in EVALUATION.md §5 has not been run yet.

**Audio upload → audiogram** (`services/audiogram.py`):

| Approach | Encode time, 58-min episode | Output size |
|---|---:|---:|
| Animated waveform, whole episode at upload (1080², 10 fps) | killed after >10 min | – |
| Animated waveform, whole episode at upload (720², 5 fps, AAC re-encode) | 517 s | 143 MB |
| Native AAC encode of the audio alone | 307 s | – |
| **Shipped:** static title card at 1 fps + audio stream-copied (m4a/aac/mp3) | **28.8 s** | **61 MB** |
| **Shipped:** 30 s 9:16 clip with the animated gold waveform, rendered per clip | 41 s | 7.6 MB |

nginx's `/api/` proxy timeout is 600 s, which rules out an animated pass over
the whole episode at upload. Through the real API on the local stack (no CPU
cap), the 54 MB `.m4a` uploaded and converted in 10.6 s and came back with
`media_kind: "audio"` and 720x720. Other audio codecs (wav/flac/ogg) are
re-encoded to 96 kb/s mono AAC, which is the slow path above.

**Static-shot check** (`chunk_analyzer.static_keep`). The probe samples 24
frames per 120 s chunk, as analysis does, and counts the chunks where the
frames show at most 4 distinct looks (mean abs difference < 12 on 32x18 grey):

| Video | Chunks | Reduced to 4 frames | Images sent (vs 24/chunk) |
|---|---:|---:|---:|
| Blocks podcast (2 people at a desk) | 32 | 29 | 188 vs 768 (−76%) |
| Doctorow talk (speaker + changing slide collages) | 34 | 5 | 716 vs 816 (−12%) |
| Wild Target (feature film) | 54 | 1 (in the end credits) | 1,276 vs 1,296 (−2%) |

On the podcast, the threshold barely matters: 25, 29, 30 and 30 of 32 chunks
are reduced at 8, 12, 16 and 20. Most chunks show 2–3 looks (the two
speakers plus a wide shot). The 3 chunks with 7–10 looks are the cold open
and about 24–28 min, where a clip from another show (the Roc Nation brunch
rant) is cut in. Fewer images means less vision
input; the money saved is unmeasured until the matrix runs.

---

# Benchmarks — live-tested, 2026-09-17

This is a **small real sample from one live debugging session**, not a
statistically rigorous benchmark suite. It exists so the cost/latency
numbers in the README are things that were actually measured against
OpenRouter, not estimates. Re-run `python backend/scripts/benchmark.py`
with a real (non-synthetic) video and more OpenRouter credit to get a
larger, more representative sample — see "What this doesn't cover" below.

## Environment

> These runs used the **previous** model defaults listed below. Defaults have
> since moved to cheap Gemini + open-source models (see README) — not yet re-benchmarked.

- Docker Compose stack (postgres+pgvector, redis, backend, frontend) built
  and run locally.
- `OPENROUTER_MODEL=anthropic/claude-sonnet-4.5` (orchestrator),
  `OPENROUTER_MODEL_LITE=openai/gpt-4o-mini` (scoring/titles),
  `OPENROUTER_MODEL_VISION=google/gemini-2.5-flash` (chunk analysis),
  `OPENROUTER_MODEL_AUDIO=google/gemini-2.5-flash` (transcription).
- Embeddings: local, `fastembed` (`BAAI/bge-small-en-v1.5`, 384-dim) — no
  API call, not counted in OpenRouter cost. *(Since replaced: embeddings now
  go through OpenRouter, `baai/bge-m3`, 1024-dim, and `fastembed` is no
  longer a dependency.)*
- Backend image size: **1.63GB** (no torch/CUDA — see bug #2 below for why
  `fastembed` replaced `sentence-transformers` at the time).

## What was actually measured

| Run | Input | Result | Wall time | OpenRouter cost |
|---|---|---|---|---|
| 1 | 45s synthetic video, color-bar test pattern + pure sine tone (no real content) | Correctly found **0 moments** — no clips, no hallucinated content | 18.6s | small (~part of $0.125 total below — not isolated) |
| 2 | 24s synthetic video, 3 scene cuts with on-screen text ("Wait for it...", "The database IS the spreadsheet", "Nobody told the CEO") + tone | Found **3 real moments** via vision analysis; clip production hit a pre-existing bug (below), fixed after this run | 55.5s | included below |
| 3 | Same 24s video, re-run after fixes | Found 3 moments again; no crash, no 402 — orchestrator still narrated a plausible clip summary without a grounded tool result (see "Known gap" below) | 36.2s | included below |

**Total OpenRouter spend observed across this session's real API calls**
(one-word ping test + 3 chat turns above, from the first balance check
taken mid-session to the last): **≈$0.125**, over roughly 5 real request
turns, 2 of which were full multi-tool-call agent runs (search_moments +
select_and_produce_clips + scoring).

**The OpenRouter balance was nearly exhausted (under $1) by the end of the
session**, which is what limited further testing. Top up before any real use.

## Bugs found and fixed via this live run (none of these were caught by
static review or `py_compile` — they only surfaced by actually executing)

1. `opencv-python-headless>=4.8.0` (unbounded) resolved to a fresh 5.0.0
   that dropped `cv2.CascadeClassifier` at import time, crashing the app
   on startup. Pinned to `<5.0.0`.
2. `sentence-transformers` pulled full PyTorch + CUDA wheels (multiple GB),
   causing repeated OOM kills on this build machine. Swapped for
   `fastembed` (ONNX Runtime, no torch) — same model class
   (`BAAI/bge-small-en-v1.5`), ~1/10th the footprint. *(Later superseded by
   OpenRouter-hosted BGE-M3 embeddings, so no local embedding model at all.)*
3. `deepagents.create_deep_agent()` and each subagent dict take
   `system_prompt`, not `instructions`/`prompt` as originally written
   (written without the ability to `pip install` and check the real
   signature at the time).
4. `PostgresSaver.from_conn_string()` returns a context manager whose
   connection closes if you don't hold it open correctly — the first fix
   attempt (`.__enter__()`) still left a fragile single connection that
   died under real use ("the connection is closed" on every chat request).
   Fixed by handing `PostgresSaver` a `psycopg_pool.ConnectionPool` instead,
   which reconnects on its own.
5. `langgraph-checkpoint-postgres` needs `psycopg` (v3), not the
   `psycopg2-binary` already in the project (used by SQLAlchemy) — added
   `psycopg[binary]`.
6. The orchestrator's default OpenRouter call had no `max_tokens` cap —
   some models (Claude via OpenRouter) default to `max_tokens=64000` when
   unset, which both costs more than needed for these short/structured
   responses and hit this account's low balance directly (`402: requested
   up to 64000 tokens, but can only afford 63180`). Capped to 4096
   (scoring/titles/vision/audio) / 8192 (orchestrator).
7. `utils/ffmpeg.py`'s `_nearest_keyframe()` assumed every line of
   `ffprobe` stdout was a parseable float timestamp; a specific H.264 SEI
   metadata line ("H.264 User Data Unregistered SEI message") broke that
   assumption and crashed clip production. Now skips non-numeric lines.
8. Placeholder `LANGSMITH_API_KEY` with `LANGSMITH_TRACING=true` caused a
   403 error logged on every single LLM call (noisy, not fatal). Disabled
   tracing by default (`config.py`, compose, and — as of 2026-10-01 —
   `.env.example`, which had still shipped `true`).

## Known gap (not fully resolved — needs more live iteration + credit)

Even after fixes #6–7 above, one run (#3 above) still had the orchestrator
narrate a plausible-sounding clip result ("Funny moment from
{video_id}", score 0.85) that didn't match `/api/clips`. The system prompt
was hardened to explicitly forbid this, but verifying the fix fully
converges needs more live test turns than this session's remaining
budget allowed. This is a real, open item — not swept under the rug.

## What this doesn't cover

- Clip *quality* (moment relevance, RAG retrieval precision) — both test
  videos were synthetic (drawtext/color bars), not real speech content.
  Run `backend/scripts/eval.py` against real labeled video for that.
- Cost at scale (a real 1-3 hour video, many chunks, many chat turns) —
  extrapolate from the per-chunk vision call cost above, but this session
  only tested single-chunk, sub-minute videos.
- `/api/search` and `modify_clip` were implemented but not live-tested in
  this session (budget ran out first). A later code review found real bugs
  in both (stale RAG rows; clip edits dropping the reframe and breaking the
  clip URL) — see README "Known issues".
- The current cheap-model defaults have not been re-benchmarked.
