# Benchmarks — live-tested, 2026-09-17

This is a **small real sample from one live debugging session**, not a
statistically rigorous benchmark suite. It exists so the cost/latency
numbers in the README are things that were actually measured against
OpenRouter, not estimates. Re-run `python backend/scripts/benchmark.py`
with a real (non-synthetic) video and more OpenRouter credit to get a
larger, more representative sample — see "What this doesn't cover" below.

## Environment

- Docker Compose stack (postgres+pgvector, redis, backend, frontend) built
  and run locally.
- `OPENROUTER_MODEL=anthropic/claude-sonnet-4.5` (orchestrator),
  `OPENROUTER_MODEL_LITE=openai/gpt-4o-mini` (scoring/titles),
  `OPENROUTER_MODEL_VISION=google/gemini-2.5-flash` (chunk analysis),
  `OPENROUTER_MODEL_AUDIO=google/gemini-2.5-flash` (transcription).
- Embeddings: local, `fastembed` (`BAAI/bge-small-en-v1.5`, 384-dim) — no
  API call, not counted in OpenRouter cost.
- Backend image size: **1.63GB** (no torch/CUDA — see provider notes in
  README for why `fastembed` replaced `sentence-transformers` here).

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

**Account balance at end of session: $910 total credits, $909.18 used,
≈$0.82 remaining.** This needs a top-up before any real use — see README.

## Bugs found and fixed via this live run (none of these were caught by
static review or `py_compile` — they only surfaced by actually executing)

1. `opencv-python-headless>=4.8.0` (unbounded) resolved to a fresh 5.0.0
   that dropped `cv2.CascadeClassifier` at import time, crashing the app
   on startup. Pinned to `<5.0.0`.
2. `sentence-transformers` pulled full PyTorch + CUDA wheels (multiple GB),
   causing repeated OOM kills on this build machine. Swapped for
   `fastembed` (ONNX Runtime, no torch) — same model class
   (`BAAI/bge-small-en-v1.5`), ~1/10th the footprint.
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
   tracing by default.

## Known gap (not fully resolved — needs more live iteration + credit)

Even after fixes #6–7 above, one run (#3 above) still had the orchestrator
narrate a plausible-sounding clip result ("Funny moment from
{video_id}", score 0.85) that didn't match `/api/clips`. The system prompt
was hardened to explicitly forbid this, but verifying the fix fully
converges needs more live test turns than this session's remaining
~$0.82 budget allows. This is a real, open item — not swept under the rug.

## What this doesn't cover

- Clip *quality* (moment relevance, RAG retrieval precision) — both test
  videos were synthetic (drawtext/color bars), not real speech content.
  Run `backend/scripts/eval.py` against real labeled video for that.
- Cost at scale (a real 1-3 hour video, many chunks, many chat turns) —
  extrapolate from the per-chunk vision call cost above, but this session
  only tested single-chunk, sub-minute videos.
- `/api/search` and `modify_clip` were implemented but not live-tested in
  this session (budget ran out first).
