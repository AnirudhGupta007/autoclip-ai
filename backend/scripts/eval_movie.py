"""Video-level evaluation of AutoClip (films, talks, podcasts) against human ground truth.

Sends each ground-truth query to the running app as a chat message (or
re-scores a previous run offline), then measures what came back against a
human-labelled moment map of the video (backend/eval/movies/, backend/eval/podcasts/):

  * query quality   — hit@1 / hit@3 / MRR vs the human's ranked top-3,
                      tag precision (is a "funny" clip actually funny?)
  * analysis        — moment recall/precision@k, recall per tenth of the video,
                      within-chunk position histogram, transcript coverage,
                      how far into the video analysis reached, credits leaks
  * delivery        — length / aspect adherence, duplicates, captions,
                      letterbox bars (ffprobe/ffmpeg, via docker exec if needed)
  * cost & time     — OpenRouter credits delta, wall time per query
  * --ragas         — optional RAGAS faithfulness + context precision with a
                      cheap judge model (evallib/ragas_eval.py; dev extra)

Examples (from the repo root):

  # score an existing run, no API calls
  python backend/scripts/eval_movie.py --gt backend/eval/movies/wild_target.json \\
      --from-results backend/eval/movies/wild_target_baseline/report.json

  # live run against the local stack (needs DAILY_QUERY_LIMIT raised)
  python backend/scripts/eval_movie.py --gt backend/eval/movies/wild_target.json \\
      --base http://127.0.0.1:8000 --video-id 4cf75b3d8e2a \\
      --baseline backend/eval/movies/wild_target_baseline/report.json

Exit codes: 0 ok · 1 error · 2 regression vs --baseline · 3 quota/budget stopped the run.
Stdlib only — runs with the system python3, no venv needed.
"""
from __future__ import annotations

import argparse
import os
import datetime as dt
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from evallib import client as C  # noqa: E402
from evallib import probe as P  # noqa: E402
from evallib import report as R  # noqa: E402
from evallib import score as S  # noqa: E402
from evallib.runs import load_gt, load_results_dir  # noqa: E402
from evallib import ragas_eval as RG  # noqa: E402

REPO = Path(__file__).resolve().parents[2]


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def git_sha() -> str | None:
    try:
        r = subprocess.run(["git", "-C", str(REPO), "rev-parse", "--short", "HEAD"],
                           capture_output=True, text=True, timeout=10)
        if r.returncode == 0:
            dirty = subprocess.run(["git", "-C", str(REPO), "status", "--porcelain", "--untracked-files=no"],
                                   capture_output=True, text=True, timeout=10).stdout.strip()
            return r.stdout.strip() + ("+dirty" if dirty else "")
    except OSError:
        pass
    return None


# ------------------------------------------------------------------------- live
def _clip_rec(c: dict, qid: str, run_no: int) -> dict:
    start = c.get("start_time", c.get("start"))
    end = c.get("end_time", c.get("end"))
    return {"id": c["id"], "title": c.get("title"), "start": float(start), "end": float(end),
            "file_path": c.get("file_path") or (c.get("file_url") or "").lstrip("/") or None,
            "frame": c.get("frame"), "query_id": qid, "run": run_no, "returned_to_user": True,
            "delivered_len_s": None, "delivered_res": None}


