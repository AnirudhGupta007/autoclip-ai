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

- **Portfolio project, nothing more.** Keep scope small. Keep current limits
  (500MB upload, ~110-min analysis cap, 60-min cap for non-admin users).
  No email verification, OAuth, 3-hour support or extra admin features.
- **OpenRouter for every model call.** No Groq/Whisper/other providers.
- **Landing page:** keep the existing motion (3D FilmScene scroll), colours
  (pure black + gold) and fonts (Plus Jakarta Sans + Inter). Improve/add
  only, never restyle.
- **Never push or merge to `master` without explicit approval** — a push to
  `master` auto-deploys to production (`.github/workflows/deploy.yml`).
  Work on branch `portfolio-overhaul`.
- No `Co-Authored-By: Claude` trailers in commits, no Claude footer in PRs.
- **Wild Target (copyrighted film) is eval-only.** Never commit its footage,
  transcript or dialogue quotes; never show it publicly. `reports/` is
  gitignored for that reason. The public demo/landing uses the CC BY Doctorow
  talk.
- The owner likes work split across parallel Opus sub-agents with strict
  file ownership, then integrated and reviewed by the main session.

## Status (as of 2026-10-10)

**Committed** — `852920d` on `portfolio-overhaul` (not pushed, not live):
pipeline fixes (transcription 3%→96% coverage, full-chunk frame sampling,
bounded memory, background analysis + SSE, exact clip lengths, letterbox
crop, captions, credits excluded), login + per-user isolation (argon2
sessions, ownership in routes *and* agent tools, X-Accel-Redirect media,
demo account, Alembic 0001–0002, 47 tests), eval harness
(`backend/scripts/eval_movie.py`, `evallib/`), ground truth for two videos,
landing-page portfolio sections, docs.

**Uncommitted in the working tree** — moment-selection fix (a sub-agent was
cut off by a usage limit before testing/committing):
`rag/selection.py` (hybrid candidates → LLM re-rank → diversity filter),
`services/moment_tagger.py` + `scripts/backfill_moment_tags.py` (category
tags on moments), `alembic/versions/0003_moment_categories.py`, credits
skipped during analysis, eval caption-check fix in `evallib/probe.py`,
`tests/test_selection.py`, plus edits in tools/orchestrator/clip_selector/
chat router/config. Eval runs with it already happened (below), but its
tests were never run and the code hasn't been reviewed.

**Eval results** (reports in `reports/eval/<slug>/<run>/report.md`, local only):

| | Baseline (old app) | After pipeline fix | + selection fix (Gemini 2.5 Flash) |
|---|---|---|---|
| Wild Target hit@3 | 0/6 | 1/6 | **2/6** |
| Wild Target tag precision | 0.11 | 0.22 | **0.33** |
| Wild Target transcript coverage | 0.03 | 0.96 | 0.96 |
| Wild Target moment recall@all | 0.37 | 0.83 | 0.83 |
| Doctorow hit@3 | – | 0/6 | **2/6** |
| Doctorow tag precision | – | 0.14 | **0.62** |
| Doctorow duplicate clips | – | 0.14 | **0.00** |

Full analysis of a 98-min film: ~$0.59, ~20 min. The selection-fix runs
re-used analysed videos, so their cost/time (~$0.03, ~4 min for 6 queries)
are not comparable to full runs.

**Model A/B (Wild Target):** `typesafe/jev-router` (a model router on
OpenRouter) lost to `google/gemini-2.5-flash` as orchestrator + re-ranker:
hit@3 0/6 vs 2/6, ~3× cost ($0.099 vs $0.034), slower (406s vs 236s). Its
Doctorow arm was never run. Defaults stay on Gemini 2.5 Flash.

## Next steps (in order)

1. Review the uncommitted selection-fix code, run `backend/tests/` (incl.
   `test_selection.py`, `test_auth_isolation.py`, `test_evallib.py`), fix,
   commit on `portfolio-overhaul`.
2. Put final numbers into `frontend/src/data/results.json` (`current`, same
   keys as `baseline`, plus a note naming the model) and a "selection fix +
   model A/B" section in EVALUATION.md / BENCHMARKS.md. Commit.
3. Health/monitoring: deep `/api/health/ready` (DB, Redis, disk, ffmpeg,
   OpenRouter key/balance), frontend healthcheck + autoheal, UptimeRobot,
   daily canary workflow (tiny CC clip on the live site), deploy smoke test
   on `/ready` + rollback.
4. Go live **only when the owner says so**: follow DEPLOY.md §7 (pg_dump,
   `alembic stamp 0001`, `ADMIN_EMAILS`, sign up the admin immediately,
   seed the demo with the Doctorow video), then merge to `master`.
5. Portfolio polish: README GIF, 2-min walkthrough.
6. Optional: frames vs native-video vision A/B (`VISION_INPUT_MODE`).

Known weak spot: hit@3 is 2/6 per video — moments are found (recall 83–91%)
but ranking for a specific ask is still modest. Be honest about it on the
landing page.

## Local environment

- Stack: `docker compose up -d` (no prod overlay locally) → http://localhost
  (nginx) and http://127.0.0.1:8000 (backend). Rebuild after backend dep
  changes: `docker compose build backend frontend`.
- Local admin: `admin@autoclip.dev`; credentials are in the local `.env`
  (`EVAL_EMAIL` / `EVAL_PASSWORD`, gitignored). Admins skip quotas.
- Analysed videos in the local DB: Wild Target `6d3872df73b1` (new
  pipeline), `4cf75b3d8e2a` (old pipeline); Doctorow `c2b0ab7cda68`.
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
