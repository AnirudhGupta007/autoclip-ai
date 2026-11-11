"""Rebuild a talk video's moments as transcript segments, without re-analysis.

Reuses the stored transcript (outputs/<id>/transcript.json) and, for video,
the stored vision moments as on-screen context (services/talk_segments.py),
so it costs only the segmentation + strict-tagging calls (lite model) and
the embeddings. Replaces the video's moments (rows + vector nodes) unless
--dry-run.

Run inside the backend container:
  docker compose exec backend python scripts/resegment.py --video-id cd0d82336186
  docker compose exec backend python scripts/resegment.py --video-id 6ac4b72bc523 --dry-run --out /tmp/seg.json
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time

from autoclip.database import SessionLocal
from autoclip.models import MomentRecord, Video
from autoclip.pipeline.agents.global_fusion import segment_moment_map
from autoclip.services.talk_segments import is_segment
from autoclip.utils.analysis_jobs import video_output_dir


def resegment(video_id: str, dry_run: bool = False, embed: bool = True) -> dict:
    from autoclip.agent.tools import _row_to_moment
    db = SessionLocal()
    try:
        video = db.query(Video).filter(Video.id == video_id).first()
        if not video:
            return {"video_id": video_id, "error": "not found"}
        rows = db.query(MomentRecord).filter(MomentRecord.video_id == video_id).all()
        context = [m for m in (_row_to_moment(r) for r in rows) if not is_segment(m)]
        if video.media_kind == "audio":
            context = []  # audio "moments" are transcript-only; nothing seen to keep
        transcript = json.loads((video_output_dir(video_id) / "transcript.json").read_text())
        state = {"video_id": video_id, "video_path": video.file_path,
                 "media_kind": video.media_kind or "video", "transcript_data": transcript}
        t0 = time.time()
        if not embed:
            import autoclip.services.embeddings as E
            E.embed_moments = lambda ms: None  # noqa: E731  (dry runs on a free model)
        segments = segment_moment_map(state, context)
        took = round(time.time() - t0, 1)
        if not dry_run:
            from autoclip.services.moment_store import persist_moments
            persist_moments(db, video_id, segments)
    finally:
        db.close()
    lens = [m.end - m.start for m in segments]
    dist: dict[str, int] = {}
    for m in segments:
        for c in m.categories:
            dist[c] = dist.get(c, 0) + 1
    return {
        "video_id": video_id, "media_kind": video.media_kind, "context_moments": len(context),
        "previous_moments": len(rows), "segments": len(segments), "seconds": took,
        "mean_len": round(sum(lens) / max(1, len(lens)), 1),
        "min_len": round(min(lens or [0]), 1), "max_len": round(max(lens or [0]), 1),
        "tag_distribution": dict(sorted(dist.items(), key=lambda x: -x[1])),
        "embedded": sum(1 for m in segments if m.embedding),
        "persisted": not dry_run,
        "items": [{"start": m.start, "end": m.end, "payoff": m.payoff, "summary": m.description,
                   "categories": m.categories, "why": m.why, "score": m.convergence_score}
                  for m in sorted(segments, key=lambda m: m.start)],
    }


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--video-id", required=True, action="append")
    ap.add_argument("--dry-run", action="store_true", help="don't replace the stored moments")
    ap.add_argument("--no-embed", action="store_true", help="skip embeddings (dry runs)")
    ap.add_argument("--out", help="write the full result (segments included) as JSON here")
    args = ap.parse_args(argv)
    results = [resegment(v, dry_run=args.dry_run, embed=not args.no_embed) for v in args.video_id]
    for r in results:
        print(json.dumps({k: v for k, v in r.items() if k != "items"}), flush=True)
    if args.out:
        with open(args.out, "w") as f:
            json.dump(results, f, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