def run_live(args, gt: dict, queries: list[dict]) -> tuple[dict, int]:
    api = C.AutoClip(args.base, log=log, email=args.email, password=args.password)
    if not api.health():
        raise SystemExit(f"backend not reachable at {args.base}")
    credits = C.Credits(C.read_env_key(REPO / ".env"))
    if credits.usage() is None:
        log("! OpenRouter credits endpoint unavailable — cost will be reported as unknown")

    if args.upload:
        t = time.time()
        v = api.upload(Path(args.upload))
        video_id = v["id"]
        log(f"uploaded {args.upload} → video {video_id} ({time.time() - t:.0f}s)")
    else:
        video_id = args.video_id
        if not api.video(video_id):
            raise SystemExit(f"video {video_id} not found at {args.base}")

    if args.fresh:
        res = C.reset_video_clips(video_id)
        if res is None:
            raise SystemExit("--fresh: could not reset clips/chat threads (local docker stack only)")
        log(f"--fresh: cleared clips + chat threads for {video_id} ({res})")

    need = len(queries) * args.runs
    q = api.quota()
    if q and q.get("remaining") is not None and q["remaining"] < need:
        log(f"! quota: {q['remaining']} chat turns left today (DAILY_QUERY_LIMIT={q.get('limit')}), "
            f"this eval needs {need} (+1 per query if analysis runs in the background). "
            f"Raise DAILY_QUERY_LIMIT in .env and `docker compose up -d backend`.")

    u0 = credits.usage()
    clips: dict[str, dict] = {}
    runs = []
    seen: set[str] = set()
    exit_code = 0
    stop_reason = None
    for run_no in range(1, args.runs + 1):
        recs = []
        for qd in queries:
            rec = {"query_id": qd["id"], "message": qd["message"], "status": None, "elapsed_s": None,
                   "cost_usd": None, "agent_text": None, "clip_ids": [], "returned_ids": [],
                   "analysis_waited_s": None, "error": None, "turns": 0, "conversation_id": None}
            recs.append(rec)
            if stop_reason:
                rec["error"] = f"skipped: {stop_reason}"
                continue
            spent = (credits.usage() - u0) if (u0 is not None and args.budget_usd) else None
            if spent is not None and spent >= args.budget_usd:
                stop_reason = f"budget ${args.budget_usd:.2f} reached (spent ${spent:.3f})"
                rec["error"] = f"skipped: {stop_reason}"
                exit_code = 3
                continue
            known = {c["id"] for c in api.clips(video_id)} | seen
            c0 = credits.usage()
            t0 = time.time()
            log(f"[run {run_no}] {qd['id']}: {qd['message']!r}")
            try:
                # One conversation per query (thread u:{uid}:c:{cid}): the same
                # path the Studio uses, and each query starts with no history.
                cid = api.create_conversation(video_id) if args.conversations else None
                rec["conversation_id"] = cid
                _, _, resp = api.chat(video_id, qd["message"], conversation_id=cid)
                rec["turns"] = 1
                if C.looks_like_analysis_started(resp):
                    log("  analysis running in the background — polling /api/chat/analysis …")
                    tw = time.time()
                    api.wait_for_analysis(video_id, timeout_s=args.analysis_timeout)
                    rec["analysis_waited_s"] = round(time.time() - tw, 1)
                    _, _, resp = api.chat(video_id, qd["message"], conversation_id=cid)
                    rec["turns"] = 2
                rec["status"] = 200
            except C.QuotaExceeded as e:
                log(f"\n✗ {e}\n")
                rec["error"] = "HTTP 429 quota"
                stop_reason = "daily chat quota exhausted (raise DAILY_QUERY_LIMIT)"
                exit_code = 3
                continue
            except (C.ApiError, OSError) as e:
                rec["error"] = str(e)[:300]
                log(f"  ✗ {e}")
                continue
            rec["elapsed_s"] = round(time.time() - t0, 1)
            rec["agent_text"] = resp.get("response")
            payload = resp.get("clips") or []
            rec["returned_ids"] = [c.get("id") for c in payload if c.get("id")]
            new = [c for c in payload if c.get("id") and c["id"] not in known]
            if not payload:  # API didn't echo clips: diff the clip list instead
                new = [c for c in api.clips(video_id) if c["id"] not in known]
                rec["returned_ids"] = [c["id"] for c in new]
            for c in new:
                clips[c["id"]] = _clip_rec(c, qd["id"], run_no)
            rec["clip_ids"] = [c["id"] for c in new]
            seen.update(rec["returned_ids"])
            seen.update(rec["clip_ids"])
            time.sleep(2)  # credits endpoint lags
            c1 = credits.usage()
            rec["cost_usd"] = max(0.0, c1 - c0) if (c0 is not None and c1 is not None) else None
            log(f"  → {len(new)} new clip(s), {len(rec['returned_ids'])} in response, "
                f"{rec['elapsed_s']}s, ${rec['cost_usd'] or 0:.4f}")
        runs.append({"run": run_no, "queries": recs})

    if args.conversations:
        stored = {}
        for r in runs:
            for rec in r["queries"]:
                cid = rec.get("conversation_id")
                if cid:
                    msgs = api.conversation_messages(cid)
                    stored[cid] = None if msgs is None else len(msgs)
                    rec["stored_messages"] = stored[cid]
        # one user message + one reply per turn: the backend does not store the
        # automatic re-send after "analysis started" as a second user message
        expected = {rec["conversation_id"]: 1 + rec["turns"] for r in runs for rec in r["queries"]
                    if rec.get("conversation_id")}
        ok = all((stored.get(c) or 0) >= n for c, n in expected.items())
        log(f"conversations: {len(stored)} created, stored messages {sorted(stored.values(), key=str)} "
            f"({'all turns persisted' if ok else 'MISSING turns'})")

    time.sleep(8)
    u1 = credits.usage()
    total = (u1 - u0) if (u0 is not None and u1 is not None) else None
    if total is not None and total < 0:  # credits endpoint is eventually consistent
        total = 0.0
    run = {"video_id": video_id, "mode": "live", "source": args.base, "runs": runs, "clips": clips,
           "moments": None, "raw_chunk_moments": None, "chunks": None, "transcript": None,
           "cost": {"total_usd": total,
                    "note": "OpenRouter usage delta of the app's API key across the whole eval (includes any analysis "
                            "it triggered); anything else using the same key during the run is counted too.",
                    "counter": credits.source},
           "analysis_s": None, "stop_reason": stop_reason}
    return run, exit_code


