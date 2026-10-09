# AutoClip AI

Conversational AI video clipping. Upload a long-form video, chat with it in
natural language, and get short-form clips back — built for TikTok, Reels and
Shorts, in whatever length/format you ask for (15s, 30s, 60s, 9:16, 1:1,
16:9 — freeform, not a fixed menu).

**Live demo:** https://15.206.112.113 (Let's Encrypt IP certificate; 2 chat
queries per visitor per day).

A deep-agent orchestrator (LangChain's `deepagents`, built on LangGraph)
drives the conversation and decides which tools to call. Clip discovery is
RAG-driven: a LlamaIndex-backed semantic index over every analyzed moment,
so "clips where he roasts a competitor" retrieves on meaning, not a fixed
style enum. Chunk analysis runs as a chunk-parallel LangGraph Send-API
fan-out underneath the agent, exposed to it as a tool.

**Every model call goes through OpenRouter**, including embeddings — using
only cheap Gemini models and cheap open-source models (see
[Provider notes](#provider-notes)). One API key, nothing runs locally.

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
POST /api/chat/message  (routers/chat.py — per-IP daily quota, 429 when spent)
     │
     ▼
agent/orchestrator.py   deepagents.create_deep_agent()
   model: OpenRouter (OPENROUTER_MODEL, default google/gemini-2.5-flash, max_tokens 8192)
   checkpointer: LangGraph PostgresSaver on a psycopg pool (MemorySaver if
                 LANGGRAPH_PG_URL unset); thread_id = video_id
     │
     ├─ tool: ingest_and_analyze_video ──▶ pipeline/graph.py
     │         │
     │         │  transcription (OpenRouter audio) → scene_detection (ffmpeg)
     │         │  → analysis subgraph:
     │         │     chunk_planner (120s windows, 10s overlap)
     │         │     Send-API fan-out — one chunk_analyzer per window
     │         ▼
     │    chunk_analyzer × N (OpenRouter vision, up to 24 sampled frames + transcript,
     │         │              ≤5 moments per chunk, structured output)
     │         │  fan-in (operator.add reducer)
     │         ▼
     │    global_fusion (merge ≥50% temporal overlap, BGE-M3 embeddings,
     │         │         drop cosine-duplicates ≥0.92, sort by convergence)
     │         ▼
     │    services/moment_store.py → MomentRecord rows + rag/index.py (LlamaIndex, pgvector)
     │
     ├─ tool: search_moments ──▶ rag/retriever.py (semantic search, filtered by video_id)
     │
     ├─ tool: select_and_produce_clips ──▶ pipeline generation subgraph:
     │         clip_selector.py (RAG retrieval → snap to scene cuts/word timings →
     │         OpenRouter scoring + title) → production.py (ffmpeg cut, face-centred
     │         reframe, burned-in captions, thumbnail). 1–10 clips per call.
     │
     ├─ tool: modify_clip ──▶ services/clip_reprocess.py (shared with PUT /api/clips/{id})
     │
     └─ tool: get_video_status ──▶ DB (Video / Clip / MomentRecord)

   subagents: retrieval-agent (search_moments), critic-agent (reviews clip
   scores), production-agent (select_and_produce_clips / modify_clip)

Live progress: pipeline nodes publish to Redis channel pipeline:{video_id};
GET /api/chat/stream/{video_id} relays it as SSE (open, chunk_done, moments,
clip_ready, done).
```

## Provider notes

| Call site | Default model (via OpenRouter) | $/1M in / out | Notes |
|---|---|---|---|
| Orchestrator + subagent reasoning | `google/gemini-2.5-flash` | 0.30 / 2.50 | Needs reliable tool-calling — the one place not using the cheapest tier. |
| Clip scoring, titles | `qwen/qwen3-30b-a3b-instruct-2507` (open source) | 0.048 / 0.193 | Structured-output calls. Score = weighted 6 dims (hook .20, emotion .20, retention .20, shareability .15, novelty .15, controversy .10). |
| Chunk vision analysis | `google/gemini-2.5-flash-lite` | 0.10 / 0.40 | `chunk_analyzer.py` samples frames every 2.5s via ffmpeg, keeps at most 24 (`MAX_SAMPLED_FRAMES`), base64-encodes them as JPEGs and sends them as `image_url` parts in one chat completion alongside the transcript window. Note the cap means a full 120s chunk only gets visual coverage of its first ~60s (see Known issues). |
| Audio transcription | `google/gemini-2.5-flash-lite` | 0.10 / 0.40 | OpenRouter has no dedicated ASR endpoint, so `services/transcription.py` sends each ~10-min audio segment (parallel, `TRANSCRIBE_PARALLELISM`) as an `input_audio` content part and asks for a phrase-level transcript with timestamps. Per-word timestamps are *approximated* by spreading each phrase's words evenly across its window — not forced alignment, but good enough for the boundary snapping `clip_selector.py` does. |
| Moment embeddings | `baai/bge-m3` (open source, 1024-dim) | 0.01 / — | OpenRouter's `/embeddings` API, batched. Swap via `EMBEDDING_MODEL_NAME` + `EMBEDDING_DIM` (must match; it sizes the pgvector columns). |

## Cost & latency

This was live-tested end to end (Docker build, real OpenRouter calls, real
chat turns producing real moment detection) — see **[BENCHMARKS.md](BENCHMARKS.md)**
for the writeup, including 8 real bugs that only surfaced by actually running
it. Short version: a full chat turn against a short (~24s) test video took
**18–56s wall time** and **≈$0.03–0.07 per turn**, measured with the
*previous* defaults (Claude Sonnet 4.5 orchestrator). The current cheap-model
defaults cost roughly 5–10× less per token but have not been re-benchmarked.
That's a small sample from synthetic test clips, not a rigorous benchmark:

```bash
make up
python backend/scripts/benchmark.py --video path/to/sample.mp4
```

It uploads a video, drives a chat turn through `/api/chat/message` (so it
consumes one unit of the daily quota — raise `DAILY_QUERY_LIMIT` locally),
times each phase, reads `/api/telemetry` for per-model token counts, and
appends a timestamped entry to `BENCHMARKS.md`.

**Open item from live testing:** the orchestrator was once caught narrating
a clip result that didn't match the database. The system prompt now forbids
this, but it hasn't been re-verified live — see BENCHMARKS.md's "Known gap".

**Cost drivers, for back-of-envelope estimates on longer videos:**

- **Vision (chunk analysis):** 1 vision call per 2-min chunk (~30/hour of
  video), each with up to 24 JPEG frames + transcript text.
- **Audio (transcription):** 1 audio call per ~10-min segment (~6/hour).
- **Text:** a handful of orchestrator tool-calling turns per chat message,
  plus 2 lite calls per produced clip (score + title).
- Check current pricing at https://openrouter.ai/models — `OPENROUTER_MODEL`,
  `OPENROUTER_MODEL_VISION` and `OPENROUTER_MODEL_AUDIO` are independently
  configurable, so you can trade cost for quality per call site.

## Quick start

Prereqs: Docker + Docker Compose, and an [OpenRouter API key](https://openrouter.ai/keys)
**with real balance on it** — every LLM call goes through that one key, and a
402 mid-request looks like a random failure otherwise.

```bash
git clone https://github.com/AnirudhGupta007/autoclip-ai.git
cd autoclip-ai
cp .env.example .env
# edit .env: paste in OPENROUTER_API_KEY
make up
```

Browse to **http://localhost** (plain HTTP; the HTTPS setup is prod-only, see
[DEPLOY.md](DEPLOY.md)). First build pulls pgvector + redis images and
installs Python deps — expect a few minutes.

### Make targets

```
make help       # list targets
make up         # build + start all 4 services (postgres+pgvector, redis, backend, frontend)
make down       # stop (volumes survive)
make nuke       # stop + wipe volumes (postgres, redis, uploads, outputs)
make ps         # service status
make logs       # tail all services
make logs-be    # tail backend only
make rebuild    # rebuild backend image after code changes
make shell-be   # bash into backend container
make shell-db   # psql into postgres
make setup      # local (non-Docker) deps: uv sync + npm install
make backend    # local FastAPI on :8000
make frontend   # local Vite dev server on :5173
make dev        # both of the above
make lint       # verify the LangGraph pipeline imports/compiles
make eval       # precision@k harness on the host (needs backend/eval/dataset.json)
make clean      # remove build artifacts and caches
```

## API

All under `/api`. Every endpoint except `/health` and `/auth/*` needs a
session cookie (401 otherwise), and is scoped to the caller's own videos —
another user's video/clip id is a **404**.

| Method & path | What |
|---|---|
| `POST /auth/signup` `{email, password}` | Create account (password ≥ 10 chars), sets the session cookie. 409 if taken; 429 past `SIGNUP_LIMIT_PER_IP_PER_DAY`. |
| `POST /auth/login` `{email, password}` | Generic 401 on bad credentials; 429 past `LOGIN_LIMIT_PER_15_MIN` per IP+email. |
| `POST /auth/demo` | Sign into the shared read-only demo account (see `scripts/seed_demo.py`). |
| `POST /auth/logout` · `GET /auth/me` | Revoke this session · `{id, email, is_admin, is_demo, video_count, max_videos, queries_remaining, query_limit}`. |
| `GET /files/{uploads\|outputs}/{video_id}/…` | Ownership-checked media (source videos, clips, thumbnails); nginx serves the bytes via `X-Accel-Redirect`. |
| `POST /chat/message` `{message, video_id?}` | Runs the orchestrator. Returns `{response, clips, moment_count, queries_remaining}` + `X-Queries-Remaining` header; **429** when the daily quota is spent. |
| `GET /chat/quota` | `{limit, remaining, resets_in_seconds}` for the signed-in user (`null` = unlimited admin). |
| `GET /chat/stream/{video_id}` | SSE progress stream (Redis pub/sub relay). |
| `GET /chat/analysis/{video_id}` | Analyzed flag, duration, moment/clip counts. |
| `POST /videos/upload` | Multipart `file`; `.mp4 .mov .avi .mkv .webm`, max 500MB. Non-admins: ≤ `MAX_VIDEOS_PER_USER` stored videos, each ≤ `MAX_VIDEO_MINUTES_DEMO` min. Demo account: 403. |
| `GET /videos` · `GET /videos/{id}` · `DELETE /videos/{id}` | List / get / delete (removes files + DB row). |
| `GET /clips?video_id=` · `GET /clips/{id}` | List / get clips. |
| `PUT /clips/{id}` | Trim or change caption style (re-cuts + re-captions). |
| `POST /clips/{id}/export` `{format}` | Re-encode to `9:16`, `1:1` or `16:9`. |
| `GET /clips/{id}/download/{format\|original}` | Download a clip file. |
| `POST /search` | Semantic moment search over the caller's videos. |
| `GET /music/search?q&mood&per_page` | Pexels proxy (needs `PEXELS_API_KEY`). |
| `GET /health` · `GET /telemetry` | Liveness; per-model OpenRouter call/token counters (admins only). |

There are no public static mounts: `file_url`, `thumbnail_url` and
`source_url` in responses point at `/api/files/...`.

### Accounts

Self-hosted (`backend/src/autoclip/auth/`): argon2id password hashes, an
opaque random session token in an httpOnly `SameSite=Lax` cookie
(`__Host-session` + `Secure` when `COOKIE_SECURE=1`), only `sha256(token)`
stored in `sessions` (30-day sliding expiry). `ADMIN_EMAILS` accounts are
admins (no quota, no upload caps). CORS uses the explicit `ALLOWED_ORIGINS`
list, and state-changing requests from a foreign `Origin` get a 403. The deep
agent's tools never trust LLM-supplied ids: the user id travels in the
LangGraph `RunnableConfig` (plus a ContextVar backstop) and each tool checks
ownership; chat threads are `u:{user}:v:{video}`.

### Daily query quota

Only `POST /api/chat/message` is metered (`services/rate_limit.py`): a Redis
counter per UTC day per user (`DAILY_QUERY_LIMIT`, default 2; admins
unlimited; the demo account shares one `DEMO_DAILY_QUERY_LIMIT` pool), a
per-IP backstop (`IP_DAILY_QUERY_LIMIT`, default 20) and an optional global
cap (`DAILY_GLOBAL_QUERY_LIMIT`, default 0 = off; prod sets 100). The client IP is nginx's `X-Real-IP`, trusted only from a private /
loopback peer. A unit is refunded if the orchestrator raises. Falls back to an
in-process counter if Redis is unavailable.

## Frontend

Vite + React 18 + Tailwind, served by nginx (which also proxies `/api` to
the backend and serves authorised media from its `internal` `/_protected/`
locations). `/login`, `/signup`, `/demo` (signs into the demo account),
`/library` (your videos: status, clips, open, delete) and `/studio` — the
last two behind a session.

- **`/` — Landing.** A 560vh scroll-driven react-three-fiber scene
  (`components/landing/FilmScene.jsx`): a spiral tunnel of film stills where a
  few frames get "picked" and become playing 9:16 clip cards, with four text
  chapters fading in over it. Footage is CC-BY Blender Foundation films
  (*Tears of Steel*, *Sintel*) — keep the footer credit. Followed by a format
  marquee, capability cards, the engine stack, and a CTA.
- **`/studio` — Chat.** Upload zone → chat composer with suggested prompts →
  live progress from the SSE stream → clip cards (inline player, score ring,
  6 score bars, transcript, download). Shows remaining daily queries and
  disables the composer on 429.

## Project layout

```
autoclip-ai/
├─ backend/
│  ├─ src/autoclip/
│  │  ├─ main.py                    # FastAPI app, CORS, static mounts, /api/health, /api/telemetry
│  │  ├─ config.py                  # env-driven models, limits, tuning knobs
│  │  ├─ database.py / models.py    # SQLAlchemy (Video, Clip, MomentRecord) + pgvector column (sqlite fallback)
│  │  ├─ schemas.py                 # Pydantic request/response models
│  │  ├─ llm/openrouter.py          # the single OpenRouter chat-model client factory
│  │  ├─ rag/
│  │  │  ├─ embedding.py            # LlamaIndex embedding wrapper → OpenRouter BGE-M3
│  │  │  ├─ store.py                # PGVectorStore (table data_moment_nodes) / in-memory fallback
│  │  │  ├─ index.py                # moment → node indexing
│  │  │  └─ retriever.py            # semantic search, shared by clip_selector + /api/search
│  │  ├─ agent/
│  │  │  ├─ tools.py                # the 5 tools wrapping pipeline / RAG / DB
│  │  │  └─ orchestrator.py         # deepagents.create_deep_agent() + 3 subagents
│  │  ├─ pipeline/
│  │  │  ├─ graph.py                # LangGraph wiring (Send API, subgraphs, checkpointer)
│  │  │  ├─ state.py                # TypedDict state + Pydantic structured-output models
│  │  │  ├─ telemetry.py            # per-model OpenRouter call/token counters
│  │  │  └─ agents/
│  │  │     ├─ chunk_planner.py     # splits video into 2-min windows
│  │  │     ├─ chunk_analyzer.py    # frame-sampled OpenRouter vision call per chunk
│  │  │     ├─ global_fusion.py     # temporal + embedding dedupe
│  │  │     ├─ clip_selector.py     # RAG retrieval + boundary snapping + scoring/titles
│  │  │     └─ production.py        # ffmpeg cut / reframe / caption / thumbnail
│  │  ├─ services/
│  │  │  ├─ transcription.py        # OpenRouter audio-part transcription + segmenting
│  │  │  ├─ scene_detector.py       # ffmpeg scene filter
│  │  │  ├─ video_processor.py      # face detection (Haar), cuts, reframing
│  │  │  ├─ caption_engine.py       # ASS subtitle generation, 5 caption styles
│  │  │  ├─ thumbnail_gen.py        # clip thumbnails
│  │  │  ├─ embeddings.py           # OpenRouter embeddings + cosine helpers
│  │  │  ├─ clip_reprocess.py       # shared re-cut/re-caption (HTTP route + agent tool)
│  │  │  ├─ events.py               # Redis pub/sub publishers + SSE subscriber
│  │  │  ├─ moment_store.py         # persist moments to DB + RAG index
│  │  │  ├─ rate_limit.py           # per-IP / global daily chat quota
│  │  │  └─ music_service.py        # Pexels music search
│  │  ├─ utils/ffmpeg.py · subtitle.py  # ffmpeg/ffprobe wrappers (argv lists, no shell), subtitle helpers
│  │  └─ routers/
│  │     ├─ chat.py                 # message, quota, SSE stream, analysis status
│  │     ├─ videos.py · clips.py    # upload/CRUD, trim, export, download
│  │     ├─ search.py               # POST /api/search
│  │     └─ music.py                # GET /api/music/search
│  ├─ scripts/eval.py               # precision@k harness (in-process pipeline)
│  ├─ scripts/benchmark.py          # live cost/latency benchmark → BENCHMARKS.md
│  ├─ scripts/test_matrix.py        # 10-ask format/length adherence matrix
│  └─ eval/dataset.example.json
├─ frontend/                        # Vite + React + Tailwind + react-three-fiber
│  ├─ src/pages/Landing.jsx · Chat.jsx
│  ├─ src/components/               # ClipCard, UploadZone, ChatMessage, landing/FilmScene, …
│  ├─ public/film/                  # CC-BY stills + clips for the landing scene
│  ├─ nginx.conf                    # dev/local: HTTP on :80
│  └─ nginx.prod.conf               # prod: HTTPS on :443, :80 for ACME + redirect
├─ infra/postgres-init.sql          # CREATE EXTENSION vector on first boot
├─ docker-compose.yml               # postgres+pgvector, redis, backend (127.0.0.1:8000), frontend (:80)
├─ docker-compose.prod.yml          # prod overlay: 443, certs, ACME webroot
├─ .github/workflows/deploy.yml     # CI + deploy to EC2 via SSM
├─ DEPLOY.md · EVALUATION.md · BENCHMARKS.md
└─ Makefile
```

## Configuration (env vars)

| Var | Default | What |
|---|---|---|
| `OPENROUTER_API_KEY` | — | Required. |
| `OPENROUTER_BASE_URL` | `https://openrouter.ai/api/v1` | |
| `OPENROUTER_MODEL` | `google/gemini-2.5-flash` | Deep-agent orchestrator + subagents. |
| `OPENROUTER_MODEL_LITE` | `qwen/qwen3-30b-a3b-instruct-2507` | Clip scoring, titles. |
| `OPENROUTER_MODEL_VISION` | `google/gemini-2.5-flash-lite` | Frame-sampled chunk analysis. |
| `OPENROUTER_MODEL_AUDIO` | `google/gemini-2.5-flash-lite` | Audio-part transcription. |
| `EMBEDDING_MODEL_NAME` | `baai/bge-m3` | Embedding model on OpenRouter. |
| `EMBEDDING_DIM` | `1024` | Must match the model's output dim (pgvector column size). |
| `DAILY_QUERY_LIMIT` | `2` | Chat messages per user per UTC day (admins unlimited). |
| `IP_DAILY_QUERY_LIMIT` | `20` | Per-IP backstop across accounts; 0 = off. |
| `ADMIN_EMAILS` | — | Comma-separated admin accounts. |
| `ALLOWED_ORIGINS` | `http://localhost:5173,…` | CORS allow-list (never `*`). |
| `COOKIE_SECURE` | `0` | `1` behind HTTPS → `__Host-session` Secure cookie. |
| `MAX_VIDEOS_PER_USER` / `MAX_VIDEO_MINUTES_DEMO` | `5` / `60` | Upload caps for non-admins. |
| `DEMO_EMAIL` / `DEMO_DAILY_QUERY_LIMIT` | `demo@autoclip.local` / `10` | Shared demo account. |
| `DAILY_GLOBAL_QUERY_LIMIT` | `0` (off) | Chat messages per UTC day across all visitors. |
| `CHUNK_LENGTH_SECONDS` | `120` | Analysis chunk size. |
| `CHUNK_OVERLAP_SECONDS` | `10` | Overlap (helps global_fusion catch boundary moments). |
| `CHUNK_MAX` | `60` | Safety bound on chunk count (≈110 min of video). |
| `SCENE_THRESHOLD` | `0.3` | ffmpeg scene-change sensitivity. |
| `TRANSCRIBE_SEGMENT_SECONDS` | `600` | Audio split size for long-form. |
| `TRANSCRIBE_SINGLE_SHOT_MAX` | `780` | Skip splitting when video ≤ this. |
| `TRANSCRIBE_PARALLELISM` | `4` | Concurrent OpenRouter calls during audio segmenting. |
| `DATABASE_URL` | sqlite file in `src/` | Compose sets Postgres. |
| `USE_PGVECTOR` | — | Compose sets `1`. |
| `LANGGRAPH_PG_URL` | unset | If set, `PostgresSaver` instead of `MemorySaver` (also backs the agent's thread state). |
| `REDIS_URL` | unset | Enables SSE live updates and the shared quota counter. |
| `UPLOAD_DIR` / `OUTPUT_DIR` | `src/uploads` / `src/outputs` | Compose sets `/app/uploads` / `/app/outputs`. |
| `CORS_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` | Compose sets `*`. |
| `POSTGRES_PASSWORD` | `autoclip_dev_password` | Compose only. Set a real one in prod **before** first boot (the `pgdata` volume keeps the original). |
| `PEXELS_API_KEY` | — | Optional, for `/api/music/search`. |
| `LANGSMITH_TRACING` | `false` | LangSmith auto-instrumentation; only enable with a real key. |
| `LANGSMITH_API_KEY` / `_PROJECT` / `_ENDPOINT` | — / `Autoclip` / LangSmith cloud | |

`MAX_UPLOAD_SIZE` is hard-coded at 500MB in `config.py`. The compose file
wires everything; just fill in `OPENROUTER_API_KEY`.

## Observability

- **`GET /api/telemetry`** — OpenRouter call count + token usage per label (`vision`, `lite_scoring`, `lite_title`; transcription isn't counted)
- **`backend/scripts/eval.py`** — precision@k vs labeled `eval/dataset.json`
- **`backend/scripts/test_matrix.py`** — length/aspect adherence across 10 asks
- **`backend/scripts/benchmark.py`** — real end-to-end cost/latency, appended to `BENCHMARKS.md`
- **LangSmith** — set `LANGSMITH_TRACING=true` + a real `LANGSMITH_API_KEY`
- **`make logs-be`** — per-chunk timing and cache hit rate per call

See [EVALUATION.md](EVALUATION.md) for details.

## Deployment & CI/CD

Production is a single EC2 instance (t3a.small, ap-south-1) running the
compose stack **with the prod overlay** (plain `docker compose up` drops HTTPS):

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

`.github/workflows/deploy.yml` runs on every push/PR: `npm ci && npm run
build` for the frontend and `compileall` for the backend. On `master` it then
assumes an AWS role via GitHub OIDC (secret `AWS_DEPLOY_ROLE_ARN`), sends an
SSM Run Command that does `git reset --hard <sha>` in `/opt/autoclip` and
rebuilds with the prod overlay, and smoke-tests `/api/health`. No SSH port is
open. Full setup in [DEPLOY.md](DEPLOY.md).

## Known issues

Found in a full code review (2026-10-01); not yet fixed.

**Security / public-demo**
- ~~No authentication or ownership~~ — fixed: accounts, per-user scoping,
  authorised media (see API / Accounts). No email verification yet.
- Thread history grows unbounded (threads are now per user + video).
- Only `/chat/message` is metered — `/search` (paid embeddings), clip
  edit/export (ffmpeg re-encodes) and uploads are not. `ClipUpdate` times are
  unvalidated (negative / inverted / whole-video ranges accepted).
- nginx accepts 2GB bodies vs the backend's 500MB cap, and buffers them to
  disk first; no per-IP upload quota.
- `chat.py` returns raw exception text to clients; `/api/telemetry` is public.

**Pipeline correctness**
- Chunk files/frames are written to `outputs/chunks/source_{i}…` — every
  upload is named `source.*`, so concurrent analyses collide and stale frames
  from a previous video can leak into the next one's vision call.
- The 24-frame cap means only the first ~60s of each 120s chunk is seen.
- `ingest_and_analyze_video` also runs generation with 4 default clip configs
  (wasted renders + LLM calls, not saved) and publishes `done`, which closes
  the SSE stream before the real clips are produced.
- Re-analysis and video deletion don't remove old RAG vector rows, so search
  returns stale/duplicate/deleted moments. Deleting an analyzed video on
  Postgres fails with an FK violation (MomentRecord has no cascade) after its
  files are already removed.
- Editing a clip (`clip_reprocess.py`) drops the 9:16 reframe, stores an
  absolute path that breaks its URL, and doesn't invalidate old exports.
- Production always burns `bold_pop` captions regardless of requested style;
  clip end isn't clamped to the video duration.

**Frontend**
- One 300s axios timeout for everything: long analyses time out client-side
  after the quota unit is already spent; large uploads can too.
- First-upload errors aren't shown (messages only render after a video exists).
- Double-clicking a suggested prompt can send twice (two quota units).
- Tailwind `white/8` opacity classes don't exist, so some tracks are invisible
  and some borders render light grey; `.text-gold-sheen` never animates.
- Landing scene forces `dpr ≥ 1.5` and preloads all clips — heavy on mobile.

**Infra**
- Smoke test only checks a static `/api/health`; no rollback on failure.
- No `uv.lock` committed, so backend builds resolve deps fresh each time.
- No log rotation, no HSTS/security headers, no gzip/cache headers for
  static assets, backend container runs as root.

## License

MIT. See `LICENSE`. Landing footage: Blender Foundation, CC-BY.
