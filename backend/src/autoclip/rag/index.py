"""Moment indexing — turns Moment dataclasses into LlamaIndex nodes."""
from __future__ import annotations
import logging
from functools import lru_cache

from llama_index.core import VectorStoreIndex, StorageContext
from llama_index.core.schema import TextNode

from autoclip.rag.store import get_vector_store
from autoclip.rag.embedding import AutoclipEmbedding
from autoclip.pipeline.state import Moment

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_moment_index() -> VectorStoreIndex:
    """The single library-wide index — every video's moments live here,
    scoped at query time via a `video_id` metadata filter (see retriever.py)."""
    storage_context = StorageContext.from_defaults(vector_store=get_vector_store())
    return VectorStoreIndex(
        nodes=[],
        storage_context=storage_context,
        embed_model=AutoclipEmbedding(),
    )


def _moment_to_node(video_id: str, moment: Moment, node_id: str) -> TextNode:
    text = (moment.transcript or moment.description or "").strip()
    return TextNode(
        id_=node_id,
        text=text or moment.description,
        embedding=moment.embedding,
        metadata={
            "video_id": video_id,
            "start": moment.start,
            "end": moment.end,
            "description": moment.description,
            "transcript": moment.transcript,
            "style_tags": list(moment.style_tags),
            "convergence_score": moment.convergence_score,
            "visual_energy": moment.visual_energy,
            "audio_energy": moment.audio_energy,
            "text_hook_strength": moment.text_hook_strength,
        },
    )


def index_moments(video_id: str, moments: list[Moment]) -> int:
    """Add this video's moments to the RAG index. Best-effort — a RAG indexing
    failure must never break the analysis pipeline (fusion/persist already
    succeeded by the time this runs)."""
    if not moments:
        return 0
    try:
        index = get_moment_index()
        nodes = [
            _moment_to_node(video_id, m, node_id=f"{video_id}:{i}")
            for i, m in enumerate(moments)
        ]
        index.insert_nodes(nodes)
        logger.info("rag.index_moments: indexed %d moments for video=%s", len(nodes), video_id)
        return len(nodes)
    except Exception as e:
        logger.warning("rag.index_moments failed for video=%s: %s", video_id, e)
        return 0
