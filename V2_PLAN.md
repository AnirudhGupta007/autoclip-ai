# AutoClip AI v2 — Deep Dive Architecture Plan

A rewrite plan that turns AutoClip AI from a batch-oriented demo into a streaming, chunk-parallel, "everything in seconds" system — with a clean AWS deployment path and a portfolio story that holds up under recruiter questioning.

---

## 1. Why the current architecture is backwards

The v1 pipeline is sequential, batch-oriented, and assumes slow infrastructure. Three concrete examples:

| Stage | Current reality | Actual bottleneck |
|---|---|---|
| Transcription | AssemblyAI, 10–30% of audio runtime → 60-min video = 6–18 min wait | AssemblyAI is a 2020s choice. Modern ASR (Groq Whisper Turbo) runs at **216× realtime** — 60 min audio in ~17 s. |
| Visual agent | Two passes (coarse → dense), 10 frames/batch, 4 s sleep between calls | Hand-rolled throttle built around free-tier Gemini RPM. With paid keys, throughput is 10× higher. |
| Pipeline control | One blocking `pipeline.invoke()`, user sees nothing for minutes | No streaming. No chunking. No parallel work during upload. |

Plus the subtle stuff:
- Video fully uploaded to EC2 *before* any work starts
- Clips re-encoded with `libx264` when `-c copy` would work 20× faster
- `librosa` loads the entire audio into RAM → OOM risk on 1 GB t2.micro
- "Multimodal fusion" reinvents what a native video-understanding model does in one call

**Core philosophical flaw:** the pipeline treats LLMs as a bottleneck to be orchestrated around, when modern models are fast enough that orchestration *is* the bottleneck.

---

## 2. v2 design philosophy

Three inversions:

1. **Chunk-first, stream-first.** The video is split into 2-minute overlapping chunks the moment the first bytes land on S3. Every downstream stage operates on chunks in parallel. The user sees moments/clips appearing live.
2. **Let the model do the hard work.** Replace 3 hand-rolled agents (visual / audio / text) with **one Gemini 2.5 Flash call per chunk** that takes the chunk video+audio directly and returns structured moments with confidence scores. Keep LangGraph for *coordination* (fan-out, retries, merging, state) — not for re-implementing what the model already does.
3. **Latency budget is the contract.** Every stage has a target. If it misses, redesign the stage — don't just add more parallelism.

---

## 3. Latency targets (60-min podcast)

| Milestone | v1 (today) | v2 (target) | How |
|---|---|---|---|
| Upload → first moment visible | ~8 min | **8–12 s** | Direct S3 upload + first chunk analyzed while rest uploads |
| All moments identified | ~15 min | **45–60 s** | 30 parallel chunk workers (60 min / 2 min = 30) |
| First clip playable | ~20 min | **30–45 s after moment** | `-c copy` cut, parallel caption generation |
| "Make clip 2 longer" | ~2 min | **2–4 s** | Cached moment map, re-cut only, skip re-analysis |
| Cold start (first request) | ~5 s | **<500 ms** | Pre-warmed workers, connection pools |

---

## 4. Tech stack changes

