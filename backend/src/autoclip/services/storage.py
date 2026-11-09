"""Storage quota, disk guard, retention and account deletion.

The box has ~17 GB free and no disk resize is planned, so files don't live
forever (values in auth/settings.py, all env-configurable):

  • at most MAX_VIDEOS_PER_USER active uploads and STORAGE_QUOTA_MB of
    sources + clips per user (admins exempt);
  • no uploads at all while free disk < MIN_FREE_DISK_GB;
  • a source file is deleted SOURCE_RETENTION_DAYS after upload and the
    video becomes "archived": transcript, moments, chats and clips stay, old
    clips still play, new clips need a re-upload;
  • rendered clips are deleted CLIP_RETENTION_DAYS after they were made;
  • an account inactive for INACTIVE_ACCOUNT_DAYS loses all its files (the
    account and its chats stay).

Admin and demo accounts are exempt from retention: the owner's eval videos
and the public demo's source must not disappear.

`run_cleanup()` applies the rules; `cleanup_loop()` (started in main.py's
lifespan) runs it once a day, with a Redis key as the cross-worker lock.
"""
from __future__ import annotations
import asyncio
import logging
import shutil
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from autoclip.auth import settings
from autoclip.config import OUTPUT_DIR, UPLOAD_DIR
from autoclip.models import AuthSession, Clip, User, Video, utcnow
from autoclip.utils.paths import clip_dir

logger = logging.getLogger(__name__)

ARCHIVED_MESSAGE = (f"This upload's source file was deleted {settings.SOURCE_RETENTION_DAYS} days after "
                    "upload (storage rule). Its existing clips still play — re-upload the file "
                    "to make new clips.")
GB = 1024 ** 3


# ─── sizes ──────────────────────────────────────────────────────

def dir_bytes(path: Path) -> int:
    total = 0
    try:
        for p in Path(path).rglob("*"):
            try:
                if p.is_file() and not p.is_symlink():
                    total += p.stat().st_size
            except OSError:
                continue
    except OSError:
        pass
    return total


def video_bytes(video_id: str) -> int:
    return dir_bytes(Path(UPLOAD_DIR) / video_id) + dir_bytes(Path(OUTPUT_DIR) / video_id)


def user_bytes(db: Session, user_id: int) -> int:
    ids = [r[0] for r in db.query(Video.id).filter(Video.user_id == user_id).all()]
    return sum(video_bytes(v) for v in ids)


def free_disk_bytes() -> int:
    return shutil.disk_usage(UPLOAD_DIR).free


# ─── upload guards ──────────────────────────────────────────────

def check_disk_guard() -> None:
    """507 for everyone while the disk is nearly full."""
    if settings.MIN_FREE_DISK_GB <= 0:
        return
    if free_disk_bytes() < settings.MIN_FREE_DISK_GB * GB:
        raise HTTPException(507, "The server is low on disk space, so uploads are paused. "
                                 "Please try again later.")


def quota_for(user: User) -> Optional[int]:
    """Per-user storage quota in bytes; None = unlimited (admins)."""
    return None if user.is_admin else settings.STORAGE_QUOTA_BYTES


def quota_exceeded(quota: int) -> HTTPException:
    return HTTPException(413, (f"This upload would go over your {quota / GB:.1f} GB storage quota. "
                               "Delete something in your Library to make room."))


def active_upload_count(db: Session, user_id: int) -> int:
    return db.query(Video).filter(Video.user_id == user_id, Video.archived.is_(False)).count()


# ─── expiry dates ───────────────────────────────────────────────

def retention_exempt(user: Optional[User]) -> bool:
    return bool(user is not None and (user.is_admin or user.is_demo))


def _naive(dt: Optional[datetime]) -> Optional[datetime]:
    return dt.replace(tzinfo=None) if dt is not None and dt.tzinfo is not None else dt


def source_expires_at(video: Video, owner: Optional[User]) -> Optional[datetime]:
    if video.archived or retention_exempt(owner) or settings.SOURCE_RETENTION_DAYS <= 0:
        return None
    return _naive(video.created_at) + timedelta(days=settings.SOURCE_RETENTION_DAYS) if video.created_at else None


def clips_expire_at(clips: list[Clip], owner: Optional[User]) -> Optional[datetime]:
    if not clips or retention_exempt(owner) or settings.CLIP_RETENTION_DAYS <= 0:
        return None
    made = [_naive(c.created_at) for c in clips if c.created_at]
    return min(made) + timedelta(days=settings.CLIP_RETENTION_DAYS) if made else None


# ─── deleting things ────────────────────────────────────────────

def archive_source(db: Session, video: Video) -> None:
    """Delete the upload dir (source / audiogram / original audio); keep
    everything in outputs (transcript, clips). Commits."""
    shutil.rmtree(Path(UPLOAD_DIR) / video.id, ignore_errors=True)
    video.archived = True
    db.commit()


def delete_clip(db: Session, clip: Clip) -> None:
    """Clip files + row (no commit)."""
    shutil.rmtree(clip_dir(clip.video_id, clip.id), ignore_errors=True)
    db.delete(clip)


def purge_user_files(db: Session, user_id: int) -> int:
    """Inactive account: every file goes, the account and its chats stay.
    Videos remain as archived rows (with their moments) so the Library and
    old chats still make sense. Commits. Returns videos touched."""
    videos = db.query(Video).filter(Video.user_id == user_id).all()
    for v in videos:
        db.query(Clip).filter(Clip.video_id == v.id).delete(synchronize_session=False)
        shutil.rmtree(Path(UPLOAD_DIR) / v.id, ignore_errors=True)
        shutil.rmtree(Path(OUTPUT_DIR) / v.id, ignore_errors=True)
        v.archived = True
    db.commit()
    return len(videos)


