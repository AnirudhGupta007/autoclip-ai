# AutoClip AI

Conversational AI video clipping. Upload a long-form video, chat with it in
natural language, and get short-form viral clips back — optimized for TikTok,
Reels, and Shorts.

Built around a chunk-parallel LangGraph pipeline that takes one Gemini 2.5
Flash multimodal call per chunk instead of orchestrating hand-rolled visual /
audio / text agents. Transcription runs on Groq Whisper Turbo (216× realtime),
chunk analysis runs concurrently via LangGraph's Send API, results stream to
the UI over SSE as they finish.

```
You:  "Give me 4 funny TikTok clips under 30 seconds"
AI:   Analyzing 12 chunks in parallel...
      [chunk 3 done]  [chunk 7 done]  [chunk 1 done] ...
      24 moments found, fusing across chunk overlaps...
      [4 clips ready]
        1. "The Database Was a Spreadsheet" — 28s · 9:16 · 8.9/10
        2. "Nobody Told the CEO"           — 24s · 9:16 · 8.4/10
        3. ...

You:  "Make clip 2 longer and give me clip 1 in square format"
AI:   Reusing cached moment map (no re-analysis), regenerating 2 clips ...
```

## Why it's interesting

| What | How |
|---|---|
| **True parallel time-chunked analysis** | LangGraph **Send API** fans out one `chunk_analyzer` worker per 2-min window. Annotated `operator.add` state reducer lets workers append moments concurrently without lock contention. |
| **Let the model do the work** | One **Gemini 2.5 Flash** multimodal call per chunk (native video + audio + transcript → structured `Moment[]` via Pydantic). Replaces ~1000 lines of hand-rolled frame sampling, librosa peak-finding, and modality fusion. |
| **216× realtime ASR** | **Groq `whisper-large-v3-turbo`**. 2 hr podcast transcribes in ~30s wall time via parallel 10-min Opus segments. |
| **Resumable runs** | LangGraph **Postgres checkpointer** persists graph state per `thread_id`. Crash mid-run, resume from the last chunk. Multi-turn chat reuses the cached moment map (no re-analysis on "make clip 2 longer"). |
| **Semantic moment search** | Embeddings on every moment via `gemini-embedding-001`, stored in a **pgvector** column. `POST /api/search` does cosine search — across one video or your whole library. Falls back to in-memory cosine on SQLite. |
| **Live streaming UX** | Per-chunk `chunk_done` and `clip_ready` events on a Redis pub/sub channel; FastAPI SSE endpoint pipes them to the React frontend, so moments and skeleton clip cards fill in as the pipeline runs. |
| **`-c copy` clip cuts** | ffmpeg stream-copy with keyframe-snap fallback. 20× faster than re-encoding when keyframe-aligned, which podcast/talking-head content almost always is. |
| **Eval harness** | `scripts/eval.py` runs labeled videos through the pipeline and reports **precision@k** plus Gemini **prompt cache hit rate**. No vibes-driven AI. |

## Architecture

```
                ┌─────────────────────────────┐
                │ FRONTEND  (nginx + React)    │
                │  ▸ chat UI                   │
                │  ▸ EventSource → /api/chat/  │
                │    stream/{video_id} (SSE)   │
                └──────────────┬──────────────┘
                               │
                ┌──────────────▼─────────────────┐
                │ BACKEND  (FastAPI + LangGraph)  │
                │                                  │
                │   transcription_node            │
                │     │  (Groq Whisper Turbo,     │
                │     │   parallel 10-min Opus)   │
                │     ▼                            │
                │   scene_detection_node          │
                │     │  (ffmpeg scene filter)    │
                │     ▼                            │
                │   chunk_planner                 │
                │     │  (2-min windows,           │
                │     │   10s overlap)             │
                │     ▼  Send API fan-out         │
                │   ┌─────────────────────────┐   │
                │   │ chunk_analyzer × N      │   │ ──▶ moments + cache
                │   │  (Gemini 2.5 Flash       │   │     hit rate telemetry
                │   │   multimodal, structured │   │
                │   │   output → Moment[])     │   │
                │   └────────────┬────────────┘   │
                │                ▼ fan-in          │
                │   global_fusion                 │
                │     │ (temporal + cosine        │
                │     │  embedding dedupe)        │
                │     ▼                            │
                │   ── pipeline_events.publish ── │ ──▶ Redis pub/sub
                │                                  │      │
                │   clip_selector → production   │     SSE
                │   (-c copy, captions, reframe) │      ▼
                └────────┬───────────┬───────────┘   frontend
                         │           │
                ┌────────▼──┐   ┌────▼────────────┐
                │ POSTGRES   │   │ REDIS           │
                │ + pgvector │   │ pub/sub + cache │
                │ ▸ langgraph│   └─────────────────┘
                │   checkpts │
                │ ▸ moments  │
                │   (embed)  │
                └────────────┘
```

## Quick start

Prereqs: Docker + Docker Compose. That's it. A Gemini key and a Groq key.

```bash
git clone https://github.com/AnirudhGupta007/autoclip-ai.git
cd autoclip-ai
cp .env.example .env
# edit .env: paste in GEMINI_API_KEY and GROQ_API_KEY
make up
```