| Component | v1 | v2 | Why |
|---|---|---|---|
| ASR | AssemblyAI | **Groq `whisper-large-v3-turbo`** | 216× realtime vs ~5×. 60 min audio = 17 s. Free tier = 7200 s/day. |
| Multimodal analysis | 3 agents (visual / audio / text) + fusion | **Gemini 2.5 Flash** (native video+audio) with structured output | One API call instead of ~50. Native audio understanding removes librosa entirely. |
| Intent parsing / titles | Gemini 2.0 Flash | **Gemini 2.5 Flash Lite** or **Groq Llama 3.3 70B** | <200 ms P50 vs ~1 s. Titles and intent are classification-shaped tasks. |
| Prompt caching | None | **Gemini implicit caching** (free) + explicit for system prompt | System prompt is ~2k tokens repeated across 30 chunks → ~75% cost cut. |
| Scene detection | PySceneDetect (Python, slow) | **ffmpeg `select='gt(scene,0.3)'`** filter | 10× faster, no Python deps. |
| Face detection | OpenCV Haar | **MediaPipe Face Detection** or **YOLOv8-face** | Haar fails on profile faces; MediaPipe is ~5 ms/frame on CPU. |
| Video storage | EC2 local disk | **S3 / Cloudflare R2** | EC2 disk fills. R2 = $0.015/GB/mo, no egress fees. Critical for going live. |
| Job queue | None (blocking invoke) | **arq** (async Redis queue) | Stateless workers, horizontal scale, retry/backoff built-in. |
| Transport | Blocking POST | **SSE** + **Redis pub/sub** | Already have `sse-starlette` in deps — wire it up. |
| DB | SQLite | **Postgres + JSONB + pgvector** | Moment map is nested JSON; JSONB indexes make modifications O(1); pgvector enables semantic search. |
| Clip cutting | `libx264` re-encode | **`-c copy`** with keyframe snap fallback | 20× faster when keyframe-aligned, which it is for most podcast/YT content. |
| FFmpeg execution | Subprocess in main process | **WASM (ffmpeg.wasm) on frontend** for simple cuts | User sees clip preview in <1 s, server only cuts for final export. |
| Frontend upload | Multipart to backend | **Presigned PUT to S3** + tus resumable protocol | Backend never sees raw video bytes. |
| Observability | None | **LangSmith** (already in env) + **OpenTelemetry** traces | Per-chunk spans show where time actually goes. |
| Hosting | EC2 t2.micro | **AWS ECS Fargate** (see §7) | Stateless, autoscale, no SSH-and-pray deploys. |

---

## 5. New pipeline architecture

```
                ┌────────────────────────────────────────────┐
                │  FRONTEND (Vercel or S3+CloudFront)         │
                │  • Chat + presigned S3 upload (tus)         │
                │  • SSE listener for live progress           │
                │  • ffmpeg.wasm for instant clip previews   │
                └────────────────┬───────────────────────────┘
                                 │ SSE
                ┌────────────────▼───────────────────────────┐
                │  API (FastAPI, ECS Fargate)                 │
                │  • Presigns upload                          │
                │  • Runs LangGraph coordinator               │
                │  • Streams events → SSE                     │
                └────────────────┬───────────────────────────┘
                                 │ arq enqueue
                                 │
                ┌────────────────▼───────────────────────────┐
                │  COORDINATOR GRAPH (LangGraph)              │
                │                                             │
                │   START                                      │
                │     │                                        │
                │     ▼                                        │
                │   chunk_planner  ← reads S3 metadata         │
                │     │                                        │
                │     ▼ Send API fan-out (30× in parallel)     │
                │   ┌──────────────────────────────────────┐   │
                │   │  chunk_subgraph (per 2-min window)   │   │
                │   │    ┌─ groq_transcribe                │   │
                │   │    ├─ gemini_multimodal_analysis    │   │
                │   │    └─ ffmpeg_signals (RMS peaks)    │   │
                │   │         ↓                            │   │
                │   │    merge_chunk → emits moments to    │   │
                │   │                  Redis stream         │   │
                │   └──────────────────────────────────────┘   │
                │     │ fan-in                                 │
                │     ▼                                        │
                │   global_fusion (dedupe overlaps)            │
                │     │                                        │
                │     ▼                                        │
                │   embed_moments (pgvector)                   │
                │     │                                        │
                │     ▼                                        │
                │   clip_selector (Gemini 2.5 Flash Lite)     │
                │     │                                        │
                │     ▼ Send API fan-out per clip              │
                │   ┌──────────────────────────────────────┐   │
                │   │  production_subgraph (per clip)       │   │
                │   │    ┌─ ffmpeg -c copy (cut)            │   │
                │   │    ├─ caption_gen (parallel)          │   │
                │   │    ├─ thumbnail_gen (parallel)        │   │
                │   │    └─ reframe (if portrait)            │   │
                │   │         ↓                              │   │
                │   │    upload_to_s3 → signed URL           │   │
                │   └──────────────────────────────────────┘   │
                │     │                                        │
                │     ▼                                        │
                │   END (all state persisted in Postgres       │
                │        via LangGraph checkpointer)            │
                └────────────────┬───────────────────────────┘
                                 │
                ┌────────────────▼──────────────────┐
                │  WORKERS (arq, ECS Fargate)        │
                │  Pre-warmed, horizontally scaled   │
                └───────────────────────────────────┘
```