def delete_account(db: Session, user: User) -> None:
    """Remove a user's files, rows, sessions and chat checkpoints."""
    from autoclip.routers.chat import chat_thread_id
    from autoclip.services.conversations import delete_user_conversations, forget_threads
    from autoclip.services.moment_store import delete_moments

    uid = user.id
    video_ids = [r[0] for r in db.query(Video.id).filter(Video.user_id == uid).all()]
    try:
        for vid in video_ids:
            delete_moments(db, vid)
            db.query(Clip).filter(Clip.video_id == vid).delete(synchronize_session=False)
        conv_ids = delete_user_conversations(db, uid)
        db.query(Video).filter(Video.user_id == uid).delete(synchronize_session=False)
        db.query(AuthSession).filter(AuthSession.user_id == uid).delete(synchronize_session=False)
        db.query(User).filter(User.id == uid).delete(synchronize_session=False)
        db.commit()
    except Exception:
        db.rollback()
        raise
    for vid in video_ids:
        shutil.rmtree(Path(UPLOAD_DIR) / vid, ignore_errors=True)
        shutil.rmtree(Path(OUTPUT_DIR) / vid, ignore_errors=True)
    forget_threads([chat_thread_id(uid, None, c) for c in conv_ids]
                   + [chat_thread_id(uid, v) for v in video_ids] + [chat_thread_id(uid, None)])


# ─── the nightly job ────────────────────────────────────────────

def _exempt_ids(db: Session) -> set[int]:
    return {r[0] for r in db.query(User.id).filter(or_(User.is_admin.is_(True), User.is_demo.is_(True))).all()}


def run_cleanup(now: Optional[datetime] = None) -> dict:
    """Apply the retention rules once. `now` (naive UTC) is injectable for tests."""
    from autoclip.database import SessionLocal
    from autoclip.utils import analysis_jobs

    now = _naive(now) or utcnow()
    out = {"sources_archived": 0, "clips_deleted": 0, "inactive_accounts": 0}
    db = SessionLocal()
    try:
        exempt = _exempt_ids(db)

        if settings.SOURCE_RETENTION_DAYS > 0:
            cutoff = now - timedelta(days=settings.SOURCE_RETENTION_DAYS)
            for v in (db.query(Video).filter(Video.archived.is_(False), Video.created_at < cutoff).all()):
                if v.user_id in exempt or analysis_jobs.is_running(v.id):
                    continue
                archive_source(db, v)
                out["sources_archived"] += 1

        if settings.CLIP_RETENTION_DAYS > 0:
            cutoff = now - timedelta(days=settings.CLIP_RETENTION_DAYS)
            old = (db.query(Clip).join(Video, Clip.video_id == Video.id)
                   .filter(Clip.created_at < cutoff).all())
            for c in old:
                if c.video.user_id in exempt:
                    continue
                delete_clip(db, c)
                out["clips_deleted"] += 1
            db.commit()

        if settings.INACTIVE_ACCOUNT_DAYS > 0:
            cutoff = now - timedelta(days=settings.INACTIVE_ACCOUNT_DAYS)
            seen = func.coalesce(User.last_active_at, User.created_at)
            for u in db.query(User).filter(seen < cutoff).all():
                if u.id in exempt:
                    continue
                vids = [r[0] for r in db.query(Video.id).filter(Video.user_id == u.id).all()]
                if any(analysis_jobs.is_running(v) for v in vids):
                    continue
                if not any(video_bytes(v) for v in vids):
                    continue   # nothing left to delete
                purge_user_files(db, u.id)
                out["inactive_accounts"] += 1
    finally:
        db.close()
    logger.info("storage cleanup: %s", out)
    return out


_LOCK_PREFIX = "cleanup:done:"
_mem_done: set[str] = set()


def _claim_today(day: str) -> bool:
    """Once per UTC day across workers/restarts: SET NX on a Redis key
    (in-process set without Redis)."""
    from autoclip.services.events import get_redis
    r = get_redis()
    if r is not None:
        try:
            return bool(r.set(_LOCK_PREFIX + day, str(time.time()), nx=True, ex=2 * 24 * 3600))
        except Exception:
            logger.warning("cleanup lock: redis unavailable, using in-process guard", exc_info=True)
    if day in _mem_done:
        return False
    _mem_done.add(day)
    return True


def _release_day(day: str) -> None:
    from autoclip.services.events import get_redis
    _mem_done.discard(day)
    r = get_redis()
    if r is not None:
        try:
            r.delete(_LOCK_PREFIX + day)
        except Exception:
            pass


async def cleanup_tick(now: Optional[datetime] = None) -> Optional[dict]:
    """Run the cleanup if it's past CLEANUP_HOUR_UTC and nobody ran it today."""
    now = _naive(now) or utcnow()
    if now.hour < settings.CLEANUP_HOUR_UTC:
        return None
    day = now.strftime("%Y-%m-%d")
    if not _claim_today(day):
        return None
    try:
        return await asyncio.to_thread(run_cleanup)
    except Exception:
        logger.exception("storage cleanup failed; will retry on the next tick")
        _release_day(day)
        return None


async def cleanup_loop() -> None:
    """Started from main.py's lifespan; cancelled on shutdown."""
    await asyncio.sleep(60)   # let the app finish starting
    while True:
        try:
            await cleanup_tick()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("cleanup loop tick failed")
        await asyncio.sleep(max(60, settings.CLEANUP_CHECK_SECONDS))
