"""FastAPI dependencies: the current user and ownership-checked lookups.

Every data endpoint goes through `current_user` (401 when not logged in) and
`get_owned_video` / `get_owned_clip`, which answer 404 — not 403 — for other
users' rows so ids can't be probed for existence.
"""
from __future__ import annotations
from datetime import timedelta
from typing import Optional

from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from autoclip.auth import settings
from autoclip.auth.security import token_hash
from autoclip.database import get_db
from autoclip.models import AuthSession, Clip, User, Video, utcnow

LEGACY_COOKIE_NAMES = ("__Host-session", "autoclip_session")


def session_token(request: Request) -> Optional[str]:
    tok = request.cookies.get(settings.COOKIE_NAME)
    if tok:
        return tok
    for name in LEGACY_COOKIE_NAMES:  # e.g. COOKIE_SECURE flipped since login
        if request.cookies.get(name):
            return request.cookies[name]
    return None


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        settings.COOKIE_NAME, token,
        max_age=settings.SESSION_DAYS * 24 * 3600,
        httponly=True, secure=settings.COOKIE_SECURE, samesite="lax", path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(settings.COOKIE_NAME, path="/", secure=settings.COOKIE_SECURE,
                           httponly=True, samesite="lax")


def user_from_token(db: Session, token: Optional[str]) -> tuple[Optional[User], Optional[AuthSession]]:
    if not token:
        return None, None
    sess = db.get(AuthSession, token_hash(token))
    if sess is None:
        return None, None
    if sess.expires_at <= utcnow():
        db.delete(sess)
        db.commit()
        return None, None
    return sess.user, sess


def optional_user(request: Request, response: Response, db: Session = Depends(get_db)) -> Optional[User]:
    token = session_token(request)
    user, sess = user_from_token(db, token)
    if user is None:
        return None
    # Sliding 30-day expiry, refreshed at most every few hours (one write).
    full = timedelta(days=settings.SESSION_DAYS)
    if sess.expires_at - utcnow() < full - timedelta(seconds=settings.SESSION_REFRESH_SECONDS):
        sess.expires_at = utcnow() + full
        db.commit()
        db.refresh(user)  # keep attributes loaded: routers may close the session early
        set_session_cookie(response, token)
    request.state.user_id = user.id
    return user


def current_user(user: Optional[User] = Depends(optional_user)) -> User:
    if user is None:
        raise HTTPException(401, "Not signed in", headers={"WWW-Authenticate": "Cookie"})
    return user


def require_admin(user: User = Depends(current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(403, "Admins only")
    return user


def require_not_demo(user: User = Depends(current_user)) -> User:
    if user.is_demo:
        raise HTTPException(403, "The demo account is read-only — sign up to upload or delete videos.")
    return user


# ─── ownership ──────────────────────────────────────────────────

def owned_video(db: Session, user_id: int, video_id: Optional[str]) -> Optional[Video]:
    if not video_id:
        return None
    return db.query(Video).filter(Video.id == video_id, Video.user_id == user_id).first()


def owned_clip(db: Session, user_id: int, clip_id: Optional[str]) -> Optional[Clip]:
    if not clip_id:
        return None
    return (db.query(Clip).join(Video, Clip.video_id == Video.id)
            .filter(Clip.id == clip_id, Video.user_id == user_id).first())


def get_owned_video(db: Session, user: User, video_id: str) -> Video:
    video = owned_video(db, user.id, video_id)
    if video is None:
        raise HTTPException(404, "Video not found")
    return video


def get_owned_clip(db: Session, user: User, clip_id: str) -> Clip:
    clip = owned_clip(db, user.id, clip_id)
    if clip is None:
        raise HTTPException(404, "Clip not found")
    return clip


def user_video_ids(db: Session, user_id: int) -> list[str]:
    return [r[0] for r in db.query(Video.id).filter(Video.user_id == user_id).all()]
