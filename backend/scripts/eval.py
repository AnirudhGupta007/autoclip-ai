"""Eval harness — runs the pipeline against labeled videos and reports
precision@k and mean convergence on the surfaced moments.

Usage:
    python -m scripts.eval --dataset eval/dataset.json [--k 6]

dataset.json format (one row per video):
    [
      {
        "video_id": "demo1",
        "video_path": "uploads/demo1.mp4",
        "good_windows": [[12.0, 25.0], [54.0, 75.0], ...]
      },
      ...
    ]
"""
from __future__ import annotations
import argparse
import json
import os
import statistics
import sys
import time
from pathlib import Path

# Make `autoclip` importable when running from backend/
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from autoclip.pipeline.graph import pipeline  # noqa: E402
from autoclip.pipeline import telemetry      # noqa: E402


def _overlap_frac(a: tuple[float, float], b: tuple[float, float]) -> float:
    inter = max(0.0, min(a[1], b[1]) - max(a[0], b[0]))
    if inter <= 0:
        return 0.0
    shorter = min(a[1] - a[0], b[1] - b[0])
    return inter / shorter if shorter else 0.0


def precision_at_k(predicted: list, labeled_windows: list[list[float]], k: int) -> float:
    """Fraction of top-k predicted moments that overlap a labeled good window >= 50%."""
    top = predicted[:k]
    if not top:
        return 0.0
    hits = 0
    for m in top:
        win = (float(m.start), float(m.end))
        if any(_overlap_frac(win, (float(s), float(e))) >= 0.5 for s, e in labeled_windows):
            hits += 1
    return hits / len(top)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default="eval/dataset.json")
    ap.add_argument("--k", type=int, default=6)
    args = ap.parse_args()

    rows = json.loads(Path(args.dataset).read_text())
    if not rows:
        print("dataset is empty", file=sys.stderr)
        return 1

    telemetry.reset()
    p_at_k_scores: list[float] = []
    convergence_means: list[float] = []
    durations: list[float] = []

    for row in rows:
        vid = row["video_id"]
        path = row["video_path"]
        good = row["good_windows"]
        print(f"\n→ {vid} ({path})")

        start = time.time()
        state = {
            "video_id": vid,
            "video_path": path,
            "clip_configs": [],
            "analysis_complete": False,
            "needs_reanalysis": False,
            "chunk_plans": [],
            "moment_map_raw": [],
            "scene_boundaries": [],
        }
        result = pipeline.invoke(state, {"configurable": {"thread_id": vid}})
        elapsed = time.time() - start
        durations.append(elapsed)

        moments = result.get("moment_map") or []
        p = precision_at_k(moments, good, args.k)
        p_at_k_scores.append(p)
        if moments:
            convergence_means.append(statistics.fmean(m.convergence_score for m in moments))

        print(f"  moments={len(moments)} P@{args.k}={p:.2f} elapsed={elapsed:.1f}s")

    print("\n=== Summary ===")
    print(f"videos:                 {len(rows)}")
    print(f"mean P@{args.k}:           {statistics.fmean(p_at_k_scores):.3f}")
    print(f"mean convergence score: {statistics.fmean(convergence_means):.3f}" if convergence_means else "no moments")
    print(f"mean wall time:         {statistics.fmean(durations):.1f}s")
    print()
    print("--- Gemini cache hit rate per model ---")
    for model, snap in telemetry.snapshot().items():
        print(
            f"  {model}: calls={snap.calls} prompt={snap.prompt_tokens} "
            f"cached={snap.cached_tokens} ({snap.cache_hit_rate * 100:.1f}%)"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
