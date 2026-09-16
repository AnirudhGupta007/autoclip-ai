"""RAG retrieval over the moment index — backs both clip_selector and /api/search.

No cross-encoder reranker (keeps deps light — no extra cross-encoder
model beyond the embedding model already loaded): vector search +
metadata filtering gets ~k candidates, and the caller's own LLM step
(clip_selector's critique/title call, or a human reading /api/search
results) does the final semantic judgment on that small candidate set.
"""
from __future__ import annotations
import logging

from llama_index.core.vector_stores.types import (
    MetadataFilters, MetadataFilter, FilterOperator,
)

from autoclip.rag.index import get_moment_index
from autoclip.pipeline.state import Moment

logger = logging.getLogger(__name__)


def _overlaps(start: float, end: float, ranges: list[tuple]) -> bool:
    return any(start < r_end and end > r_start for r_start, r_end in ranges)


def _node_to_moment(node_with_score) -> Moment:
    md = node_with_score.node.metadata
    return Moment(
        start=float(md.get("start", 0.0)),
        end=float(md.get("end", 0.0)),
        visual_energy=float(md.get("visual_energy", 0.0)),
        audio_energy=float(md.get("audio_energy", 0.0)),
        text_hook_strength=float(md.get("text_hook_strength", 0.0)),
        convergence_score=float(md.get("convergence_score", 0.0)),
        modalities_active=sum(
            1 for v in (md.get("visual_energy", 0), md.get("audio_energy", 0), md.get("text_hook_strength", 0))
            if v > 0.4
        ),
        style_tags=list(md.get("style_tags", [])),
        description=md.get("description", "") or "",
        transcript=md.get("transcript", "") or "",
    )


def retrieve_moments(
    video_id: str | None,
    query: str,
    k: int = 10,
    min_convergence: float = 0.0,
    exclude_ranges: tuple = (),
) -> list[Moment]:
    """Semantic search over moments, optionally scoped to one video.

    `video_id=None` searches across the whole library (used by /api/search
    when no video is specified).
    """
    filters_list = []
    if video_id:
        filters_list.append(MetadataFilter(key="video_id", value=video_id, operator=FilterOperator.EQ))
    if min_convergence > 0:
        filters_list.append(MetadataFilter(key="convergence_score", value=min_convergence, operator=FilterOperator.GTE))
    filters = MetadataFilters(filters=filters_list) if filters_list else None

    try:
        index = get_moment_index()
        retriever = index.as_retriever(similarity_top_k=max(k * 2, k), filters=filters)
        hits = retriever.retrieve(query or "interesting moment")
    except Exception as e:
        logger.warning("retrieve_moments failed (video_id=%s query=%r): %s", video_id, query, e)
        return []

    moments: list[Moment] = []
    for h in hits:
        m = _node_to_moment(h)
        if exclude_ranges and _overlaps(m.start, m.end, list(exclude_ranges)):
            continue
        moments.append(m)
        if len(moments) >= k:
            break
    return moments