# ------------------------------------------------------------------------ enrich
def enrich(run: dict, args) -> None:
    vid = run.get("video_id")
    if args.offline or not vid:
        return
    if not run.get("moments"):
        ms = C.AutoClip(args.base, email=args.email, password=args.password).moments_endpoint(vid) if args.base else None
        src = "api"
        if ms is None:
            ms, src = C.moments_from_postgres(vid), "postgres"
        if ms:
            run["moments"] = [{k: m.get(k) for k in ("start", "end", "convergence_score", "style_tags")}
                              | {"description": (m.get("description") or "")[:160]} for m in ms]
            log(f"moments: {len(ms)} from {src}")
    t = run.get("transcript") or {}
    if t.get("word_starts") is None:
        tr = C.transcript_from_container(vid)
        if tr:
            run["transcript"] = tr
            log(f"transcript: {len(tr['word_starts'])} word timings from the backend container")


def probe_all(run: dict, args) -> dict:
    probes = dict(run.get("probes") or {})
    if args.no_probe:
        return probes
    todo = [c for c in run["clips"].values() if c.get("file_path") and (args.reprobe or c["id"] not in probes)]
    if not todo:
        return probes
    try:
        runner = P.Runner.auto(local_root=Path(args.outputs_root) if args.outputs_root else None)
    except RuntimeError as e:
        log(f"! probing disabled: {e}")
        return probes
    log(f"probing {len(todo)} clip(s) via {'docker exec ' + runner.container if runner.container else 'local ffmpeg'} …")
    for c in todo:
        pr = P.probe_clip(runner, P.resolve_clip_path(runner, c["file_path"]), deep=not args.shallow_probe)
        probes[c["id"]] = pr.as_dict()
    return probes


# ------------------------------------------------------------------------ main
def build_report(gt: dict, run: dict, probes: dict, args, mode: str) -> dict:
    run_scores = []
    for r in run["runs"]:
        sc = S.score_run(gt, run, r["queries"], probes)
        sc["run"] = r["run"]
        run_scores.append(sc)
    analysis = S.score_analysis(gt, run)
    head = S.headline(run_scores, analysis, run)
    agg = S.aggregate(run_scores)
    extra = {k: v["mean"] for k, v in agg.items()}

    moments = gt["moments"]
    unreq = []
    for cid in run.get("unrequested_clip_ids") or []:
        c = run["clips"].get(cid)
        if c:
            hm = S._best_moment((c["start"], c["end"]), moments)
            unreq.append({"clip_id": cid, "start": c["start"], "end": c["end"], "title": c.get("title"),
                          "human_moment": hm["id"] if hm else None})

    stored_run = json.loads(json.dumps(run))
    stored_run["probes"] = probes
    return {
        "schema": "autoclip-eval-movie/1",
        "meta": {"generated_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                 "mode": mode, "video_id": run.get("video_id"), "runs": len(run["runs"]), "git": git_sha(),
                 "gt_path": str(args.gt), "source": run.get("source"), "stop_reason": run.get("stop_reason")},
        "gt": {"slug": gt["slug"], "title": gt["title"], "license_note": gt["license_note"],
               "duration": gt["duration"], "film_end": gt["film_end"], "n_moments": len(moments),
               "n_queries": len(gt["queries"]), "chunk_s": gt["chunking"]["chunk_s"]},
        "gt_queries": {q["id"]: {k: q.get(k) for k in ("prompt", "count", "length", "frame", "tags", "truth")}
                       for q in gt["queries"]},
        "gt_moments": {m["id"]: m for m in moments},
        "headline": head,
        "summary_extra": extra,
        "analysis": analysis,
        "runs": [{"run": r["run"], "summary": r["summary"], "per_query": r["per_query"], "per_clip": r["per_clip"]}
                 for r in run_scores],
        "unrequested_clips": unreq,
        "run": stored_run,
    }


