from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Mapping

from config.settings import settings
from src.application.rag.runtime import close_shared_rag_runtime, get_shared_rag_runtime
from src.core.knowledge.document_models import TranscriptRecord
from web.backend.app.domain.session import RealtimeSession

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class _BufferedSessionState:
    session_id: str
    subject: str
    records: list[TranscriptRecord] = field(default_factory=list)
    char_count: int = 0
    last_updated_at: float = field(default_factory=time.monotonic)

    def append(self, record: TranscriptRecord) -> None:
        self.records.append(record)
        self.char_count += len(record.content)
        self.last_updated_at = time.monotonic()

    def reset(self) -> list[TranscriptRecord]:
        snapshot = list(self.records)
        self.records.clear()
        self.char_count = 0
        self.last_updated_at = time.monotonic()
        return snapshot


class RealtimeRagIndexer:
    def __init__(
        self,
        *,
        enabled: bool = settings.RAG_REALTIME_INDEXING_ENABLED,
        flush_records: int = settings.RAG_REALTIME_FLUSH_RECORDS,
        flush_chars: int = settings.RAG_REALTIME_FLUSH_CHARS,
        flush_interval_seconds: float = settings.RAG_REALTIME_FLUSH_INTERVAL_SECONDS,
        queue_size: int = settings.RAG_REALTIME_QUEUE_SIZE,
        runtime_factory=get_shared_rag_runtime,
        runtime_closer=close_shared_rag_runtime,
    ) -> None:
        self.enabled = enabled
        self.flush_records = max(1, int(flush_records))
        self.flush_chars = max(1, int(flush_chars))
        self.flush_interval_seconds = max(1.0, float(flush_interval_seconds))
        self.runtime_factory = runtime_factory
        self.runtime_closer = runtime_closer

        self._buffers: dict[str, _BufferedSessionState] = {}
        self._lock = threading.RLock()
        self._queue: queue.Queue[list[TranscriptRecord] | None] = queue.Queue(maxsize=max(1, int(queue_size)))
        self._stop_event = threading.Event()
        self._worker = threading.Thread(target=self._worker_loop, daemon=True, name="realtime-rag-index-worker")
        self._watcher = threading.Thread(target=self._watcher_loop, daemon=True, name="realtime-rag-watch-worker")
        self._runtime = None

        if self.enabled:
            self._worker.start()
            self._watcher.start()

    def append_record(self, session: RealtimeSession, record_payload: Mapping[str, Any] | TranscriptRecord) -> None:
        if not self.enabled:
            return

        record = (
            record_payload
            if isinstance(record_payload, TranscriptRecord)
            else TranscriptRecord.from_dict(record_payload)
        )
        if record.session_id != session.session_id:
            raise ValueError("realtime rag record session_id does not match websocket session")

        to_flush: list[TranscriptRecord] | None = None
        with self._lock:
            state = self._buffers.get(session.session_id)
            if state is None:
                state = _BufferedSessionState(
                    session_id=session.session_id,
                    subject=session.subject or record.subject or "untitled",
                )
                self._buffers[session.session_id] = state

            state.append(record)
            if self._should_flush_locked(state):
                to_flush = state.reset()

        if to_flush:
            self._enqueue_for_indexing(to_flush)

    def flush_session(self, session_id: str) -> None:
        if not self.enabled:
            return

        pending: list[TranscriptRecord] | None = None
        with self._lock:
            state = self._buffers.pop(session_id, None)
            if state is not None and state.records:
                pending = state.reset()

        if pending:
            self._enqueue_for_indexing(pending)

    def close(self) -> None:
        if not self.enabled:
            return

        self._stop_event.set()
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            pass

        if self._watcher.is_alive():
            self._watcher.join(timeout=2.0)
        if self._worker.is_alive():
            self._worker.join(timeout=2.0)

        if callable(self.runtime_closer):
            self.runtime_closer()
        elif self._runtime is not None:
            self._runtime.index_store.close()
        self._runtime = None

    def _watcher_loop(self) -> None:
        while not self._stop_event.wait(timeout=1.0):
            expired_sessions: list[str] = []
            now = time.monotonic()

            with self._lock:
                for session_id, state in self._buffers.items():
                    if state.records and now - state.last_updated_at >= self.flush_interval_seconds:
                        expired_sessions.append(session_id)

            for session_id in expired_sessions:
                self.flush_session(session_id)

    def _worker_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                batch = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue

            if batch is None:
                break

            try:
                runtime = self._get_runtime()
                runtime.indexing_service.index_records(
                    batch,
                    embed_model=runtime.embed_model,
                )
                session_id = batch[0].session_id if batch else "unknown"
                logger.info(
                    "Realtime RAG indexed %s transcript records for session %s",
                    len(batch),
                    session_id,
                )
            except Exception as exc:
                logger.exception("Realtime RAG indexing failed: %s", exc)

    def _enqueue_for_indexing(self, records: list[TranscriptRecord]) -> None:
        if not records:
            return
        try:
            self._queue.put_nowait(list(records))
        except queue.Full:
            logger.warning(
                "Realtime RAG queue is full; dropping %s buffered records for session %s",
                len(records),
                records[0].session_id,
            )

    def _should_flush_locked(self, state: _BufferedSessionState) -> bool:
        return len(state.records) >= self.flush_records or state.char_count >= self.flush_chars

    def _get_runtime(self):
        runtime = self._runtime
        if runtime is not None:
            return runtime

        with self._lock:
            runtime = self._runtime
            if runtime is None:
                runtime = self.runtime_factory()
                self._runtime = runtime
        return runtime


realtime_rag_indexer = RealtimeRagIndexer()