**Key graph-level moves:**

- **Send API over *time chunks*** (not just modalities). This is the single biggest latency win.
- **Subgraphs emit incremental events** to Redis, so the SSE stream to the UI starts populating moments within seconds.
- **Postgres checkpointer** (LangGraph ships one) replaces `MemorySaver` — enables real resume-after-crash.
- **Per-clip production subgraph** also fans out — cutting 6 clips in parallel rather than sequentially.

---

## 6. Storage & embeddings

### What we're storing

| Data | Where | Why |
|---|---|---|
| Raw video chunks | **S3** | Workers pull a specific chunk without re-downloading the full video |
| Chunk analysis results (moments per chunk) | **Postgres JSONB** | Resume failed runs, replay modifications without re-calling Gemini |
| Active run state (LangGraph checkpoints) | **Postgres** via checkpointer | Pause/resume, multi-turn chat state |
| Hot data during a run | **Redis** | Fast pub/sub between workers and the SSE stream |
| Final clips | **S3** + signed URLs | CDN-friendly delivery via CloudFront |
| Moment embeddings | **Postgres pgvector** | Semantic search, cross-video library |

### Why embeddings earn their keep

Embeddings aren't needed for the base "analyze one video → produce clips" flow. They unlock three real features:

**1. Semantic moment search**
> User: "find me something about AI ethics"
- Embed query + each moment's transcript with `gemini-embedding-001` or `text-embedding-3-small`.
- Cosine search via pgvector extension — zero new infra.
- ~$0.00002 per moment.

**2. Cross-video library search**
> User has 50 podcasts, wants every mention of "Anthropic".
- Same embeddings, just search across `video_id`.
- Linear scan doesn't scale past ~10 videos.

**3. Smarter boundary deduplication**
- Chunks overlap by 10 s. A moment at chunk 5's end and chunk 6's start may be the same moment.
- Timestamp overlap catches 90%; embeddings catch the remaining 10% where timing shifts but content is identical.

**Do NOT add a dedicated vector DB (Pinecone/Weaviate/Qdrant).** pgvector in the same Postgres instance is sufficient up to millions of moments. Knowing when not to add a vector DB is the senior signal.

### Minimal embeddings delta

```
+ pgvector extension on RDS Postgres
+ one column: moments.embedding vector(1536)
+ one API call per moment: Gemini embedding at fusion time
+ one endpoint: POST /api/search { query } → embeds, cosine-searches
```

Total: ~150 lines of code, ~$0.01 per video.

---

## 7. AWS deployment architecture

```
                ┌─────────────────────────┐
                │  Route 53 (DNS)          │
                └──────────┬──────────────┘
                           │
                ┌──────────▼──────────────┐
                │  CloudFront (CDN)        │◄─── serves frontend + clip URLs
                └──────────┬──────────────┘
                           │
            ┌──────────────┼──────────────┐
            │              │              │
      ┌─────▼────┐   ┌─────▼────┐   ┌────▼──────┐
      │ S3       │   │ ALB      │   │ S3         │
      │ (React   │   │ (HTTPS)  │   │ (videos +  │
      │  build)  │   │          │   │  clips)    │
      └──────────┘   └────┬─────┘   └────────────┘
                          │
                  ┌───────▼────────┐
                  │ ECS Fargate     │
                  │ ┌─────────────┐ │
                  │ │ api service  │ │ ← FastAPI + LangGraph coordinator
                  │ │ (2 tasks)    │ │
                  │ └─────────────┘ │
                  │ ┌─────────────┐ │
                  │ │ worker svc   │ │ ← arq workers, autoscales 1→20
                  │ │ (N tasks)    │ │
                  │ └─────────────┘ │
                  └──┬──────────┬───┘
                     │          │
            ┌────────▼──┐  ┌───▼─────────┐
            │ RDS       │  │ ElastiCache │
            │ Postgres  │  │ Redis       │
            │ +pgvector │  │             │
            └───────────┘  └─────────────┘

  Secrets Manager → API keys   CloudWatch → logs + metrics
```