def ragas_step(args, gt: dict, run: dict) -> dict:
    """RAGAS on the first run's queries, within the budget left after them."""
    spent = float((run.get("cost") or {}).get("total_usd") or 0.0)
    budget = max(0.0, args.budget_usd - spent)
    try:
        api = C.AutoClip(args.base, log=log, email=args.email, password=args.password)
        clips = {c["id"]: c for c in api.clips(run["video_id"])}
    except (SystemExit, OSError, KeyError) as e:
        return {"skipped": f"could not fetch clip transcripts: {e}"}
    gone = [c for c in (run.get("clips") or {}).values() if c["id"] not in clips]
    if gone and not args.offline:  # clips deleted since (e.g. --fresh): rebuild their dialogue
        texts = C.window_texts_from_container(run["video_id"], [(c["start"], c["end"]) for c in gone])
        for c, text in zip(gone, texts or []):
            clips[c["id"]] = {"id": c["id"], "title": c.get("title"), "transcript": text}
    truth = {q["id"]: q.get("truth") or [] for q in gt["queries"]}
    per_query = [{**q, "truth": truth.get(q.get("query_id"), [])} for q in (run["runs"][0]["queries"]
                                                                          if run.get("runs") else [])]
    key = C.read_env_key(REPO / ".env") or os.environ.get("OPENROUTER_API_KEY")
    credits = C.Credits(key)
    res = RG.run(per_query, clips, {m["id"]: m for m in gt["moments"]}, api_key=key,
                 base_url=os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
                 budget_usd=budget, model=args.ragas_model, usage=credits.usage, log=log)
    if res.get("cost_usd") is not None and isinstance(run.get("cost"), dict):
        run["cost"]["ragas_usd"] = res["cost_usd"]
    return res


