from __future__ import annotations

import logging
from typing import Any, Mapping, Protocol, Sequence

from src.core.knowledge.document_models import TranscriptRecord
from src.core.knowledge.query_filters import MetadataFilterClause, MetadataFilterSpec
from src.domain.session import RealtimeSession

logger = logging.getLogger(__name__)


class TranscriptWriter(Protocol):
    def append_realtime_transcript(self, session: RealtimeSession, text: str): ...

    def append_transcript_record(self, record: Mapping[str, Any]) -> int: ...

    def next_chunk_id(self, session_id: str) -> int: ...

    def list_session_transcripts(
        self,
        session: RealtimeSession | None,
        session_id: str,
        *,
        prefer_final: bool = True,
    ): ...

    def release_session(self, session_id: str) -> None: ...


class RealtimeRecordIndexer(Protocol):
    def append_record(self, session: RealtimeSession, record_payload: Mapping[str, Any] | TranscriptRecord) -> None: ...

    def flush_session(self, session_id: str) -> None: ...


class KnowledgeIngestionService:
    """Unified SQL + RAG ingestion entry point for lesson knowledge records."""

    def __init__(
        self,
        *,
        transcript_writer: TranscriptWriter,
        realtime_indexer: RealtimeRecordIndexer | None = None,
        runtime_factory=None,
        rag_indexing_enabled: bool = True,
    ) -> None:
        self.transcript_writer = transcript_writer
        self.realtime_indexer = realtime_indexer
        self.runtime_factory = runtime_factory
        self.rag_indexing_enabled = rag_indexing_enabled

    def append_realtime_transcript(self, session: RealtimeSession, text: str):
        record = self.transcript_writer.append_realtime_transcript(session, text)
        if record is not None:
            self.enqueue_realtime_record(session, record)
        return record

    def persist_record(self, record: Mapping[str, Any]) -> int:
        return self.transcript_writer.append_transcript_record(record)

    def persist_records(self, records: Sequence[Mapping[str, Any]]) -> list[int]:
        return [self.persist_record(record) for record in records]

    def persist_and_enqueue_realtime_record(
        self,
        session: RealtimeSession,
        record: Mapping[str, Any],
    ) -> int:
        record_id = self.persist_record(record)
        self.enqueue_realtime_record(session, record)
        return record_id

    def persist_and_index_records(self, records: Sequence[Mapping[str, Any]]):
        self.persist_records(records)
        return self.index_records_immediately(records)

    def enqueue_realtime_record(
        self,
        session: RealtimeSession,
        record: Mapping[str, Any] | TranscriptRecord,
    ) -> None:
        if self.realtime_indexer is None:
            return
        self.realtime_indexer.append_record(session, record)

    def flush_session(self, session_id: str) -> None:
        if self.realtime_indexer is None:
            return
        flush_session = getattr(self.realtime_indexer, "flush_session", None)
        if callable(flush_session):
            flush_session(session_id)

    def release_session(self, session_id: str) -> None:
        release_session = getattr(self.transcript_writer, "release_session", None)
        if callable(release_session):
            release_session(session_id)

    def next_chunk_id(self, session_id: str) -> int:
        return self.transcript_writer.next_chunk_id(session_id)

    def index_records_immediately(self, records: Sequence[Mapping[str, Any] | TranscriptRecord]):
        if not self.rag_indexing_enabled or not records:
            return None
        runtime = self._get_runtime()
        transcript_records = self._to_transcript_records(records)
        if not transcript_records:
            return None
        return runtime.indexing_service.index_records(
            transcript_records,
            embed_model=runtime.embed_model,
        )

    def rebuild_session_index(self, session_id: str, *, prefer_final: bool = True):
        if not self.rag_indexing_enabled:
            return None
        runtime = self._get_runtime()
        payloads = self.transcript_writer.list_session_transcripts(
            None,
            session_id,
            prefer_final=prefer_final,
        )
        records = self._to_transcript_records(
            payload
            for payload in payloads
            if str(payload.get("clean_text") or payload.get("text") or "").strip()
        )
        if not records:
            return None

        runtime.index_store.delete_by_metadata(
            MetadataFilterSpec(
                clauses=(MetadataFilterClause("session_id", session_id),),
            )
        )
        return runtime.indexing_service.index_records(
            records,
            embed_model=runtime.embed_model,
        )

    def _get_runtime(self):
        if self.runtime_factory is None:
            raise ValueError("runtime_factory is required for direct RAG indexing")
        return self.runtime_factory()

    @staticmethod
    def _to_transcript_records(
        records: Sequence[Mapping[str, Any] | TranscriptRecord] | Any,
    ) -> list[TranscriptRecord]:
        normalized: list[TranscriptRecord] = []
        for record in records:
            normalized.append(
                record if isinstance(record, TranscriptRecord) else TranscriptRecord.from_dict(record)
            )
        return normalized
