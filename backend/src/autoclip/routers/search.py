"""Semantic moment search router (Phase 2.5)."""
from __future__ import annotations
import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from autoclip.database import get_db
from autoclip.config import DATABASE_URL
from autoclip.models import MomentRecord
from autoclip.services.embeddings import embed_text, _cosine

router = APIRouter(prefix="/api", tags=["search"])

USE_PGVECTOR = DATABASE_URL.startswith("postgres") and os.getenv("USE_PGVECTOR", "1") != "0"


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    video_id: Optional[str] = None
    limit: int = Field(default=10, ge=1, le=50)


class SearchHit(BaseModel):
    id: str
    video_id: str
    start: float
    end: float
    description: Optional[str]
    transcript: Optional[str]
    style_tags: list[str]
    convergence_score: float
    similarity: float


@router.post("/search", response_model=list[SearchHit])
def search_moments(req: SearchRequest, db: Session = Depends(get_db)):
    """Semantic search over moments using embeddings + cosine similarity.

    On Postgres+pgvector: ORDER BY embedding <=> query (HNSW-friendly).
    On SQLite: fetch + cosine in Python (fine up to a few thousand moments).
    """
    qvec = embed_text(req.query)
    if qvec is None:
        raise HTTPException(status_code=503, detail="Embedding service unavailable")

    if USE_PGVECTOR:
        sql = text(
            """
            SELECT id, video_id, start, "end", description, transcript,
                   style_tags, convergence_score,
                   1 - (embedding <=> CAST(:q AS vector)) AS similarity
            FROM moments
            WHERE embedding IS NOT NULL
              AND (:video_id IS NULL OR video_id = :video_id)
            ORDER BY embedding <=> CAST(:q AS vector)
            LIMIT :lim
            """
        )
        rows = db.execute(sql, {"q": qvec, "video_id": req.video_id, "lim": req.limit}).mappings().all()
        return [SearchHit(**dict(r)) for r in rows]

    q = db.query(MomentRecord)
    if req.video_id:
        q = q.filter(MomentRecord.video_id == req.video_id)
    rows = q.all()
    scored: list[tuple[float, MomentRecord]] = []
    for m in rows:
        if not m.embedding:
            continue
        scored.append((_cosine(qvec, list(m.embedding)), m))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [
        SearchHit(
            id=m.id, video_id=m.video_id, start=m.start, end=m.end,
            description=m.description, transcript=m.transcript,
            style_tags=list(m.style_tags or []),
            convergence_score=float(m.convergence_score or 0.0),
            similarity=float(sim),
        )
        for sim, m in scored[: req.limit]
    ]