def render_ragas_md(r: dict) -> str:
    if r.get("skipped"):
        return f"## RAGAS\n\nSkipped: {r['skipped']}\n"
    f = lambda v: "–" if v is None else f"{v:.2f}"  # noqa: E731
    rows = "\n".join(f"| {qid} | {f(v.get('faithfulness'))} | {f(v.get('context_precision'))} |"
                     for qid, v in r["per_query"].items())
    cost = "unknown" if r.get("cost_usd") is None else f"${r['cost_usd']:.4f}"
    return (f"## RAGAS (judge: {r['judge_model']})\n\n| query | faithfulness | context precision |\n"
            f"|---|---|---|\n{rows}\n\nRAGAS faithfulness {f(r['faithfulness'])} · "
            f"context precision {f(r['context_precision'])} · cost {cost}\n")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("--gt", required=True, type=Path, help="ground-truth JSON (backend/eval/{movies,podcasts}/<slug>.json)")
    ap.add_argument("--base", default="http://127.0.0.1:8000", help="backend base URL")
    ap.add_argument("--email", default=os.environ.get("EVAL_EMAIL"),
                    help="account to log in as (default: $EVAL_EMAIL); use an ADMIN_EMAILS account to skip quotas")
    ap.add_argument("--password", default=os.environ.get("EVAL_PASSWORD"),
                    help="password (default: $EVAL_PASSWORD — prefer the env var over the flag)")
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--video-id", help="already-uploaded video id")
    src.add_argument("--upload", help="upload this file first")
    ap.add_argument("--from-results", type=Path,
                    help="score an existing run (dir with run.json/report.json/results.json, or a report.json) "
                         "without sending chat messages")
    ap.add_argument("--fresh", action="store_true",
                    help="LOCAL docker stack only: delete the video's existing clips and chat threads first "
                         "(earlier clips block their moments via the no-duplicates rule)")
    ap.add_argument("--runs", type=int, default=1, help="repeat every query N times (live mode)")
    ap.add_argument("--queries", default="all", help="'all' or comma-separated query ids")
    ap.add_argument("--out", type=Path, default=Path("reports/eval"),
                    help="report root; writes <out>/<slug>/<UTC-ts>/")
    ap.add_argument("--out-dir", type=Path, help="write to exactly this directory instead")
    ap.add_argument("--baseline", type=Path, help="baseline report.json to diff against")
    ap.add_argument("--fail-on-regression", type=float, default=0.05, metavar="DELTA",
                    help="absolute drop on any rate metric that counts as a regression (default 0.05)")
    ap.add_argument("--no-conversations", dest="conversations", action="store_false",
                    help="chat on the legacy per-video thread instead of one conversation per query")
    ap.add_argument("--budget-usd", type=float, default=3.0, help="stop sending queries once spend reaches this")
    ap.add_argument("--analysis-timeout", type=float, default=3 * 3600)
    ap.add_argument("--no-probe", action="store_true", help="skip ffprobe/ffmpeg checks")
    ap.add_argument("--shallow-probe", action="store_true", help="ffprobe only (no cropdetect / caption diff)")
    ap.add_argument("--reprobe", action="store_true", help="re-probe clips even if the input already has probes")
    ap.add_argument("--outputs-root", help="host directory mapped to /app (enables local ffmpeg probing)")
    ap.add_argument("--offline", action="store_true",
                    help="never touch docker/postgres/the API (from-results only)")
    ap.add_argument("--source-label", help="override the run's recorded source (e.g. to hide a local path)")
    ap.add_argument("--ragas", action="store_true",
                    help="also score faithfulness + context precision with RAGAS (needs `ragas`; uses the "
                         "budget left after the queries; needs the API for clip transcripts)")
    ap.add_argument("--ragas-model", default=RG.JUDGE_MODEL, help="OpenRouter judge model for --ragas")
    ap.add_argument("--dry-run", action="store_true", help="print the messages that would be sent and exit")
    args = ap.parse_args(argv)

    gt = load_gt(args.gt)
    queries = gt["queries"] if args.queries == "all" else \
        [q for q in gt["queries"] if q["id"] in set(args.queries.split(","))]
    if not queries:
        ap.error(f"no queries match {args.queries!r}; known: {[q['id'] for q in gt['queries']]}")

    if args.dry_run:
        for q in queries:
            print(f"{q['id']:<14} {q['message']}")
        return 0

    exit_code = 0
    if args.from_results:
        run = load_results_dir(args.from_results, gt)
        if args.queries != "all":
            keep = {q["id"] for q in queries}
            for r in run["runs"]:
                r["queries"] = [x for x in r["queries"] if x.get("query_id") in keep]
        mode = "from-results"
    else:
        if not (args.video_id or args.upload):
            ap.error("live mode needs --video-id or --upload (or use --from-results)")
        run, exit_code = run_live(args, gt, queries)
        mode = "live"

    if args.source_label:
        run["source"] = args.source_label
    enrich(run, args)
    probes = probe_all(run, args)
    rep = build_report(gt, run, probes, args, mode)

    regressed = False
    if args.baseline:
        base = json.loads(args.baseline.read_text())
        rows, regressed = S.diff(rep["headline"], base["headline"], args.fail_on_regression)
        rep["diff"] = {"baseline_path": str(args.baseline), "baseline_generated": base["meta"]["generated_utc"],
                       "threshold": args.fail_on_regression, "rows": rows, "regressed": regressed}

    if args.ragas:
        rep["ragas"] = ragas_step(args, gt, run)

    out = args.out_dir or (args.out / gt["slug"] / dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(rep, indent=1, ensure_ascii=False, default=str))
    md = R.render_md(rep)
    if rep.get("ragas"):
        md += "\n" + render_ragas_md(rep["ragas"])
    (out / "report.md").write_text(md)
    (out / "clips.csv").write_text(R.render_csv(rep))

    h = rep["headline"]
    print(f"\n{gt['title']} — {out}/report.md")
    for key, label, _, kind in S.HEADLINE:
        print(f"  {label:<46} {R.fmt(h.get(key), kind):>8}  {R.bar(h.get(key)) if kind == 'rate' else ''}")
    if rep.get("ragas"):
        print("  " + render_ragas_md(rep["ragas"]).strip().splitlines()[-1])
    if args.baseline:
        print(f"\n  {'REGRESSION vs baseline' if regressed else 'no regression vs baseline'}")
    if exit_code:
        return exit_code  # incomplete run: a diff against it is not meaningful
    return 2 if regressed else 0


if __name__ == "__main__":
    sys.exit(main())
