"""/api/conversations — the Studio's chat history (frontend/API_CONTRACT.md).

Scoped to the signed-in user: another user's id is a 404. The shared demo
account is read-only and has no history of its own (every demo visitor is
the same user, so a list would leak one visitor's chats to the next): its
list is empty and create/rename/delete answer 403. The UI then chats
without a conversation id, exactly as before.
"""
from __future__ import annotations
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from autoclip.auth.deps import current_user, owned_video, require_not_demo
from autoclip.database import get_db
from autoclip.models import Conversation, Message, User, utcnow
from autoclip.services import conversations as C

router = APIRouter(prefix="/api/conversations", tags=["conversations"],
                   dependencies=[Depends(current_user)])

DEMO_READ_ONLY = "The demo account is read-only — sign up to keep your chat history."


class ConversationCreate(BaseModel):
    video_id: Optional[str] = None


class ConversationRename(BaseModel):
    title: str = Field(max_length=200)

    @field_validator("title")
    @classmethod
    def _clean(cls, v: str) -> str:
        v = " ".join(v.split())
        if not v:
            raise ValueError("Title cannot be empty")
        return v


@router.get("")
def list_conversations(user: User = Depends(current_user), db: Session = Depends(get_db)):
    if user.is_demo:
        return []
    rows = (db.query(Conversation).filter(Conversation.user_id == user.id)
            .order_by(Conversation.updated_at.desc(), Conversation.created_at.desc()).all())
    return [C.conversation_out(c) for c in rows]


@router.post("", status_code=201)
def create_conversation(body: Optional[ConversationCreate] = None, user: User = Depends(current_user),
                        db: Session = Depends(get_db)):
    if user.is_demo:
        raise HTTPException(403, DEMO_READ_ONLY)
    video_id = body.video_id if body else None
    if video_id and owned_video(db, user.id, video_id) is None:
        raise HTTPException(404, "Video not found")
    now = utcnow()
    conv = Conversation(user_id=user.id, video_id=video_id, title="", created_at=now, updated_at=now)
    db.add(conv)
    db.commit()
    db.refresh(conv)
    return C.conversation_out(conv)


@router.get("/{conversation_id}/messages")
def get_messages(conversation_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    conv = C.get_owned_conversation(db, user, conversation_id)
    return C.list_messages(db, user.id, conv)


@router.patch("/{conversation_id}")
def rename_conversation(conversation_id: str, body: ConversationRename,
                        user: User = Depends(require_not_demo), db: Session = Depends(get_db)):
    conv = C.get_owned_conversation(db, user, conversation_id)
    conv.title = body.title
    db.commit()
    db.refresh(conv)
    return C.conversation_out(conv)


@router.delete("/{conversation_id}", status_code=204)
def delete_conversation(conversation_id: str, user: User = Depends(require_not_demo),
                        db: Session = Depends(get_db)):
    from autoclip.routers.chat import chat_thread_id

    conv = C.get_owned_conversation(db, user, conversation_id)
    db.query(Message).filter(Message.conversation_id == conv.id).delete(synchronize_session=False)
    db.delete(conv)
    db.commit()
    C.forget_threads([chat_thread_id(user.id, None, conversation_id)])
    return Response(status_code=204)
