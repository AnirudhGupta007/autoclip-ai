# AutoClip AI

Conversational AI video clipping. Upload a long-form video, chat with it in
natural language, and get short-form viral clips back — optimized for TikTok,
Reels, and Shorts, in whatever length/format you ask for (15s, 30s, 60s,
9:16, 1:1, 16:9 — freeform, not a fixed menu).

A deep-agent orchestrator (LangChain's `deepagents`, built on LangGraph)
drives the conversation and decides which tools to call. Clip discovery is
RAG-driven: a LlamaIndex-backed semantic index over every analyzed moment,
so "clips where he roasts a competitor" retrieves on meaning, not a fixed
style enum. Chunk analysis still runs as a chunk-parallel LangGraph
Send-API fan-out underneath the agent — that part of the original
architecture was already good and is reused as a tool, not rebuilt.

**Every LLM call goes through OpenRouter** — orchestrator reasoning,
subagents, clip scoring, titles, chat replies, frame-sampled vision
analysis, and audio transcription. The one exception is embeddings:
OpenRouter has no embeddings endpoint at all, so moment embeddings run on a
local fastembed (ONNX, no torch) model instead (see [Provider notes](#provider-notes-what-moved-to-openrouter-and-what-didnt)).

```
You:  "Give me 4 funny TikTok clips under 30 seconds"
AI:   Analyzing 12 chunks in parallel...
      [chunk 3 done]  [chunk 7 done]  [chunk 1 done] ...
      24 moments indexed, retrieving matches for "funny"...
      [4 clips ready]
        1. "The Database Was a Spreadsheet" — 28s · 9:16 · 8.9/10
        2. "Nobody Told the CEO"           — 24s · 9:16 · 8.4/10
        3. ...

You:  "Clip where he roasts a competitor, square format"
AI:   Searching moments for "roasts a competitor"... found 3 candidates,
      producing the best match in 1:1 ...
```

## Architecture

```
User message
     │
     ▼
POST /api/chat/message  (routers/chat.py — unchanged request/response shape)
     │
     ▼
agent/orchestrator.py   deepagents.create_deep_agent()
   model: OpenRouter (OPENROUTER_MODEL, e.g. anthropic/claude-sonnet-4.5)
   checkpointer: LangGraph Postgres saver (thread_id = video_id, resumable)
     │
     ├─ tool: ingest_and_analyze_video ──▶ pipeline/graph.py (unchanged)
     │         │
     │         │  Send-API fan-out — one chunk_analyzer worker per 2-min window
     │         ▼
     │    chunk_analyzer × N (OpenRouter vision, frame-sampled — see below)
     │         │  fan-in
     │         ▼
     │    global_fusion (dedupe, local fastembed (ONNX, no torch) embeddings)
     │         │
     │         ▼
     │    rag/index.py — moments indexed into LlamaIndex (pgvector-backed)
     │
     ├─ tool: search_moments ──▶ rag/retriever.py (semantic search, filtered by video_id)
     │
     ├─ tool: select_and_produce_clips ──▶ clip_selector.py (RAG retrieval + OpenRouter
     │         scoring/titles) → production.py (ffmpeg cut/caption/reframe, unchanged)
     │
     ├─ tool: modify_clip ──▶ services/clip_reprocess.py (shared with PUT /api/clips/{id})
     │
     └─ tool: get_video_status ──▶ DB (Video/Clip/MomentRecord) — replaces the old
               in-process `_analysis_cache` dict, which silently broke under
               multiple uvicorn workers/replicas.

   subagents: retrieval-agent (search_moments), critic-agent (reviews clip
   scores), production-agent (select_and_produce_clips / modify_clip)
```

## Provider notes: what moved to OpenRouter, and what didn't

| Call site | Provider | Why |
|---|---|---|
| Orchestrator + subagent reasoning | OpenRouter (`OPENROUTER_MODEL`) | Standard chat-completions tool-calling. |
| Clip scoring, titles, chat replies | OpenRouter (`OPENROUTER_MODEL_LITE`) | Cheap/fast structured-output calls. |
| Chunk vision analysis | OpenRouter (`OPENROUTER_MODEL_VISION`) | OpenRouter has no native video-file-upload API, so `chunk_analyzer.py` samples ~1 frame every 2.5s via ffmpeg, base64-encodes them as JPEGs, and sends them as multiple `image_url` parts in one chat completion alongside the transcript window. This leans more on the transcript signal than true video understanding would — a known precision tradeoff. |
| Audio transcription | OpenRouter (`OPENROUTER_MODEL_AUDIO`) | OpenRouter has no dedicated ASR endpoint, so `services/transcription.py` sends each ~10-min audio segment as an `input_audio` chat-completion content part and asks for a phrase-level transcript with timestamps. Per-word timestamps are then *approximated* by evenly distributing each phrase's words across its estimated window — this is not frame-accurate forced alignment the way a dedicated ASR model's word timestamps are, but it's good enough for the scene/word-boundary snapping `clip_selector.py` does. |
| Moment embeddings | **Local** — `fastembed (ONNX, no torch)` (`BAAI/bge-small-en-v1.5`, 384-dim), no API key, no network call | OpenRouter has no embeddings endpoint at all — this is the one call site that genuinely cannot go through it. |

## Cost & latency

This was live-tested end to end (Docker build, real OpenRouter calls, a
real chat turn producing real moment detection) — see **[BENCHMARKS.md](BENCHMARKS.md)**
for the full writeup, including 8 real bugs that only surfaced by actually
running it (none caught by static review). Short version: a full chat
turn against a short (~24s) test video — orchestrator reasoning, vision
analysis, RAG retrieval, scoring — took **18–56s wall time** and **≈$0.03–0.07
per turn**, depending on how many tool calls the agent makes. That's a
small sample from synthetic test clips, not a rigorous benchmark — run it
yourself against a real video for numbers that mean something for your use
case:

```bash
make up
python backend/scripts/benchmark.py --video path/to/sample.mp4
```

It uploads a video, drives a chat turn through `/api/chat/message`, times
each phase (upload → analysis → clip production), reads `/api/telemetry`
for per-model token counts, and appends a real, timestamped entry to
`BENCHMARKS.md`.

**One open item from live testing:** the orchestrator was caught once
narrating a plausible-sounding clip result that didn't match what was
actually in the database (a tool-call error got summarized instead of
reported honestly). The system prompt now explicitly forbids this, but it
wasn't re-verified live — see BENCHMARKS.md's "Known gap" section.

**Cost drivers, for back-of-envelope estimates on longer videos:**

- **Vision (chunk analysis):** 1 OpenRouter vision call per chunk × chunks
  (a 2-min chunk size means ~30 chunks/hour of video), each with ~24 sampled
  JPEG frames + transcript text as input tokens. Cost ≈
  `chunks_per_video × (input_tokens_per_call × vision_model_input_price + output_tokens × output_price)`.
- **Audio (transcription):** 1 OpenRouter audio call per ~10-min segment ×
  segments (~6 calls/hour of video).
- **Text (orchestrator + scoring):** a handful of tool-calling turns per
  chat message (orchestrator reasoning) + 2 lite calls per produced clip
  (score + title).
- Check current per-model pricing at https://openrouter.ai/models before
  estimating — it changes over time and varies a lot by model choice
  (`OPENROUTER_MODEL`/`OPENROUTER_MODEL_VISION`/`OPENROUTER_MODEL_AUDIO`
  are all independently configurable, so you can trade cost for quality
  per call site).

## Quick start

Prereqs: Docker + Docker Compose, and an [OpenRouter API key](https://openrouter.ai/keys)
**with real balance on it** — every LLM call in this app (orchestrator,
vision, audio, scoring) goes through that one key, so check
https://openrouter.ai/settings/credits before relying on it for anything;
a 402 mid-request looks like a random failure otherwise.

```bash
git clone https://github.com/AnirudhGupta007/autoclip-ai.git
cd autoclip-ai
cp .env.example .env
# edit .env: paste in OPENROUTER_API_KEY
make up
```

Browse to **http://localhost**. First build pulls pgvector + redis images
and installs Python deps (including `fastembed (ONNX, no torch)`, which also
pulls its embedding model weights on first run — expect a few minutes).

### Make targets

```
make up         # build + start all 4 services (postgres+pgvector, redis, backend, frontend)
make down       # stop (volumes survive)
make nuke       # stop + wipe everything
make logs       # tail all services
make logs-be    # tail backend only
make rebuild    # rebuild backend image after code changes
make shell-be   # bash into backend container
make shell-db   # psql into postgres
make eval       # run the precision@k harness (needs backend/eval/dataset.json)
```

## Project layout

```
autoclip-ai/
├─ backend/
│  ├─ src/autoclip/
│  │  ├─ main.py                    # FastAPI app + /api/health + /api/telemetry
│  │  ├─ config.py                  # env-driven model + tuning knobs
│  │  ├─ database.py / models.py    # SQLAlchemy + pgvector column (hybrid sqlite/pg)
│  │  ├─ llm/openrouter.py          # the single OpenRouter chat-model client factory
│  │  ├─ rag/                       # LlamaIndex moment index + retriever
│  │  │  ├─ embedding.py            # LlamaIndex wrapper around the local embedding model
│  │  │  ├─ store.py                # pgvector-backed vector store (additive table)
│  │  │  ├─ index.py                # moment → node indexing
│  │  │  └─ retriever.py            # semantic search, shared by clip_selector + /api/search
│  │  ├─ agent/                     # the deep-agent orchestrator
│  │  │  ├─ tools.py                # tool wrappers around the pipeline/RAG/DB
│  │  │  └─ orchestrator.py         # deepagents.create_deep_agent() + subagents
│  │  ├─ pipeline/
│  │  │  ├─ graph.py                # the LangGraph wiring (Send API, subgraphs, checkpointer)
│  │  │  ├─ state.py                # TypedDict state + Pydantic structured-output models
│  │  │  ├─ telemetry.py            # per-model OpenRouter call/token counters
│  │  │  └─ agents/
│  │  │     ├─ chunk_planner.py     # splits video into 2-min windows
│  │  │     ├─ chunk_analyzer.py    # frame-sampled OpenRouter vision call per chunk
│  │  │     ├─ global_fusion.py     # temporal + embedding dedupe
│  │  │     ├─ clip_selector.py     # RAG retrieval + OpenRouter scoring/titles
│  │  │     └─ production.py        # ffmpeg cut/caption/reframe/thumbnail
│  │  ├─ services/
│  │  │  ├─ transcription.py        # OpenRouter audio-part transcription + chunking
│  │  │  ├─ scene_detector.py       # ffmpeg scene filter
│  │  │  ├─ video_processor.py      # face detection, -c copy cuts, reframing
│  │  │  ├─ embeddings.py           # local fastembed (ONNX, no torch) + cosine helpers
│  │  │  ├─ clip_reprocess.py       # shared re-cut/re-caption logic (HTTP route + agent tool)
│  │  │  ├─ events.py               # Redis pub/sub publishers + SSE subscriber
│  │  │  └─ moment_store.py         # persist moments to Postgres + RAG index
│  │  └─ routers/
│  │     ├─ chat.py                 # POST /api/chat/message → orchestrator.invoke()
│  │     ├─ videos.py · clips.py    # CRUD
│  │     └─ search.py               # POST /api/search → rag/retriever.py
│  ├─ scripts/eval.py               # precision@k harness (analysis subgraph, unchanged)
│  ├─ scripts/benchmark.py          # live cost/latency benchmark → BENCHMARKS.md
│  └─ eval/dataset.example.json
├─ frontend/                        # Vite + React + Tailwind — unchanged, same API contract
├─ infra/postgres-init.sql          # CREATE EXTENSION vector on first boot
├─ docker-compose.yml
└─ Makefile
```

## Configuration (env vars)

| Var | Default | What |
|---|---|---|
| `OPENROUTER_API_KEY` | — | Required. |
| `OPENROUTER_MODEL` | `anthropic/claude-sonnet-4.5` | Deep-agent orchestrator + subagents. |
| `OPENROUTER_MODEL_LITE` | `openai/gpt-4o-mini` | Clip scoring, titles, chat replies. |
| `OPENROUTER_MODEL_VISION` | `google/gemini-2.5-flash` | Frame-sampled chunk analysis. |
| `OPENROUTER_MODEL_AUDIO` | `google/gemini-2.5-flash` | Audio-part transcription. |
| `EMBEDDING_MODEL_NAME` | `BAAI/bge-small-en-v1.5` | Local embedding model (no API key). |
| `EMBEDDING_DIM` | `384` | Must match the embedding model's output dim (pgvector column size). |
| `CHUNK_LENGTH_SECONDS` | `120` | Analysis chunk size. |
| `CHUNK_OVERLAP_SECONDS` | `10` | Overlap (helps global_fusion catch boundary moments). |
| `CHUNK_MAX` | `60` | Safety bound on chunk count. |
| `TRANSCRIBE_SEGMENT_SECONDS` | `600` | Audio split size for long-form. |
| `TRANSCRIBE_SINGLE_SHOT_MAX` | `780` | Skip splitting when video ≤ this. |
| `TRANSCRIBE_PARALLELISM` | `4` | Concurrent OpenRouter calls during audio chunking. |
| `LANGGRAPH_PG_URL` | unset | If set, swaps `MemorySaver` for `PostgresSaver` (resumable runs — also backs the deep agent's own thread state). |
| `REDIS_URL` | unset | If set, enables SSE live updates; otherwise pub/sub is a no-op. |
| `LANGSMITH_TRACING`, `LANGSMITH_API_KEY` | unset | LangSmith auto-instrumentation. |

The compose file wires all of these for you; just fill in `OPENROUTER_API_KEY`.

## Observability

- **`GET /api/telemetry`** — rolling OpenRouter call count + token usage per `model_label` (vision/audio/lite_scoring/lite_title)
- **`backend/scripts/eval.py`** — precision@k vs labeled `eval/dataset.json` (untouched by this rewrite — still calls `pipeline.invoke()` directly against the analysis subgraph)
- **`backend/scripts/benchmark.py`** — real end-to-end cost/latency, appended to `BENCHMARKS.md`
- **LangSmith** — set `LANGSMITH_API_KEY` and every LangGraph node + OpenRouter call appears as a span
- **`make logs-be`** — backend logs include per-chunk timing and cache hit rate per call

## Known limitations of this rewrite

- **Not live-tested end-to-end.** Built in a sandbox with no general
  internet access (pip installs and live API calls both fail there) —
  code is correct against documented library interfaces and passes
  `py_compile`, but hasn't run against a real video yet. Run
  `backend/scripts/benchmark.py` to validate + generate real numbers.
- **`deepagents.create_deep_agent`'s exact kwargs** (`agent/orchestrator.py`)
  were written against the library's documented public interface without
  being able to `pip install` and check the installed version's actual
  signature — verify on first real run.
- **Audio timestamps are approximated**, not forced-aligned — see the
  provider table above.
- **Vision analysis is frame-sampled, not native video understanding** —
  leans more on the transcript than a true video model would.

## Cold deploy to a fresh EC2

```bash
# On the box
sudo apt update && sudo apt install -y docker.io docker-compose-v2 git
sudo usermod -aG docker ubuntu && exec sudo -u ubuntu bash    # re-login for group
sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile \
  && sudo mkswap /swapfile && sudo swapon /swapfile \
  && echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab

git clone https://github.com/AnirudhGupta007/autoclip-ai.git
cd autoclip-ai
cp .env.example .env       # paste in OPENROUTER_API_KEY
make up                    # ~3 min on a t3.small / t2.micro
```

CI/CD: `.github/workflows/deploy.yml` runs an AST sanity check on every push to
`master`, then SSHs to EC2 and runs `git pull && docker compose up -d --build`.
Add `EC2_HOST` and `EC2_SSH_KEY` repo secrets to enable it.

## License

MIT. See `LICENSE`.
