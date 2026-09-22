#!/usr/bin/env python3
"""Run one video through many clip formats and report a results table.

The moment map is computed once and cached, so every additional format is a
cheap retrieval + ffmpeg cut. That makes a single long video a broad test:
one analysis, a dozen different asks.

    python backend/scripts/test_matrix.py --video-id abc123
    python backend/scripts/test_matrix.py --upload /path/movie.mkv --out matrix.md

Writes a markdown table (and --json for raw records) covering, per request:
wall time, clips produced, durations actually delivered vs asked, mean score,
and the OpenRouter spend measured from the credits endpoint.
"""
from __future__ import annotations
import argparse
import json
import os
import statistics
import sys
import time
from dataclasses import dataclass, asdict, field

import httpx

BASE = os.getenv("AUTOCLIP_BASE", "http://localhost:8000")
OR_KEY = os.getenv("OPENROUTER_API_KEY", "")

# (label, prompt, expected_seconds, expected_frame)
MATRIX: list[tuple[str, str, int, str]] = [
    ("TikTok 10s",      "give me 2 clips of about 10 seconds for TikTok",            10, "9:16"),
    ("TikTok 20s",      "give me 2 funny clips under 20 seconds for TikTok",          20, "9:16"),
    ("Reels 30s",       "3 clips around 30 seconds for Instagram Reels",              30, "9:16"),
    ("Shorts 60s",      "one 60 second clip for YouTube Shorts",                      60, "9:16"),
    ("Square 30s",      "2 clips at 30 seconds in square format",                     30, "1:1"),
    ("YouTube 16:9",    "a 45 second clip in 16:9 for YouTube",                       45, "16:9"),
    ("Emotional beat",  "the most emotional moment, 20 seconds, vertical",            20, "9:16"),
    ("Tense moment",    "where it gets tense or heated, 30 seconds",                  30, "9:16"),
    ("Funniest",        "the single funniest moment, 15 seconds, TikTok",             15, "9:16"),
    ("Quotable",        "a quotable line under 20 seconds, vertical",                 20, "9:16"),
]


@dataclass
class Result:
    label: str
    prompt: str
    ok: bool
    seconds: float
    clips: int
    asked_len: int
    got_lens: list[float] = field(default_factory=list)
    asked_frame: str = ""
    got_frames: list[str] = field(default_factory=list)
    mean_score: float | None = None
    cost: float | None = None
    reply: str = ""


def credits() -> float | None:
    if not OR_KEY:
        return None
    try:
        r = httpx.get(
            "https://openrouter.ai/api/v1/credits",
            headers={"Authorization": f"Bearer {OR_KEY}"},
            timeout=20,
        ).json()["data"]
        return round(r["total_credits"] - r["total_usage"], 6)
    except Exception:
        return None


def upload(path: str) -> str:
    with open(path, "rb") as fh:
        r = httpx.post(
            f"{BASE}/api/videos/upload",
            files={"file": (os.path.basename(path), fh, "video/mp4")},
            timeout=3600,
        )
    r.raise_for_status()
    vid = r.json()["id"]
    print(f"uploaded → video_id={vid}", flush=True)
    return vid


def ask(video_id: str, prompt: str, timeout: float) -> dict:
    r = httpx.post(
        f"{BASE}/api/chat/message",
        json={"message": prompt, "video_id": video_id},
        timeout=timeout,
    )
    r.raise_for_status()
    return r.json()


def run_matrix(video_id: str, timeout: float) -> list[Result]:
    results: list[Result] = []
    for label, prompt, exp_len, exp_frame in MATRIX:
        print(f"→ {label}: {prompt}", flush=True)
        before = credits()
        t0 = time.time()
        try:
            data = ask(video_id, prompt, timeout)
            clips = data.get("clips") or []
            scores = [c.get("overall_score") for c in clips if c.get("overall_score") is not None]
            res = Result(
                label=label, prompt=prompt, ok=True,
                seconds=round(time.time() - t0, 1),
                clips=len(clips),
                asked_len=exp_len,
                got_lens=[round(c.get("duration", 0), 1) for c in clips],
                asked_frame=exp_frame,
                got_frames=[c.get("frame", "?") for c in clips],
                mean_score=round(statistics.mean(scores), 2) if scores else None,
                reply=(data.get("response") or "")[:160],
            )
        except Exception as e:
            res = Result(
                label=label, prompt=prompt, ok=False,
                seconds=round(time.time() - t0, 1), clips=0,
                asked_len=exp_len, asked_frame=exp_frame, reply=f"ERROR: {e}"[:160],
            )
        after = credits()
        if before is not None and after is not None:
            res.cost = round(before - after, 6)
        results.append(res)
        print(f"   {res.clips} clips · {res.seconds}s · cost={res.cost}", flush=True)
    return results


def to_markdown(results: list[Result], video_id: str) -> str:
    total_cost = sum(r.cost or 0 for r in results)
    produced = sum(r.clips for r in results)

    # Format adherence: did we get back the aspect ratio that was asked for?
    frame_hits = sum(
        1 for r in results for f in r.got_frames if f == r.asked_frame
    )
    frame_total = sum(len(r.got_frames) for r in results)

    # Length adherence: within 25% of the requested length.
    len_hits = sum(
        1 for r in results for d in r.got_lens
        if r.asked_len and abs(d - r.asked_len) <= 0.25 * r.asked_len
    )
    len_total = sum(len(r.got_lens) for r in results)

    lines = [
        f"# Format matrix — `{video_id}`",
        "",
        f"- Requests: **{len(results)}**, clips produced: **{produced}**",
        f"- Aspect-ratio adherence: **{frame_hits}/{frame_total}**"
        + (f" ({100*frame_hits/frame_total:.0f}%)" if frame_total else ""),
        f"- Length within ±25% of ask: **{len_hits}/{len_total}**"
        + (f" ({100*len_hits/len_total:.0f}%)" if len_total else ""),
        f"- Measured OpenRouter spend: **${total_cost:.4f}**",
        "",
        "| Ask | Clips | Wall | Durations (asked) | Frames (asked) | Mean score | Cost |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in results:
        lines.append(
            f"| {r.label} | {r.clips} | {r.seconds}s | "
            f"{r.got_lens or '—'} ({r.asked_len}s) | "
            f"{r.got_frames or '—'} ({r.asked_frame}) | "
            f"{r.mean_score if r.mean_score is not None else '—'} | "
            f"{f'${r.cost:.4f}' if r.cost is not None else '—'} |"
        )

    failures = [r for r in results if not r.ok or r.clips == 0]
    if failures:
        lines += ["", "## Requests that produced nothing", ""]
        for r in failures:
            lines.append(f"- **{r.label}** — {r.reply}")
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--video-id", help="already-uploaded video id")
    ap.add_argument("--upload", help="path to a video to upload first")
    ap.add_argument("--out", default="MATRIX.md")
    ap.add_argument("--json", dest="json_out")
    ap.add_argument("--timeout", type=float, default=3600)
    args = ap.parse_args()

    if not args.video_id and not args.upload:
        ap.error("pass --video-id or --upload")

    video_id = args.video_id or upload(args.upload)

    start = credits()
    results = run_matrix(video_id, args.timeout)
    end = credits()

    md = to_markdown(results, video_id)
    with open(args.out, "w") as fh:
        fh.write(md)
    if args.json_out:
        with open(args.json_out, "w") as fh:
            json.dump([asdict(r) for r in results], fh, indent=2)

    print("\n" + md)
    if start is not None and end is not None:
        print(f"total measured spend: ${start - end:.4f}")
    print(f"written → {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
