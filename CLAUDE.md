# AutoClip AI — notes for Claude

Read this first. It's the handoff between sessions: what the project is,
the rules the owner set, where the work stands, and what to do next.

## What this is

Conversational video clipping: upload a long video, chat ("4 funny 30s
clips, 9:16"), a LangGraph deep agent finds moments and renders captioned,
reframed clips. FastAPI + LangGraph/`deepagents` + LlamaIndex/pgvector +
Redis + React/Vite/Tailwind/react-three-fiber, Docker Compose, deployed on
one EC2 box. See README.md (architecture, API, env vars), DEPLOY.md,
EVALUATION.md, BENCHMARKS.md.

## Owner's rules (don't re-litigate)

- **Portfolio project, nothing more.** Keep scope small; build the bare
  minimum first.
- **Limits: 300 MB / 60 min per upload, for everyone** (admins too, via
  `VIDEO_MINUTES_CAP_ADMINS=1`). Audio uploads (mp3/m4a/wav/aac/ogg/flac)
  are supported and become audiograms. No 3-hour support, no email
  verification, no extra admin features.
- **Google sign-in is WANTED** (replaces the old "no OAuth" rule). Plan:
  free hostname `15-206-112-113.sslip.io` (Let's Encrypt cert via the
  existing acme.sh), authlib code flow + PKCE, `google_sub` column, issue
  the existing session cookie. **Not built yet — do it together with the
  owner**, who creates the OAuth client in Google Cloud (redirect
  `https://15-206-112-113.sslip.io/api/auth/google/callback`, scopes
  `openid email profile`). Fallback hostname: a free `autoclip.is-a.dev`.
  Email/password and the demo stay.
- **OpenRouter for every model call.** No Groq/Whisper/other providers.
- **Spend nothing without asking:** no domain, no disk resize, no new paid
  services. Paid OpenRouter runs only above a $10 balance, with
  `--budget-usd`. Unit tests mock every LLM call.
- **Landing page:** keep the existing motion (3D FilmScene scroll) and fonts
  (Plus Jakarta Sans + Inter). Palette is now 2+1: obsidian black, platinum,
  gold as the accent only.
- **Never push or merge to `master` without explicit approval** — a push to
  `master` auto-deploys to production (`.github/workflows/deploy.yml`).
  Work on branch `portfolio-overhaul`. Don't touch the prod server, AWS
  resources or GitHub settings without the owner.
- No `Co-Authored-By: Claude` trailers in commits, no Claude footer in PRs.
- **Wild Target (copyrighted film) is eval-only.** Never commit its footage,
  transcript or dialogue quotes; never show it publicly. `reports/` is
  gitignored for that reason. The public demo/landing uses the CC BY Doctorow
  talk.
- The owner likes work split across parallel Opus sub-agents with strict
  file ownership, then integrated and reviewed by the main session.

## Status (as of 2026-11-12)

Plan: `~/.claude/plans/calm-hatching-church.md` (podcast pivot, real site,
live with users). Everything below is on `portfolio-overhaul`, **not pushed,
not live** — production still runs the old code.

**Done on the branch:**

- **Phase 0–1 (`a26730c`, `fed747c`):** moment selection (hybrid candidates
  → LLM re-rank → diversity filter, category tags, migration 0003); podcast
  pivot — audio → audiogram mp4 (`services/audiogram.py`, `media_kind`,
  migration 0004), transcript-only chunks for audio, static-shot check (4
  frames instead of 24), credits detection only ≥ 70 min, 60-min cap for all.
- **Phase 2 (`5a45ee0`):** podcast ground truth
  (`backend/eval/podcasts/blocks_russell_peters.json`, CC BY), RAGAS step
  (`--ragas`, dev-only extra). The paid podcast matrix ran on 2026-11-10
  (EVALUATION.md §5).
- **Phase 3 (`dca6959`):** chat history — `conversations`/`messages`
  (migration 0005), `/api/conversations` CRUD, turns stored by
  `/api/chat/message` with `conversation_id`, thread `u:{uid}:c:{cid}`,
  ownership checked in routes and agent tools, demo read-only.
- **Phase 4 + 7 (frontend commits `60271c3`…`8900040`):** shared header,
  `/docs`, `/settings`, Library retention dates, Studio sidebar, audio
  dropzone, 2+1 palette + Apple tokens, landing copy for podcasts.
  `frontend/API_CONTRACT.md` is the frontend↔backend contract.
- **Phase 5 (`43ca488`):** 3 active uploads + 1.5 GB per user, 5 GB global
  disk guard (507), nightly retention (source 7 d → archived, clips 30 d,
  inactive accounts 60 d; admin + demo exempt) in the `main.py` lifespan
  with a Redis lock, migration 0006, `GET /api/me/usage`, `DELETE /api/me`.
- **Phase 8 code (`7167e79`):** one-at-a-time analysis queue with
  `queue_position` ("#N in line"), `DAILY_ANALYSIS_MINUTES_LIMIT`,
  `/api/health/ready` (deploy smoke test uses it),
  `backend/scripts/backup_db.sh` (pg_dump → S3, documented, not set up).
- **Clip titles (`d0bc780`):** cut at a word boundary, prompt asks for ≤ 7
  words (old clips keep their cut titles).
- **Talk segments (`692f5bc`):** podcasts/talks are stored as 30–90 s
  transcript segments instead of 3–17 s vision fragments
  (`services/talk_segments.py`, `SEGMENT_MODE=auto|moments|segments`,
  default `auto`: audio, or video with ≥ 60% static chunks). Lite-model
  segmentation per ~10 min with a pause-based fallback, payoff sentence per
  segment (migration **0007** `moments.payoff`), strict tags (≤ 2, no tag
  on > 25% of segments), re-rank on the whole segment, clip windows snapped
  to sentences. `scripts/resegment.py` rebuilds a video's moments from its
  stored transcript without re-analysis. **Not yet measured end to end** —
  see Eval results.
- Backend tests: 141 passing (`backend/tests/`, run inside the backend image).

**Eval results so far** (reports in `reports/eval/<slug>/<run>/report.md`,
local only): selection fix with Gemini 2.5 Flash — Wild Target hit@3 2/6,
tag precision 0.33; Doctorow hit@3 2/6, tag precision 0.62, 0 duplicates;
transcript coverage 0.96. RAGAS (free judge) faithfulness 0.81 / 0.69.
Podcast matrix (2026-11-10, Blocks episode, vision moments): hit@3 audio
1/6, video static 3/6, full vision 2/6; recall@all 0.82–0.95. The exit bar
was not met (audio only 28% cheaper, not 60%). The diagnosis: stored moments
were 3–17 s fragments of 30–90 s stories, and tags were inflated
(`insightful` on 42–86%). The talk-segments fix is the answer to that. It was
only dry-run on a free model ($0, balance $4.18): units 8 s → 55 s, labelled
moments fully inside one unit 0.00 → 0.53–0.68, max tag share ≤ 0.25. But on
Doctorow the LLM boundaries lose to a fixed 60 s grid (0.56 vs 0.65), and
**hit@3 is unmeasured**. Details in EVALUATION.md. Known weak spot: ranking
for a specific ask. Be honest about it on the landing page, and the owner
does not want podcast numbers on the landing page.

## Next steps (in order)

1. **Frontend:** show `queue_position` ("#N in line") from the analysis
   state/SSE (contract appended in `frontend/API_CONTRACT.md`); the backend
   already sends it and puts it in the reply text.
2. **Paid re-eval of talk segments** once the OpenRouter balance is above
   $10 (~$0.25): rebuild the backend image (0007 applies), then
   `scripts/resegment.py` for `cd0d82336186`, `6ac4b72bc523` and
   `c2b0ab7cda68`, then the 6 `eval_movie.py --video-id … --budget-usd 0.5`
   runs per video (EVALUATION.md §5, "Still to run"). Update
   `results.json` → `podcast_matrix`, EVALUATION.md and BENCHMARKS.md. If
   hit@3 doesn't improve, consider `SEGMENT_MODE=moments` as the default for
   video, or fixed overlapping windows: the dry run says a fixed grid is a
   strong boundary baseline.
3. **Google sign-in (Phase 6) with the owner:** sslip.io cert + nginx
   `server_name`, OAuth client, authlib flow, migration **0008**
   `google_sub` (0007 is now `moments.payoff`), `google_linked` on `/api/auth/me`
   (currently always `false`), mocked callback test.
4. **Ops the owner must do (AWS, not code):** S3 bucket + instance-role
   `s3:PutObject` + host cron for `backup_db.sh` (DEPLOY.md §6); a spend
   limit on the OpenRouter key; UptimeRobot on `/api/health/ready`.
5. Frontend healthcheck in compose + autoheal; deploy rollback.
6. Go live **only when the owner says so**: DEPLOY.md §9 (pg_dump first;
   migrations 0003–0007 apply on deploy; `ADMIN_EMAILS`; sign up the admin
   immediately; seed the demo with Doctorow). **Doctorow is 61.2 min**, over
   the 60-min cap: upload it with `VIDEO_MINUTES_CAP_ADMINS=0` set
   temporarily (then back to `1`), or trim it under 60 min. Then merge to
   `master`.
7. Portfolio polish: README GIF, 2-min walkthrough.

## Local environment

- Stack: `docker compose up -d` (no prod overlay locally) → http://localhost
  (nginx) and http://127.0.0.1:8000 (backend). Rebuild after backend dep
  changes: `docker compose build backend frontend`.
- Local admin: `admin@autoclip.dev`; credentials are in the local `.env`
  (`EVAL_EMAIL` / `EVAL_PASSWORD`, gitignored). Admins skip quotas, the
  storage quota and retention.
- Tests: mount the source into the backend image (ffmpeg is only there):
  `docker run --rm -v "$PWD/backend:/w" -w /w --entrypoint sh autoclip-ai-backend -c "pip install -q --target /tmp/pt pytest && PYTHONPATH=/tmp/pt:/w/src python -m pytest tests -q -p no:cacheprovider"`
- Analysed videos in the local DB: Wild Target `6d3872df73b1` (new
  pipeline), `4cf75b3d8e2a` (old pipeline); Doctorow `c2b0ab7cda68`.
  Podcast uploads (analysed in the 2026-11-10 matrix, still the old vision
  moments): `6ac4b72bc523` (video), `cd0d82336186` (audio). Local DB is at
  migration 0007.
- Source files (not in git): `~/Videos/autoclip-bench/wildtarget.mp4`,
  `~/Videos/autoclip-bench/doctorow_39c3.mp4`.
- DB backup before the auth migration: `~/autoclip-backups/`.
- Run an eval:
  `set -a; source .env; set +a; python3 backend/scripts/eval_movie.py --gt backend/eval/movies/doctorow_39c3.json --base http://localhost --video-id c2b0ab7cda68 --budget-usd 1`
- ffmpeg isn't on the host — use `docker exec autoclip-ai-backend-1 ffmpeg …`
  or a `docker run --rm` of the backend image.
- The host has an `rtk` hook that filters some command output; use
  `rtk proxy curl …` when you need raw JSON from curl.
- OpenRouter key is shared with other projects; check
  `https://openrouter.ai/api/v1/credits` before spending (~$41 left on
  2026-10-10).

## Production (live, still the OLD code)

https://15.206.112.113 — EC2 t3a.small, ap-south-1, app at `/opt/autoclip`,
port 22 closed (manage via SSM), always run compose with
`-f docker-compose.yml -f docker-compose.prod.yml`. Details in DEPLOY.md.