### Service mapping

| v1 (EC2 t2.micro) | v2 AWS |
|---|---|
| Video files on local disk | **S3** with presigned uploads |
| SQLite on disk | **RDS Postgres** (`db.t4g.micro`, ~$12/mo) |
| Nothing (in-memory cache) | **ElastiCache Redis** (`cache.t4g.micro`, ~$12/mo) |
| `.env` file | **Secrets Manager** ($0.40/secret/mo) |
| Manual `docker compose up` | **ECS Fargate** with service definitions |
| SSH + `docker logs` | **CloudWatch Logs** + **CloudWatch Metrics** |
| Hardcoded EC2 IP | **ALB** + **Route 53** + **ACM** (free cert) |
| GitHub Actions SSH deploy | **GitHub Actions → ECR push → ECS deploy** |

### Why ECS Fargate over plain EC2

v1's DEPLOY.md uses one EC2 with Docker Compose. That's fine for a demo but it's a *single box*. Fargate gives you:
- Stateless containers (die and respawn, no state loss)
- Easy horizontal scaling (`desired_count: 20`)
- No SSH-and-pray deploys
- No host OS management

**Skip EKS (Kubernetes on AWS).** Overkill and a distraction.

### Cost at idle vs live

| Scenario | Monthly |
|---|---|
| v1 (t2.micro, free tier) | $0 for 12 months, then ~$10 |
| v2 idle (2 API tasks + 1 worker, min-sized) | ~$45–60 |
| v2 with light traffic (~50 videos/day) | ~$80–120 |
| v2 under load (workers scaled to 20) | ~$200+ when scaled |

For pure portfolio use: keep v1's single-EC2 setup and just upgrade the *code* to v2. The architecture looks identical from outside; deploy differently later.

### Learning path (each step ~half a day)

1. **IAM + CLI basics** — roles, policies, `aws configure`, least-privilege mental model.
2. **S3 + presigned URLs** — upload from a test script, stream back. Fixes a v1 design flaw.
3. **RDS Postgres** — create instance, connect from local psql, connect from FastAPI. Migrate SQLite data.
4. **ECR + Docker** — push backend image to ECR. Private Docker Hub.
5. **ECS Fargate** — one service running the API task, fronted by ALB. Console first, then Terraform/CDK.
6. **ElastiCache Redis + arq worker service** — second ECS service that pulls jobs. Two tiers now.
7. **Secrets Manager + task role** — stop passing env vars, inject secrets via task role.
8. **CloudWatch alarms + CI/CD** — `gh actions → ecr push → ecs update-service`.
9. **Terraform** (optional, strong signal) — codify everything. Destroyable, reproducible infra.

Steps 1–4 can happen while still on v1. Steps 5–9 are the v2 migration.

---

## 8. Implementation phases

### Phase 0 — Stop the bleeding (half a day)
- Rotate the three leaked API keys; add `.env` to `.gitignore`.
- Move `GEMINI_MODEL` to `config.py`.
- Turn on LangSmith tracing (already in env, zero code change).
- Drop `psycopg2-binary` or actually move to Postgres.

### Phase 1 — Swap the slow pieces (2–3 days)
- Replace AssemblyAI with Groq Whisper Turbo (`services/transcription.py` is ~40 lines).
- Replace the 3 analysis agents with one Gemini 2.5 Flash call that takes the raw chunk + returns structured `Moment[]`. Keep lightweight ffmpeg RMS peak detection.
- Switch clip cutting to `-c copy` with keyframe-snap fallback.
- **Expected gain: 5–10× latency on a 60-min video, no architectural changes yet.**

### Phase 2 — Chunking + fan-out (3–5 days)
- Implement `chunk_planner` that splits by time (2 min, 10 s overlap).
- Restructure graph: outer coordinator + per-chunk subgraph dispatched via Send API.
- Wire Postgres checkpointer so chunks are resumable.
- Add `global_fusion` node that dedupes moments in overlap regions.

### Phase 2.5 — Embeddings (1 day)
- pgvector extension on Postgres.
- Embed each moment at fusion time.
- `/api/search` endpoint for semantic moment search.

