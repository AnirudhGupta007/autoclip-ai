"""Semantic moment search router — backed by the shared RAG retriever
(autoclip.rag.retriever), the same code path the deep agent's
`search_moments` tool uses, so manual search and agent-driven search never
drift apart. Always scoped to the caller's own videos."""
from __future__ import annotations
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from autoclip.auth.deps import current_user, get_owned_video, user_video_ids
from autoclip.database import get_db
from autoclip.models import User
from autoclip.rag.retriever import retrieve_moments

router = APIRouter(prefix="/api", tags=["search"], dependencies=[Depends(current_user)])


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    video_id: Optional[str] = None
    limit: int = Field(default=10, ge=1, le=50)


class SearchHit(BaseModel):
    video_id: Optional[str] = None
    start: float
    end: float
    description: Optional[str]
    transcript: Optional[str]
    style_tags: list[str]
    convergence_score: float


@router.post("/search", response_model=list[SearchHit])
def search_moments(req: SearchRequest, db: Session = Depends(get_db),
                   user: User = Depends(current_user)):
    if req.video_id:
        get_owned_video(db, user, req.video_id)
        allowed = [req.video_id]
    else:
        allowed = user_video_ids(db, user.id)
    moments = retrieve_moments(video_id=req.video_id, query=req.query, k=req.limit, video_ids=allowed)
    return [
        SearchHit(
            video_id=getattr(m, "video_id", None) or req.video_id,
            start=m.start, end=m.end,
            description=m.description, transcript=m.transcript,
            style_tags=m.style_tags,
            convergence_score=m.convergence_score,
        )
        for m in moments
    ]
