"""Chat history: conversations and their messages (per user).

Ownership works like videos: a conversation id that isn't the caller's is
"not found" (404), never 403. The chat router persists every turn here; the
agent tools re-check the conversation in the run's thread id
(agent/tools._user_id), so a forged thread can't borrow someone's history.
"""
from __future__ import annotations
import logging
from datetime import timezone
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from autoclip.database import SessionLocal
from autoclip.models import Conversation, Message, Video, utcnow
from autoclip.utils.text import truncate_words

logger = logging.getLogger(__name__)

TITLE_MAX = 60
UNTITLED = {"", "new chat"}


def title_from_prompt(prompt: str) -> str:
    """Sidebar title: the first prompt, cut at a word boundary (no LLM call)."""
    return truncate_words(prompt, TITLE_MAX) or "New chat"


def iso(dt) -> Optional[str]:
    """ISO 8601 UTC with a trailing Z (the DB columns are naive UTC)."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def owned_conversation(db: Session, user_id: int, conversation_id: Optional[str]) -> Optional[Conversation]:
    if not conversation_id:
        return None
    return (db.query(Conversation)
            .filter(Conversation.id == str(conversation_id), Conversation.user_id == int(user_id))
            .first())


def get_owned_conversation(db: Session, user, conversation_id: str) -> Conversation:
    conv = owned_conversation(db, user.id, conversation_id)
    if conv is None:
        raise HTTPException(404, "Conversation not found")
    return conv


def user_owns_conversation(user_id: int, conversation_id: str) -> bool:
    db = SessionLocal()
    try:
        return owned_conversation(db, user_id, conversation_id) is not None
    finally:
        db.close()


def conversation_out(c: Conversation) -> dict:
    return {"id": c.id, "title": c.title or "", "video_id": c.video_id, "updated_at": iso(c.updated_at)}


def message_out(m: Message, live: dict[str, dict]) -> dict:
    clips = None
    if m.clips_json:
        clips = []
        for c in m.clips_json:
            cur = live.get(c.get("id")) if isinstance(c, dict) else None
            if cur is not None:
                clips.append(cur)
            elif isinstance(c, dict):
                # Deleted since (retention or the user): keep the record, drop the media.
                clips.append({**c, "file_url": None, "thumbnail_url": None})
    return {"id": m.id, "role": m.role, "content": m.content or "", "clips": clips,
            "created_at": iso(m.created_at)}


def list_messages(db: Session, user_id: int, conv: Conversation) -> list[dict]:
    """Messages oldest first; clips re-read from the DB so trims and
    expiries show up, falling back to the stored snapshot."""
    from autoclip.agent.tools import clips_by_ids

    rows = (db.query(Message).filter(Message.conversation_id == conv.id)
            .order_by(Message.id.asc()).all())
    ids = [c.get("id") for m in rows for c in (m.clips_json or []) if isinstance(c, dict) and c.get("id")]
    live = {c["id"]: c for c in clips_by_ids(list(dict.fromkeys(ids)), user_id)} if ids else {}
    return [message_out(m, live) for m in rows]


def record_turn(user_id: int, conversation_id: str, prompt: str, reply: str,
                clips: Optional[list[dict]] = None, video_id: Optional[str] = None,
                pending: bool = False) -> None:
    """Store one user prompt + assistant reply, bump updated_at, set the
    title from the first prompt. Own DB session: the chat router closes its
    request session before the agent runs.

    If the previous turn was the "analysing — I'll pick this up" reply to
    the same prompt, the automatic re-send is not stored twice."""
    db = SessionLocal()
    try:
        conv = owned_conversation(db, user_id, conversation_id)
        if conv is None:
            return
        last = (db.query(Message).filter(Message.conversation_id == conv.id)
                .order_by(Message.id.desc()).limit(2).all())
        resend = (len(last) == 2 and last[0].role == "assistant" and last[0].pending
                  and last[1].role == "user" and last[1].content == prompt)
        now = utcnow()
        if not resend:
            db.add(Message(conversation_id=conv.id, role="user", content=prompt, created_at=now))
        db.add(Message(conversation_id=conv.id, role="assistant", content=reply or "",
                       clips_json=list(clips) if clips else None, pending=pending, created_at=now))
        if (conv.title or "").strip().lower() in UNTITLED:
            conv.title = title_from_prompt(prompt)
        if video_id and db.query(Video.id).filter(Video.id == video_id, Video.user_id == user_id).first():
            conv.video_id = video_id
        conv.updated_at = now
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("could not store chat turn (conversation=%s)", conversation_id)
    finally:
        db.close()


def delete_user_conversations(db: Session, user_id: int) -> list[str]:
    """Remove a user's conversations + messages (no commit). Returns the ids."""
    ids = [r[0] for r in db.query(Conversation.id).filter(Conversation.user_id == user_id).all()]
    if ids:
        db.query(Message).filter(Message.conversation_id.in_(ids)).delete(synchronize_session=False)
        db.query(Conversation).filter(Conversation.id.in_(ids)).delete(synchronize_session=False)
    return ids


def forget_threads(thread_ids: list[str]) -> None:
    """Best-effort delete of LangGraph checkpoints for these threads."""
    if not thread_ids:
        return
    try:
        from autoclip.pipeline.graph import checkpointer
    except Exception:
        return
    for tid in thread_ids:
        try:
            checkpointer.delete_thread(tid)
        except Exception:
            logger.debug("checkpoint delete failed for %s", tid, exc_info=True)
