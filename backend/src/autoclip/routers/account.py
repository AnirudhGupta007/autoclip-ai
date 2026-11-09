"""/api/me — today's usage + storage, and account deletion (API_CONTRACT.md)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from autoclip.auth.deps import clear_session_cookie, current_user, require_not_demo
from autoclip.database import get_db
from autoclip.models import Clip, User, Video
from autoclip.services import rate_limit, storage
from autoclip.services.conversations import iso

router = APIRouter(prefix="/api/me", tags=["account"], dependencies=[Depends(current_user)])


@router.get("/usage")
async def usage(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Queries used today, bytes stored, and when each item's files expire."""
    videos = (db.query(Video).filter(Video.user_id == user.id)
              .order_by(Video.created_at.desc()).all())
    clips_by_video: dict[str, list[Clip]] = {v.id: [] for v in videos}
    if videos:
        for c in db.query(Clip).filter(Clip.video_id.in_(list(clips_by_video))).all():
            clips_by_video[c.video_id].append(c)
    sizes = await run_in_threadpool(lambda: {v.id: storage.video_bytes(v.id) for v in videos})
    items = [{
        "video_id": v.id,
        "title": v.filename,
        "media_kind": v.media_kind or "video",
        "size_bytes": sizes[v.id],
        "source_expires_at": iso(storage.source_expires_at(v, user)),
        "clips_expire_at": iso(storage.clips_expire_at(clips_by_video[v.id], user)),
        "archived": bool(v.archived),
    } for v in videos]
    limit = rate_limit.chat_limit(user)
    return {
        "queries_used": min(rate_limit.used(user), limit) if limit is not None else rate_limit.used(user),
        "queries_limit": limit,
        "storage_bytes": sum(sizes.values()),
        "storage_quota_bytes": storage.quota_for(user),
        "items": items,
    }


@router.delete("", status_code=204)
def delete_me(user: User = Depends(require_not_demo), db: Session = Depends(get_db)):
    """Delete the account: files, rows, sessions, chat checkpoints. The demo
    account gets 403 (require_not_demo)."""
    from autoclip.utils import analysis_jobs

    vids = [r[0] for r in db.query(Video.id).filter(Video.user_id == user.id).all()]
    if any(analysis_jobs.is_running(v) for v in vids):
        raise HTTPException(409, "One of your uploads is still being analysed — try again when it finishes.")
    try:
        storage.delete_account(db, user)
    except Exception:
        raise HTTPException(500, "Could not delete the account. Nothing was removed.")
    response = Response(status_code=204)
    clear_session_cookie(response)
    return response
