"""/api/auth — signup, login, logout, me, demo.

Opaque random session token in an httpOnly cookie; only sha256(token) is
stored (`sessions` table). Errors for bad credentials are deliberately
generic so the endpoints can't be used to discover which emails exist.
"""
from __future__ import annotations
import re
from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from autoclip.auth import settings
from autoclip.auth.deps import (
    clear_session_cookie, current_user, session_token, set_session_cookie,
)
from autoclip.auth.security import (
    hash_password, has_usable_password, new_session_token, token_hash, verify_password,
)
from autoclip.database import get_db
from autoclip.models import AuthSession, User, Video, utcnow
from autoclip.services import rate_limit

router = APIRouter(prefix="/api/auth", tags=["auth"])

BAD_CREDENTIALS = "Incorrect email or password."
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class Credentials(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(max_length=1024)

    @field_validator("email")
    @classmethod
    def _norm_email(cls, v: str) -> str:
        return v.strip().lower()


class SignupRequest(Credentials):
    @field_validator("email")
    @classmethod
    def _valid_email(cls, v: str) -> str:
        if not _EMAIL_RE.match(v):
            raise ValueError("Enter a valid email address")
        return v

    @field_validator("password")
    @classmethod
    def _strong_enough(cls, v: str) -> str:
        if len(v) < settings.PASSWORD_MIN_LENGTH:
            raise ValueError(f"Password must be at least {settings.PASSWORD_MIN_LENGTH} characters")
        return v


class UserOut(BaseModel):
    id: int
    email: str
    is_admin: bool
    is_demo: bool
    video_count: int = 0
    max_videos: Optional[int] = None
    max_video_minutes: Optional[int] = None
    queries_remaining: Optional[int] = None
    query_limit: Optional[int] = None


def user_out(db: Session, user: User) -> UserOut:
    count = db.query(Video).filter(Video.user_id == user.id).count()
    limited = not user.is_admin
    return UserOut(
        id=user.id, email=user.email, is_admin=bool(user.is_admin), is_demo=bool(user.is_demo),
        video_count=count,
        max_videos=settings.MAX_VIDEOS_PER_USER if limited and not user.is_demo else None,
        max_video_minutes=settings.MAX_VIDEO_MINUTES_DEMO if limited and not user.is_demo else None,
        queries_remaining=rate_limit.remaining(user),
        query_limit=rate_limit.chat_limit(user),
    )


def _start_session(db: Session, response: Response, user: User) -> None:
    token = new_session_token()
    db.add(AuthSession(token_hash=token_hash(token), user_id=user.id,
                       expires_at=utcnow() + timedelta(days=settings.SESSION_DAYS)))
    db.commit()
    set_session_cookie(response, token)


def _too_many(msg: str) -> HTTPException:
    return HTTPException(429, msg)


@router.post("/signup", response_model=UserOut, status_code=201)
def signup(body: SignupRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    ip = rate_limit.client_ip(request)
    if not rate_limit.hit("signup", ip, settings.SIGNUP_LIMIT_PER_IP_PER_DAY, 24 * 3600):
        raise _too_many("Too many sign-ups from this network today. Try again tomorrow.")
    if body.email == settings.DEMO_EMAIL:
        raise HTTPException(400, "That email can't be used.")

    is_admin = body.email in settings.ADMIN_EMAILS
    existing = db.query(User).filter(User.email == body.email).first()
    if existing is not None:
        # The only account that can be "claimed" is the passwordless legacy
        # owner created by migration 0002 for an ADMIN_EMAILS address.
        if is_admin and not existing.is_demo and not has_usable_password(existing.password_hash):
            existing.password_hash = hash_password(body.password)
            existing.is_admin = True
            db.commit()
            _start_session(db, response, existing)
            response.status_code = 201
            return user_out(db, existing)
        raise HTTPException(409, "An account with that email already exists. Try signing in.")

    user = User(email=body.email, password_hash=hash_password(body.password),
                is_admin=is_admin, is_demo=False)
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "An account with that email already exists. Try signing in.")
    db.refresh(user)
    _start_session(db, response, user)
    return user_out(db, user)


@router.post("/login", response_model=UserOut)
def login(body: Credentials, request: Request, response: Response, db: Session = Depends(get_db)):
    ip = rate_limit.client_ip(request)
    if not rate_limit.hit("login", f"{ip}:{body.email}", settings.LOGIN_LIMIT_PER_15_MIN, 15 * 60):
        raise _too_many("Too many sign-in attempts. Wait 15 minutes and try again.")
    user = db.query(User).filter(User.email == body.email).first()
    if not verify_password(user.password_hash if user else None, body.password) or user.is_demo:
        raise HTTPException(401, BAD_CREDENTIALS)
    if body.email in settings.ADMIN_EMAILS and not user.is_admin:
        user.is_admin = True
        db.commit()
    _start_session(db, response, user)
    return user_out(db, user)


@router.post("/demo", response_model=UserOut)
def demo_login(request: Request, response: Response, db: Session = Depends(get_db)):
    """Log into the shared, read-only demo account (see scripts/seed_demo.py)."""
    user = db.query(User).filter(User.email == settings.DEMO_EMAIL, User.is_demo.is_(True)).first()
    if not settings.DEMO_ENABLED or user is None:
        raise HTTPException(404, "The demo isn't available right now.")
    ip = rate_limit.client_ip(request)
    if not rate_limit.hit("demo", ip, settings.DEMO_LOGIN_LIMIT_PER_IP_PER_DAY, 24 * 3600):
        raise _too_many("Too many demo sessions from this network today.")
    _start_session(db, response, user)
    return user_out(db, user)


@router.post("/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    token = session_token(request)
    if token:
        db.query(AuthSession).filter(AuthSession.token_hash == token_hash(token)).delete()
        db.commit()
    clear_session_cookie(response)
    return {"ok": True}


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return user_out(db, user)
