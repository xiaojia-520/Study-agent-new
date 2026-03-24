from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Sequence

from pydantic import Field, PrivateAttr
from sentence_transformers import SentenceTransformer

from config.settings import settings


def _load_base_embedding():
    try:
        from llama_index.core.base.embeddings.base import BaseEmbedding
    except ImportError as exc:
        raise ImportError(
            "llama-index-core is required for SentenceTransformerEmbedding."
        ) from exc
    return BaseEmbedding


class SentenceTransformerEmbedding(_load_base_embedding()):
    normalize_embeddings: bool = Field(default=True)
    show_progress_bar: bool = Field(default=False)
    device: str | None = Field(default=None)
    _model: SentenceTransformer = PrivateAttr()

    def __init__(
        self,
        model_name: str | Path | None = None,
        *,
        normalize_embeddings: bool = True,
        show_progress_bar: bool = False,
        device: str | None = None,
        embed_batch_size: int = 32,
        **kwargs: Any,
    ) -> None:
        resolved_model_name = str(model_name or settings.RAG_EMBED_MODEL_NAME)
        super().__init__(
            model_name=resolved_model_name,
            embed_batch_size=embed_batch_size,
            normalize_embeddings=normalize_embeddings,
            show_progress_bar=show_progress_bar,
            device=device,
            **kwargs,
        )
        self._model = SentenceTransformer(resolved_model_name, device=device)

    @classmethod
    def class_name(cls) -> str:
        return "sentence_transformer_embedding"

    def _get_query_embedding(self, query: str) -> list[float]:
        return self._encode_one(query)

    async def _aget_query_embedding(self, query: str) -> list[float]:
        return await asyncio.to_thread(self._encode_one, query)

    def _get_text_embedding(self, text: str) -> list[float]:
        return self._encode_one(text)

    def _get_text_embeddings(self, texts: Sequence[str]) -> list[list[float]]:
        return self._encode_many(texts)

    async def _aget_text_embedding(self, text: str) -> list[float]:
        return await asyncio.to_thread(self._encode_one, text)

    async def _aget_text_embeddings(self, texts: Sequence[str]) -> list[list[float]]:
        return await asyncio.to_thread(self._encode_many, texts)

    def _encode_one(self, text: str) -> list[float]:
        values = self._encode_many([text])
        return values[0] if values else []

    def _encode_many(self, texts: Sequence[str]) -> list[list[float]]:
        materialized = [str(text) for text in texts]
        if not materialized:
            return []
        vectors = self._model.encode(
            materialized,
            batch_size=self.embed_batch_size,
            show_progress_bar=self.show_progress_bar,
            convert_to_numpy=True,
            normalize_embeddings=self.normalize_embeddings,
            device=self.device,
        )
        return vectors.tolist()

    def get_vector_dimension(self) -> int:
        dimension = self._model.get_sentence_embedding_dimension()
        if dimension is None:
            raise ValueError("unable to determine embedding dimension from the sentence transformer model")
        return int(dimension)


def build_sentence_transformer_embedding(
    model_name: str | Path | None = None,
    *,
    normalize_embeddings: bool = True,
    show_progress_bar: bool = False,
    device: str | None = None,
    embed_batch_size: int = 32,
    **kwargs: Any,
) -> SentenceTransformerEmbedding:
    return SentenceTransformerEmbedding(
        model_name=model_name,
        normalize_embeddings=normalize_embeddings,
        show_progress_bar=show_progress_bar,
        device=device,
        embed_batch_size=embed_batch_size,
        **kwargs,
    )
