from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence

from config.settings import settings
from src.core.knowledge.document_models import TranscriptChunk
from src.core.knowledge.llamaindex_embedding import build_sentence_transformer_embedding


_VECTOR_METADATA_KEYS = (
    "doc_id",
    "session_id",
    "subject",
    "source_type",
    "created_at",
    "first_chunk_id",
    "last_chunk_id",
    "record_count",
    "storage_id",
    "course_id",
    "lesson_id",
    "source_file",
    "start_ms",
    "end_ms",
    "segment_count",
    "parser",
    "transcript_role",
    "video_id",
    "asset_id",
    "media_type",
    "mineru_parser",
    "page_idx",
    "page_no",
    "first_page_no",
    "last_page_no",
    "region",
)


def build_llama_document(chunk: TranscriptChunk, *, document_cls: type[Any] | None = None) -> Any:
    cls = document_cls or _load_document_class()
    return cls(
        text=chunk.content,
        doc_id=chunk.doc_id,
        metadata=build_vector_metadata(chunk),
    )


def build_llama_documents(
    chunks: Sequence[TranscriptChunk],
    *,
    document_cls: type[Any] | None = None,
) -> list[Any]:
    return [build_llama_document(chunk, document_cls=document_cls) for chunk in chunks]


def build_vector_metadata(chunk: TranscriptChunk) -> dict[str, object]:
    source = chunk.to_metadata()
    metadata: dict[str, object] = {}
    for key in _VECTOR_METADATA_KEYS:
        if key not in source:
            continue
        value = source[key]
        if _is_vector_metadata_value(value):
            metadata[key] = value
    return metadata


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


def _is_vector_metadata_value(value: object) -> bool:
    return isinstance(value, (str, int, float, bool))


def _load_document_class() -> type[Any]:
    try:
        from llama_index.core import Document
    except ImportError as exc:
        raise ImportError(
            "llama-index is required to build Document objects. Install llama-index-core."
        ) from exc
    return Document
