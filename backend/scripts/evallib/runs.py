"""Loading ground truth and run records.

A *run record* is the normalised, scorer-facing description of one eval run:

    {
      "video_id": str, "mode": "live" | "from-results", "source": str,
      "runs": [ {"run": 1, "queries": [QueryRec, ...]} , ...],
      "clips": {clip_id: ClipRec},       # every clip seen, any run
      "moments": [ {start, end, convergence_score, style_tags, description}, ...],
      "raw_chunk_moments": [ {chunk_index, start, end}, ...] | None,
      "chunks": {"planned": int, "failed": [int]} | None,
      "transcript": {"word_starts": [float], "duration": float} | None,
      "cost": {"total_usd": float | None, "note": str},
      "analysis_s": float | None,
    }
    QueryRec = {query_id, message, status, elapsed_s, cost_usd, agent_text,
                clip_ids: [new clips, delivery order], returned_ids: [all ids in response],
                analysis_waited_s, error}
    ClipRec  = {id, title, start, end, file_path, frame, query_id, run, returned_to_user,
                delivered_len_s, delivered_res}

Two on-disk inputs are understood by :func:`load_results_dir`:
  * a directory (or report.json) written by eval_movie.py — contains ``run``;
  * the hand-collected "apprun" layout (results.json + chat_*.json +
    moments_db.txt + sse.log + credits_*.json/credits_log.txt) used for the
    first baseline.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

_WORD = re.compile(r"[a-z0-9:]+")
_STOP = {"a", "an", "the", "me", "give", "of", "and", "or", "clip", "clips", "moment", "moments",
         "seconds", "second", "each", "this", "movie", "analyze", "where", "s", "i", "want"}


def load_gt(path: Path) -> dict:
    gt = json.loads(Path(path).read_text())
    ids = {m["id"] for m in gt["moments"]}
    for q in gt["queries"]:
        missing = [t for t in q["truth"] if t not in ids]
        if missing:
            raise ValueError(f"query {q['id']} references unknown moments {missing}")
        q.setdefault("count", 1)
        q.setdefault("message", build_message(q))
    gt.setdefault("chunking", {"chunk_s": 120, "overlap_s": 10})
    return gt


def build_message(q: dict) -> str:
    """Natural chat phrasing for a GT query, e.g. 'Give me the funniest moment, 30 seconds, 9:16'."""
    p = q["prompt"]
    lead = f"Give me {q['count']} clips: {p}" if q.get("count", 1) > 1 else f"Give me {p}"
    parts = [lead]
    if q.get("length"):
        parts.append(f"{q['length']} seconds" + (" each" if q.get("count", 1) > 1 else ""))
    if q.get("frame"):
        parts.append(q["frame"])
    return ", ".join(parts)


def _tokens(s: str) -> set[str]:
    return {w for w in _WORD.findall(s.lower()) if w not in _STOP and not w.isdigit()}


def match_query(message: str, queries: list[dict]) -> Optional[dict]:
    """Map a recorded chat message to a GT query: exact `message` match first,
    then best token overlap with prompt+tags (must share ≥1 content word)."""
    for q in queries:
        if q.get("message", "").strip().lower() == message.strip().lower():
            return q
    mt = _tokens(message)
    best, best_s = None, 0.0
    for q in queries:
        qt = _tokens(q["prompt"]) | set(q.get("tags", []))
        if not qt:
            continue
        s = len(mt & qt) / len(qt)
        if s > best_s:
            best, best_s = q, s
    return best if best_s > 0 else None


# ---------------------------------------------------------------- apprun layout
def _parse_moments_txt(path: Path) -> list[dict]:
    """moments_db.txt: `start|end|score|["tags"]|description|transcript` (psql -A
    output; transcripts may wrap onto following lines, which are skipped)."""
    out = []
    row = re.compile(r"^(\d+(?:\.\d+)?)\|(\d+(?:\.\d+)?)\|(\d+(?:\.\d+)?)\|(\[.*?\])\|([^|]*)")
    for line in path.read_text().splitlines():
        m = row.match(line)
        if not m:
            continue
        try:
            tags = json.loads(m.group(4))
        except json.JSONDecodeError:
            tags = []
        out.append({"start": float(m.group(1)), "end": float(m.group(2)),
                    "convergence_score": float(m.group(3)), "style_tags": tags,
                    "description": m.group(5)[:160]})
    return out


def _parse_sse_chunks(path: Path) -> list[dict]:
    raw = []
    for line in path.read_text(errors="replace").splitlines():
        if '"chunk_index"' not in line or "data: " not in line:
            continue
        try:
            d = json.loads(line.split("data: ", 1)[1])
        except json.JSONDecodeError:
            continue
        for m in d.get("moments", []) or []:
            if "start" in m and "end" in m:
                raw.append({"chunk_index": d["chunk_index"], "start": float(m["start"]), "end": float(m["end"])})
    return raw


def _credit_reads(d: Path) -> tuple[Optional[float], dict[str, float], Optional[float]]:
    def usage(p: Path) -> Optional[float]:
        try:
            return float(json.loads(p.read_text())["data"]["total_usage"])
        except (OSError, KeyError, ValueError, TypeError):
            return None
    before = usage(d / "credits_before.json")
    after = usage(d / "credits_after.json")
    log: dict[str, float] = {}
    if (d / "credits_log.txt").is_file():
        for line in (d / "credits_log.txt").read_text().splitlines():
            parts = line.split(" ", 2)
            if len(parts) == 3:
                try:
                    log[parts[0]] = float(json.loads(parts[2])["data"]["total_usage"])
                except (ValueError, KeyError, TypeError):
                    pass
    return before, log, after


def _load_apprun(d: Path, gt: dict) -> dict:
    res = json.loads((d / "results.json").read_text())
    chats = {}
    for p in sorted(d.glob("chat_*.json")):
        c = json.loads(p.read_text())
        chats[c.get("tag", p.stem[5:])] = c
    for tag, c in (res.get("chats") or {}).items():
        chats.setdefault(tag, {"tag": tag, **c})

    before, log, after = _credit_reads(d)
    order = sorted(chats)  # tags a, b, c… were sent in this order
    prev = before
    tag_cost: dict[str, Optional[float]] = {}
    for tag in order:
        cur = log.get(f"after_{tag}")
        tag_cost[tag] = (cur - prev) if (cur is not None and prev is not None) else None
        prev = cur if cur is not None else prev

    clips: dict[str, dict] = {}
    by_tag: dict[str, list[str]] = {}
    for c in res.get("clips", []):
        clips[c["clip_id"]] = {
            "id": c["clip_id"], "title": c.get("title"), "start": float(c["start"]), "end": float(c["end"]),
            "file_path": (c.get("file") or "").replace("/app/", "", 1) or None,
            "frame": None, "query_id": None, "run": 1, "request_tag": c.get("request"),
            "returned_to_user": bool(c.get("returned_to_user")),
            "delivered_len_s": c.get("delivered_len_s"), "delivered_res": c.get("delivered_res"),
        }
        by_tag.setdefault(c.get("request"), []).append(c["clip_id"])

    queries = []
    seen: set[str] = set(by_tag.get("default", []))
    for tag in order:
        c = chats[tag]
        resp = c.get("response") if isinstance(c.get("response"), dict) else {}
        q = match_query(c.get("message", ""), gt["queries"])
        returned = [x.get("id") for x in (resp.get("clips") or [])]
        new = by_tag.get(tag) or [i for i in returned if i not in seen]
        seen.update(returned)
        for x in resp.get("clips") or []:  # fill frame info from the API payload
            if x.get("id") in clips:
                clips[x["id"]]["frame"] = x.get("frame")
        for cid in new:
            if cid in clips:
                clips[cid]["query_id"] = q["id"] if q else None
        queries.append({
            "query_id": q["id"] if q else None, "tag": tag, "message": c.get("message"),
            "status": c.get("status"), "elapsed_s": c.get("elapsed_s"), "cost_usd": tag_cost.get(tag),
            "agent_text": resp.get("response") or c.get("agent_text"), "clip_ids": new,
            "returned_ids": returned, "analysis_waited_s": None, "error": None if c.get("status") == 200 else str(c.get("response"))[:300],
        })

    moments = _parse_moments_txt(d / "moments_db.txt") if (d / "moments_db.txt").is_file() else None
    raw = _parse_sse_chunks(d / "sse.log") if (d / "sse.log").is_file() else None
    transcript = None
    if (d / "transcript.json").is_file():
        t = json.loads((d / "transcript.json").read_text())
        transcript = {"duration": t.get("duration"),
                      "word_starts": t.get("word_starts") or [w["start"] for w in t.get("words", [])]}
    elif res.get("transcript_coverage_s"):
        transcript = {"span_only": res["transcript_coverage_s"]}

    total = res.get("openrouter_spend_usd")
    if total is None and before is not None and after is not None:
        total = after - before
    return {
        "video_id": res.get("video_id"), "mode": "from-results", "source": str(d),
        "runs": [{"run": 1, "queries": queries}],
        "clips": clips, "moments": moments, "raw_chunk_moments": raw,
        "chunks": {"planned": res.get("chunks_planned"), "failed": res.get("chunks_failed") or []}
        if res.get("chunks_planned") else None,
        "transcript": transcript,
        "cost": {"total_usd": total,
                 "note": "OpenRouter credits delta over the whole run; the first query includes analysis."},
        "analysis_s": None,
        "unrequested_clip_ids": by_tag.get("default", []),
    }


def load_results_dir(path: Path, gt: dict) -> dict:
    path = Path(path)
    if path.is_file() and path.suffix == ".json":
        d = json.loads(path.read_text())
        return d["run"] if "run" in d else d
    if (path / "run.json").is_file():
        return json.loads((path / "run.json").read_text())
    if (path / "report.json").is_file():
        d = json.loads((path / "report.json").read_text())
        if "run" in d:
            return d["run"]
    if (path / "results.json").is_file():
        return _load_apprun(path, gt)
    raise FileNotFoundError(f"{path}: no run.json, report.json or results.json")
