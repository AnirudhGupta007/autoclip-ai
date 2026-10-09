"""Create the shared demo account and give it pre-processed videos.

The demo user (DEMO_EMAIL, default demo@autoclip.local) has no password —
visitors reach it only through "Try demo" (POST /api/auth/demo). It can view
its videos/clips and chat (shared DEMO_DAILY_QUERY_LIMIT), but can't upload
or delete.

    # inside the backend container
    docker compose exec backend python scripts/seed_demo.py --video-id 4cf75b3d8e2a
    # locally
    cd backend && uv run python scripts/seed_demo.py --video-id <id> [--video-id <id2>]

Reassigning moves the video (and with it its clips, moments and files) to
the demo account — the previous owner no longer sees it.
"""
from __future__ import annotations
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from autoclip.auth import settings  # noqa: E402
from autoclip.auth.security import UNUSABLE_PASSWORD  # noqa: E402
from autoclip.database import SessionLocal, init_db  # noqa: E402
from autoclip.models import User, Video  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--video-id", action="append", default=[], help="video to give to the demo user (repeatable)")
    ap.add_argument("--email", default=settings.DEMO_EMAIL, help="demo account email (default: DEMO_EMAIL)")
    args = ap.parse_args()

    init_db()
    email = args.email.strip().lower()
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        if user is None:
            user = User(email=email, password_hash=UNUSABLE_PASSWORD, is_admin=False, is_demo=True)
            db.add(user)
            db.commit()
            print(f"created demo user {email} (id={user.id})")
        else:
            if not user.is_demo or user.is_admin:
                user.is_demo, user.is_admin = True, False
                user.password_hash = UNUSABLE_PASSWORD
                db.commit()
            print(f"demo user {email} exists (id={user.id})")

        for vid in args.video_id:
            video = db.query(Video).filter(Video.id == vid).first()
            if video is None:
                print(f"  ! video {vid} not found", file=sys.stderr)
                continue
            video.user_id = user.id
            db.commit()
            print(f"  video {vid} ({video.filename}, status={video.status}) -> demo")
        n = db.query(Video).filter(Video.user_id == user.id).count()
        print(f"demo user now owns {n} video(s)")
    finally:
        db.close()
    if email != settings.DEMO_EMAIL:
        print(f"note: set DEMO_EMAIL={email} so POST /api/auth/demo finds this account")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
