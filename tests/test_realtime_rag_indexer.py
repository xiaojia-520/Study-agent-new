import threading
import time
import unittest
from types import SimpleNamespace

from web.backend.app.domain.session import RealtimeSession
from web.backend.app.services.realtime_rag_indexer import RealtimeRagIndexer


class FakeIndexingService:
    def __init__(self):
        self.calls = []
        self.event = threading.Event()

    def index_records(self, records, **kwargs):
        self.calls.append((list(records), dict(kwargs)))
        self.event.set()
        return SimpleNamespace(record_count=len(records))


class FakeRuntime:
    def __init__(self):
        self.indexing_service = FakeIndexingService()
        self.embed_model = object()
        self.index_store = SimpleNamespace(close=lambda: None)


class RealtimeRagIndexerTests(unittest.TestCase):
    def test_flushes_after_record_threshold(self) -> None:
        runtime = FakeRuntime()
        indexer = RealtimeRagIndexer(
            enabled=True,
            flush_records=2,
            flush_chars=999,
            flush_interval_seconds=30,
            runtime_factory=lambda: runtime,
        )

        try:
            session = self._session("session-a")
            indexer.append_record(session, self._record_payload("session-a", 1, "alpha"))
            self.assertEqual(len(runtime.indexing_service.calls), 0)

            indexer.append_record(session, self._record_payload("session-a", 2, "beta"))
            self.assertTrue(runtime.indexing_service.event.wait(timeout=2.0))

            records, kwargs = runtime.indexing_service.calls[0]
            self.assertEqual([record.chunk_id for record in records], [1, 2])
            self.assertIs(kwargs["embed_model"], runtime.embed_model)
        finally:
            indexer.close()

    def test_flush_session_indexes_remaining_tail(self) -> None:
        runtime = FakeRuntime()
        indexer = RealtimeRagIndexer(
            enabled=True,
            flush_records=5,
            flush_chars=999,
            flush_interval_seconds=30,
            runtime_factory=lambda: runtime,
        )

        try:
            session = self._session("session-b")
            indexer.append_record(session, self._record_payload("session-b", 1, "gamma"))
            indexer.flush_session("session-b")

            self.assertTrue(runtime.indexing_service.event.wait(timeout=2.0))
            records, _ = runtime.indexing_service.calls[0]
            self.assertEqual([record.chunk_id for record in records], [1])
        finally:
            indexer.close()

    def test_flushes_stale_buffer_after_interval(self) -> None:
        runtime = FakeRuntime()
        indexer = RealtimeRagIndexer(
            enabled=True,
            flush_records=5,
            flush_chars=999,
            flush_interval_seconds=1,
            runtime_factory=lambda: runtime,
        )

        try:
            session = self._session("session-c")
            indexer.append_record(session, self._record_payload("session-c", 1, "delta"))

            self.assertTrue(runtime.indexing_service.event.wait(timeout=3.0))
            records, _ = runtime.indexing_service.calls[0]
            self.assertEqual([record.chunk_id for record in records], [1])
        finally:
            indexer.close()

    @staticmethod
    def _session(session_id: str) -> RealtimeSession:
        now = int(time.time())
        return RealtimeSession(
            session_id=session_id,
            subject="math",
            created_at=now,
            updated_at=now,
        )

    @staticmethod
    def _record_payload(session_id: str, chunk_id: int, text: str) -> dict[str, object]:
        return {
            "session_id": session_id,
            "chunk_id": chunk_id,
            "subject": "math",
            "source_type": "realtime",
            "text": text,
            "clean_text": text,
            "created_at": 100 + chunk_id,
        }


if __name__ == "__main__":
    unittest.main()
