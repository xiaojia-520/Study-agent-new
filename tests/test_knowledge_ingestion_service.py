import unittest
from types import SimpleNamespace

from src.application.rag.ingestion_service import KnowledgeIngestionService
from src.domain.session import RealtimeSession


class FakeTranscriptWriter:
    def __init__(self) -> None:
        self.persisted = []
        self.released = []
        self.session_records = []

    def append_realtime_transcript(self, session: RealtimeSession, text: str):
        record = _record(session.session_id, 1, text)
        self.persisted.append(record)
        return record

    def append_transcript_record(self, record):
        self.persisted.append(dict(record))
        return len(self.persisted)

    def next_chunk_id(self, session_id: str) -> int:
        return len(self.persisted) + 1

    def list_session_transcripts(self, session, session_id: str, *, prefer_final: bool = True):
        return list(self.session_records)

    def release_session(self, session_id: str) -> None:
        self.released.append(session_id)


class FakeRealtimeIndexer:
    def __init__(self) -> None:
        self.enqueued = []
        self.flushed = []

    def append_record(self, session, record):
        self.enqueued.append((session, record))

    def flush_session(self, session_id: str) -> None:
        self.flushed.append(session_id)


class FakeIndexStore:
    def __init__(self) -> None:
        self.deleted_filters = []

    def delete_by_metadata(self, filters):
        self.deleted_filters.append(filters)


class FakeIndexingService:
    def __init__(self) -> None:
        self.indexed = []

    def index_records(self, records, **kwargs):
        self.indexed.append((list(records), kwargs))
        return SimpleNamespace(record_count=len(records))


class FakeRuntime:
    def __init__(self) -> None:
        self.index_store = FakeIndexStore()
        self.indexing_service = FakeIndexingService()
        self.embed_model = object()


class KnowledgeIngestionServiceTests(unittest.TestCase):
    def test_append_realtime_transcript_persists_and_enqueues(self) -> None:
        writer = FakeTranscriptWriter()
        indexer = FakeRealtimeIndexer()
        service = KnowledgeIngestionService(transcript_writer=writer, realtime_indexer=indexer)
        session = _session("session-a")

        record = service.append_realtime_transcript(session, "hello")

        self.assertEqual(record["clean_text"], "hello")
        self.assertEqual(writer.persisted[0]["clean_text"], "hello")
        self.assertEqual(indexer.enqueued, [(session, record)])

    def test_persist_and_index_records_uses_runtime_indexer(self) -> None:
        writer = FakeTranscriptWriter()
        runtime = FakeRuntime()
        service = KnowledgeIngestionService(
            transcript_writer=writer,
            runtime_factory=lambda: runtime,
        )

        service.persist_and_index_records([_record("session-a", 1, "alpha")])

        self.assertEqual(len(writer.persisted), 1)
        indexed_records, kwargs = runtime.indexing_service.indexed[0]
        self.assertEqual([record.content for record in indexed_records], ["alpha"])
        self.assertIs(kwargs["embed_model"], runtime.embed_model)

    def test_rebuild_session_index_replaces_session_vectors(self) -> None:
        writer = FakeTranscriptWriter()
        writer.session_records = [_record("session-a", 1, "final")]
        runtime = FakeRuntime()
        service = KnowledgeIngestionService(
            transcript_writer=writer,
            runtime_factory=lambda: runtime,
        )

        service.rebuild_session_index("session-a")

        self.assertEqual(len(runtime.index_store.deleted_filters), 1)
        indexed_records, _ = runtime.indexing_service.indexed[0]
        self.assertEqual([record.content for record in indexed_records], ["final"])


def _session(session_id: str) -> RealtimeSession:
    return RealtimeSession(
        session_id=session_id,
        course_id="course-a",
        lesson_id="lesson-a",
        subject="math",
        created_at=100,
        updated_at=100,
    )


def _record(session_id: str, chunk_id: int, text: str) -> dict[str, object]:
    return {
        "session_id": session_id,
        "course_id": "course-a",
        "lesson_id": "lesson-a",
        "chunk_id": chunk_id,
        "subject": "math",
        "source_type": "realtime",
        "text": text,
        "clean_text": text,
        "created_at": 100 + chunk_id,
    }


if __name__ == "__main__":
    unittest.main()
