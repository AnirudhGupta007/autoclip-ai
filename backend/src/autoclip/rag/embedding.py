"""LlamaIndex embedding wrapper around the OpenRouter embeddings call.

Reuses `services/embeddings.embed_text` verbatim (single source of truth
for the embedding model) rather than re-implementing embedding logic here —
this class just adapts that function to LlamaIndex's BaseEmbedding interface.
"""
from __future__ import annotations
from typing import Any

from llama_index.core.embeddings import BaseEmbedding

from autoclip.services.embeddings import embed_text
from autoclip.config import EMBEDDING_DIM


class AutoclipEmbedding(BaseEmbedding):
    """LlamaIndex-compatible wrapper around the local embedding model."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)

    @classmethod
    def class_name(cls) -> str:
        return "AutoclipEmbedding"

    def _get_query_embedding(self, query: str) -> list[float]:
        return embed_text(query) or [0.0] * EMBEDDING_DIM

    def _get_text_embedding(self, text: str) -> list[float]:
        return embed_text(text) or [0.0] * EMBEDDING_DIM

    async def _aget_query_embedding(self, query: str) -> list[float]:
        return self._get_query_embedding(query)

    async def _aget_text_embedding(self, text: str) -> list[float]:
        return self._get_text_embedding(text)
