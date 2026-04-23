from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence

from config.settings import settings
from src.core.knowledge.chunker import build_chunks, load_records_from_dir, load_transcript_records
from src.core.knowledge.document_models import ChunkingOptions, TranscriptChunk, TranscriptRecord
from src.core.knowledge.llamaindex_builder import build_llama_documents
from src.infrastructure.storage.qdrant_index_store import QdrantIndexStore


@dataclass(slots=True)
class RagIndexingSummary:
    record_count: int
    chunk_count: int
    document_count: int
    session_count: int
    session_ids: tuple[str, ...]
    index: Any | None = None


class RagIndexingService:
    def __init__(
        self,
        *,
        index_store: Any | None = None,
        chunk_options: ChunkingOptions | None = None,
        document_builder: Callable[[Sequence[TranscriptChunk]], list[Any]] = build_llama_documents,
        transcript_root: Path | None = None,
    ) -> None:
        self.index_store = index_store or QdrantIndexStore()
        self.chunk_options = chunk_options or ChunkingOptions()
        self.document_builder = document_builder
        self.transcript_root = transcript_root or settings.TRANSCRIPT_SAVE_DIR

    def load_records(self, path: Path | None = None) -> list[TranscriptRecord]:
        target = Path(path or self.transcript_root)
        if target.is_dir():
            return load_records_from_dir(target)
        return load_transcript_records(target)

    def build_chunks(
        self,
        records: Sequence[TranscriptRecord],
        *,
        chunk_options: ChunkingOptions | None = None,
    ) -> list[TranscriptChunk]:
        return build_chunks(records, chunk_options or self.chunk_options)

    def index_records(
        self,
        records: Sequence[TranscriptRecord],
        *,
        chunk_options: ChunkingOptions | None = None,
        embed_model: Any = None,
        transformations: Sequence[Any] | None = None,
        show_progress: bool = False,
        recreate_if_mismatch: bool = False,
    ) -> RagIndexingSummary:
        chunks = self.build_chunks(records, chunk_options=chunk_options)
        documents = self.document_builder(chunks)
        index = self.index_store.create_index(
            documents,
            embed_model=embed_model,
            transformations=transformations,
            show_progress=show_progress,
            recreate_if_mismatch=recreate_if_mismatch,
        )
        session_ids = tuple(sorted({record.session_id for record in records}))
        return RagIndexingSummary(
            record_count=len(records),
            chunk_count=len(chunks),
            document_count=len(documents),
            session_count=len(session_ids),
            session_ids=session_ids,
            index=index,
        )

    def index_path(
        self,
        path: Path | None = None,
        *,
        chunk_options: ChunkingOptions | None = None,
        embed_model: Any = None,
        transformations: Sequence[Any] | None = None,
        show_progress: bool = False,
        recreate_if_mismatch: bool = False,
    ) -> RagIndexingSummary:
        records = self.load_records(path)
        return self.index_records(
            records,
            chunk_options=chunk_options,
            embed_model=embed_model,
            transformations=transformations,
            show_progress=show_progress,
            recreate_if_mismatch=recreate_if_mismatch,
        )


rag_indexing_service = RagIndexingService()
