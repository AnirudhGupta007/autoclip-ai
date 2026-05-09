"""Persistence helpers for analyzed moments."""
from __future__ import annotations
import logging
from sqlalchemy.orm import Session
from autoclip.models import MomentRecord, generate_id
from autoclip.pipeline.state import Moment

logger = logging.getLogger(__name__)


def persist_moments(db: Session, video_id: str, moments: list[Moment]) -> int:
    """Replace any existing moments for `video_id` with the given list."""
    db.query(MomentRecord).filter(MomentRecord.video_id == video_id).delete()
    n = 0
    for m in moments:
        db.add(MomentRecord(
            id=generate_id(),
            video_id=video_id,
            start=float(m.start),
            end=float(m.end),
            description=m.description,
            transcript=m.transcript,
            style_tags=list(m.style_tags),
            visual_energy=float(m.visual_energy),
            audio_energy=float(m.audio_energy),
            text_hook_strength=float(m.text_hook_strength),
            convergence_score=float(m.convergence_score),
            modalities_active=int(m.modalities_active),
            embedding=list(m.embedding) if m.embedding else None,
        ))
        n += 1
    db.commit()
    logger.info("persist_moments: stored %d moments for video=%s", n, video_id)
    return n