### Phase 3 — Streaming UX (2–3 days)
- SSE endpoint that pipes Redis pub/sub events to the frontend.
- Frontend: skeleton clip cards that fill in as moments arrive.
- `ffmpeg.wasm` on frontend for instant preview before server finishes production.

### Phase 4 — Storage + workers (2–3 days)
- S3 bucket, presigned upload, backend never touches raw bytes.
- arq workers deployed as separate ECS Fargate services; autoscale policy.
- Pre-warm: lazy singletons for Gemini/Groq clients in worker startup hook.

### Phase 5 — Credibility layer (2 days, punches above its weight for portfolio)
- Eval harness: 5–10 videos with human-labeled "good moments", nightly CI run that prints precision@k and mean convergence score.
- OTel traces exported to Honeycomb/Tempo — screenshots in README.
- Prompt caching metrics: log cache hit rate per Gemini call.

### Phase 6 — Go-live readiness (only when you're sure)
- Auth (Clerk or Supabase Auth — ~1 day drop-in).
- Per-user quotas in Redis.
- Stripe metered billing keyed to minutes-processed.
- Abuse guards: max video length, rate limits, content policy call before analysis.

---

## 9. LangGraph recruiter pitch

v2 uses LangGraph *properly* — the differentiator vs every other "built with LangGraph" resume.

**30-second interview pitch:**

> "I built a real-time video clipping pipeline with LangGraph. The main graph fans out time-chunked analysis across parallel subgraphs using the Send API — a 60-minute video splits into 30 two-minute chunks that run concurrently. Each chunk subgraph does its own Groq transcription and Gemini multimodal analysis, then the results fan back in through a fusion node that dedupes moments across chunk boundaries. State is checkpointed to Postgres, so runs are resumable. End-to-end a one-hour podcast becomes 6 viral clips in under a minute."

**Specific LangGraph primitives worth naming:**

| Feature | What we used it for | Why it's a flex |
|---|---|---|
| **Send API** | Parallel fan-out over time chunks | Most demos are linear — using Send for true parallelism signals depth |
| **Compiled subgraphs** | `chunk_subgraph` and `production_subgraph` as reusable nodes | Composability, not one flat graph |
| **Conditional edges** | Skip visual agent for podcasts, route modify-vs-regenerate intents | Real routing, not toy if/else |
| **Postgres checkpointer** | Resume failed runs + multi-turn chat state | Production concern 90% of demos skip |
| **Annotated state reducers** (`operator.add`) | Safe concurrent writes from parallel chunks | Pairs with Send API |
| **ToolNode + structured output** | FFmpeg ops + Pydantic-typed Gemini responses | Type safety for LLM output |

**Always pair with a number:** "Parallel fan-out took the pipeline from 15 min to 45 s on a 60-min video, measured across 30 workers."

**AWS talking points:**
- "Stateless workers on **Fargate**, horizontal autoscale keyed to queue depth."
- "Media on **S3** with **CloudFront** for CDN'd clip delivery, presigned PUTs so the backend never handles raw bytes."
- "Postgres on **RDS** with the LangGraph checkpointer + pgvector for semantic moment search, **ElastiCache** Redis for the arq queue and SSE fan-out."
- "CI via **GitHub Actions → ECR → ECS rolling deploy**, secrets through **Secrets Manager** with task-role IAM."
- "Observability in **CloudWatch** + LangSmith for LLM-level traces."

**What NOT to overclaim:** LangGraph is hot now but the field rotates fast. Pair it with fundamentals — async Python, distributed systems, observability — so you're not a one-framework candidate.

---

## 10. Success criteria

Measurable, in a dashboard:

- P50 end-to-end latency for 60-min video < 90 s
- P95 end-to-end latency for 60-min video < 180 s
- Cache hit rate on repeat modifications > 95%
- Gemini prompt cache hit rate > 60% across chunks in a single run
- Zero-data-loss on worker crash (checkpointer resume test in CI)
- Precision@6 on eval set > 0.7 (6 clips returned, ≥4 rated "viral" by human labelers)

If v2 hits these, it's both an advanced personal project *and* a viable live product.