Browse to **http://localhost**. First build is ~3 min (pulls pgvector + redis
images, installs Python deps). Subsequent boots are seconds.

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
│  │  ├─ pipeline/
│  │  │  ├─ graph.py                # the LangGraph wiring (Send API, subgraphs, checkpointer)
│  │  │  ├─ state.py                # TypedDict state + Pydantic structured-output models
│  │  │  ├─ telemetry.py            # Gemini cache hit rate counters
│  │  │  └─ agents/
│  │  │     ├─ chunk_planner.py     # splits video into 2-min windows
│  │  │     ├─ chunk_analyzer.py    # one Gemini 2.5 Flash call per chunk
│  │  │     ├─ global_fusion.py     # temporal + embedding dedupe
│  │  │     ├─ clip_selector.py     # picks moments per user request, scores them
│  │  │     └─ production.py        # ffmpeg cut/caption/reframe/thumbnail
│  │  ├─ services/
│  │  │  ├─ transcription.py        # Groq Whisper + audio chunking for long videos
│  │  │  ├─ scene_detector.py       # ffmpeg scene filter (replaces PySceneDetect)
│  │  │  ├─ video_processor.py      # face detection, -c copy cuts, reframing
│  │  │  ├─ embeddings.py           # gemini-embedding-001 + cosine helpers
│  │  │  ├─ events.py               # Redis pub/sub publishers + SSE subscriber
│  │  │  └─ moment_store.py         # persist moments to Postgres for /api/search
│  │  └─ routers/
│  │     ├─ chat.py                 # POST /api/chat/message  + GET /api/chat/stream/{id}
│  │     ├─ videos.py · clips.py    # CRUD
│  │     └─ search.py               # POST /api/search (pgvector cosine)
│  ├─ scripts/eval.py               # precision@k harness
│  └─ eval/dataset.example.json
├─ frontend/                        # Vite + React + Tailwind
│  └─ src/
│     ├─ pages/Chat.jsx             # main UI, opens EventSource on send
│     ├─ services/api.js            # axios + openPipelineStream(EventSource)
│     └─ components/                # HeroSection, UploadZone, ClipCard, ProcessingIndicator, ...
├─ infra/postgres-init.sql          # CREATE EXTENSION vector on first boot
├─ docker-compose.yml
└─ Makefile
```

## Pipeline walkthrough

```python
# Single Gemini call per chunk — structured output, no parsing yak-shaving
class GeminiMoment(BaseModel):
    start: float
    end: float
    description: str
    transcript: str
    style_tags: list[Literal["hot_take", "story", "quote", ...]]
    visual_energy: float
    audio_energy: float
    text_hook_strength: float
    convergence_score: float    # only > 0.7 when 2+ modalities co-fire

# In graph.py: parallel fan-out, fan-in, and a Postgres checkpoint
def route_to_chunks(state):
    return [Send("chunk_analyzer", {"chunk_plans": [p], "video_id": state["video_id"]})
            for p in state["chunk_plans"]]
```

For a 1-hr podcast, this fans out ~30 concurrent chunk workers; each one runs
its own Gemini call, publishes its moments to Redis as they land, and writes
into the shared `moment_map_raw` list via `operator.add`. `global_fusion`
then dedupes moments in the 10s overlap regions (timestamp + cosine), embeds
each moment, and persists to Postgres.

## Configuration (env vars)

| Var | Default | What |
|---|---|---|
| `GEMINI_API_KEY` | — | Required. |
| `GROQ_API_KEY` | — | Required (transcription). |
| `GEMINI_MODEL_MULTIMODAL` | `gemini-2.5-flash` | Per-chunk multimodal analyzer. |
| `GEMINI_MODEL_LITE` | `gemini-2.5-flash-lite` | Intent parsing, titles, scoring. |
| `GEMINI_EMBEDDING_MODEL` | `gemini-embedding-001` | Moment embeddings. |
| `GROQ_TRANSCRIPTION_MODEL` | `whisper-large-v3-turbo` | 216× realtime ASR. |
| `CHUNK_LENGTH_SECONDS` | `120` | Analysis chunk size. |
| `CHUNK_OVERLAP_SECONDS` | `10` | Overlap (helps global_fusion catch boundary moments). |
| `CHUNK_MAX` | `60` | Safety bound on chunk count. |
| `TRANSCRIBE_SEGMENT_SECONDS` | `600` | Audio split size for long-form (Groq 25 MB cap). |
| `TRANSCRIBE_SINGLE_SHOT_MAX` | `780` | Skip splitting when video ≤ this. |
| `TRANSCRIBE_PARALLELISM` | `4` | Concurrent Groq calls during audio chunking. |
| `LANGGRAPH_PG_URL` | unset | If set, swaps `MemorySaver` for `PostgresSaver` (resumable runs). |
| `REDIS_URL` | unset | If set, enables SSE live updates; otherwise pub/sub is a no-op. |
| `USE_PGVECTOR` | `1` on Postgres | Use `embedding <=> query` for search; falls back to in-memory cosine on SQLite. |
| `LANGSMITH_TRACING`, `LANGSMITH_API_KEY` | unset | LangSmith auto-instrumentation. |

The compose file wires all of these for you; just fill in the keys.

## Observability

- **`GET /api/telemetry`** — rolling Gemini call count + prompt cache hit rate per model
- **`backend/scripts/eval.py`** — precision@k vs labeled `eval/dataset.json`
- **LangSmith** — set `LANGSMITH_API_KEY` and every node + Gemini call appears as a span
- **`make logs-be`** — backend logs include per-chunk timing and cache hit rate per call

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
cp .env.example .env       # paste in your keys
make up                    # ~3 min on a t3.small / t2.micro
```

CI/CD: `.github/workflows/deploy.yml` runs an AST sanity check on every push to
`master`, then SSHs to EC2 and runs `git pull && docker compose up -d --build`.
Add `EC2_HOST` and `EC2_SSH_KEY` repo secrets to enable it.

## License

MIT. See `LICENSE`.
