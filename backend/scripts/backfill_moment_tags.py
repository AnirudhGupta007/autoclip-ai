"""Backfill moment categories + "why" lines for already-analysed videos.

New analyses tag moments at the end of global fusion; this runs the same
cheap text-only pass (lite model, batched) over stored MomentRecords, so no
re-analysis is needed. Optionally also drops moments inside the detected end
credits (new analyses never store them).

Run inside the backend container:
  docker compose exec backend python scripts/backfill_moment_tags.py --video-id 6d3872df73b1 --prune-credits
  docker compose exec backend python scripts/backfill_moment_tags.py --all [--force]
"""
from __future__ import annotations

import argparse
import logging
import sys

from autoclip.database import SessionLocal
from autoclip.models import MomentRecord, Video
from autoclip.services.moment_tagger import tag_moments
from autoclip.utils.video_profile import credits_start


def backfill(video_id: str, force: bool = False, prune_credits: bool = False) -> dict:
    db = SessionLocal()
    try:
        video = db.query(Video).filter(Video.id == video_id).first()
        if not video:
            return {"video_id": video_id, "error": "not found"}
        rows = db.query(MomentRecord).filter(MomentRecord.video_id == video_id).all()
        pruned = 0
        if prune_credits:
            c = credits_start(video_id, video.file_path)
            if c:
                for r in [r for r in rows if r.start >= c]:
                    db.delete(r)
                    pruned += 1
                rows = [r for r in rows if r.start < c]
        # MomentRecord has description/transcript/categories/why — tag in place.
        for r in rows:
            r.categories = list(r.categories or []) if r.categories is not None else []
            r.why = r.why or ""
        todo = [r for r in rows if force or not r.why]
        tagged = tag_moments(todo, force=True)
        for r in rows:
            if not r.why:  # untagged (failed batch) -> keep NULL so a rerun retries
                r.categories, r.why = None, None
        db.commit()
        if pruned:
            # keep the RAG node table (used by /api/search) in step with the rows
            from autoclip.rag.index import index_moments
            from autoclip.agent.tools import _row_to_moment
            index_moments(video_id, [_row_to_moment(r) for r in rows])
        return {"video_id": video_id, "moments": len(rows), "tagged": tagged, "pruned_credits": pruned}
    finally:
        db.close()


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--video-id", action="append", help="video id (repeatable)")
    g.add_argument("--all", action="store_true", help="every video with moments")
    ap.add_argument("--force", action="store_true", help="re-tag moments that already have tags")
    ap.add_argument("--prune-credits", action="store_true", help="delete moments inside the end credits")
    args = ap.parse_args(argv)
    ids = args.video_id
    if args.all:
        db = SessionLocal()
        try:
            ids = [v for (v,) in db.query(MomentRecord.video_id).distinct().all()]
        finally:
            db.close()
    for vid in ids:
        print(backfill(vid, force=args.force, prune_credits=args.prune_credits), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
