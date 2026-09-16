"""Semantic moment search router — backed by the shared RAG retriever
(autoclip.rag.retriever), the same code path the deep agent's
`search_moments` tool uses, so manual search and agent-driven search never
drift apart."""
from __future__ import annotations
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from autoclip.rag.retriever import retrieve_moments

router = APIRouter(prefix="/api", tags=["search"])


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
def search_moments(req: SearchRequest):
    moments = retrieve_moments(video_id=req.video_id, query=req.query, k=req.limit)
    return [
        SearchHit(
            video_id=req.video_id,
            start=m.start, end=m.end,
            description=m.description, transcript=m.transcript,
            style_tags=m.style_tags,
            convergence_score=m.convergence_score,
        )
        for m in moments
    ]
