from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence

from config.settings import settings
from src.core.knowledge.document_models import TranscriptChunk
from src.core.knowledge.llamaindex_embedding import build_sentence_transformer_embedding


def build_llama_document(chunk: TranscriptChunk, *, document_cls: type[Any] | None = None) -> Any:
    cls = document_cls or _load_document_class()
    return cls(
        text=chunk.content,
        doc_id=chunk.doc_id,
        metadata=chunk.to_metadata(),
    )


def build_llama_documents(
    chunks: Sequence[TranscriptChunk],
    *,
    document_cls: type[Any] | None = None,
) -> list[Any]:
    return [build_llama_document(chunk, document_cls=document_cls) for chunk in chunks]


def build_default_embed_model(
    model_name: str | Path | None = None,
    *,
    normalize: bool = True,
    embed_batch_size: int = 32,
) -> Any:
    return build_sentence_transformer_embedding(
        model_name=model_name or settings.RAG_EMBED_MODEL_NAME,
        normalize_embeddings=normalize,
        embed_batch_size=embed_batch_size,
    )


def _load_document_class() -> type[Any]:
    try:
        from llama_index.core import Document
    except ImportError as exc:
        raise ImportError(
            "llama-index is required to build Document objects. Install llama-index-core."
        ) from exc
    return Document
