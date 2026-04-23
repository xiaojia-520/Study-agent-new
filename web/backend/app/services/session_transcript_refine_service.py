from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from config.prompts import build_transcript_refine_prompt
from src.application.rag.runtime import close_shared_rag_runtime, get_shared_rag_runtime
from src.infrastructure.storage.sqlite_store import SQLiteStore, sqlite_store
from web.backend.app.services.session_manager import session_manager
from web.backend.app.services.transcript_service import transcript_service

logger = logging.getLogger(__name__)


def _build_runtime():
    return get_shared_rag_runtime()


@dataclass(slots=True)
class RefinedTranscriptRecord:
    id: int
    source_record_id: int
    session_id: str
    course_id: str | None
    lesson_id: str | None
    chunk_id: int
    original_text: str
    refined_text: str
    created_at: int
    refined_at: int
    model_name: str | None
    metadata: dict[str, Any]


class SessionTranscriptRefineService:
    def __init__(
        self,
        *,
        store: SQLiteStore = sqlite_store,
        runtime_factory=None,
        runtime_closer=None,
        session_getter=session_manager.get_session,
        transcript_loader=transcript_service.list_session_transcripts,
        batch_char_limit: int = 6000,
    ) -> None:
        self.store = store
        self.runtime_factory = runtime_factory or _build_runtime
        self.runtime_closer = runtime_closer or close_shared_rag_runtime
        self.session_getter = session_getter
        self.transcript_loader = transcript_loader
        self.batch_char_limit = max(1, int(batch_char_limit))
        self._runtime = None
        self._lock = threading.RLock()
        self._running_sessions: set[str] = set()

    def init_schema(self) -> None:
        self.store.init_schema()

    def enqueue_session(self, session_id: str) -> bool:
        normalized_session_id = (session_id or "").strip()
        if not normalized_session_id:
            return False

        with self._lock:
            if normalized_session_id in self._running_sessions:
                return False
            self._running_sessions.add(normalized_session_id)

        thread = threading.Thread(
            target=self._run_background_refinement,
            args=(normalized_session_id,),
            name=f"transcript-refine-{normalized_session_id[:8]}",
            daemon=True,
        )
        thread.start()
        return True

    def refine_session(self, session_id: str) -> list[RefinedTranscriptRecord]:
        normalized_session_id = (session_id or "").strip()
        if not normalized_session_id:
            return []

        session = self.session_getter(normalized_session_id)
        transcript_items = self.transcript_loader(session, normalized_session_id)
        pending_records = self._filter_pending_transcript_records(transcript_items)
        if not pending_records:
            return self.list_session_refined_transcripts(normalized_session_id)

        runtime = self._get_runtime()
        llm = getattr(runtime, "llm", None)
        if llm is None:
            logger.info("Skip transcript refinement because RAG LLM is not enabled")
            return self.list_session_refined_transcripts(normalized_session_id)

        model_name = self._resolve_model_name(runtime)
        batches = self._build_batches(pending_records)
        for batch_index, batch in enumerate(batches, start=1):
            prompt = build_transcript_refine_prompt(
                transcript_records=batch,
                batch_index=batch_index,
                batch_count=len(batches),
            )
            response_text = self._complete_text(llm, prompt)
            payload = self._parse_json_payload(response_text)
            normalized_results = self._normalize_refined_results(payload, batch)
            for source_record, refined_text in normalized_results:
                self.append_refined_transcript_record(
                    source_record=source_record,
                    refined_text=refined_text,
                    model_name=model_name,
                    metadata={
                        "prompt_version": "transcript-refine-v1",
                        "batch_index": batch_index,
                        "batch_count": len(batches),
                        "llm_used": True,
                    },
                )

        return self.list_session_refined_transcripts(normalized_session_id)

    def append_refined_transcript_record(
        self,
        *,
        source_record: Mapping[str, Any],
        refined_text: str,
        model_name: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> int:
        source_record_id = self._record_id(source_record)
        original_text = self._clean_transcript_text(source_record)
        normalized_refined_text = " ".join(str(refined_text or "").strip().split())
        if source_record_id is None:
            raise ValueError("source transcript record id is required")
        if not original_text or not normalized_refined_text:
            raise ValueError("original and refined transcript text are required")

        now = int(time.time())
        return self.store.execute(
            """
            INSERT INTO refined_transcript_records (
                source_record_id, session_id, course_id, lesson_id, chunk_id,
                original_text, refined_text, created_at, refined_at, model_name, metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_record_id) DO UPDATE SET
                refined_text = excluded.refined_text,
                refined_at = excluded.refined_at,
                model_name = excluded.model_name,
                metadata_json = excluded.metadata_json
            """,
            (
                source_record_id,
                _optional_text(source_record.get("session_id")) or "",
                _optional_text(source_record.get("course_id")),
                _optional_text(source_record.get("lesson_id")),
                _optional_int(source_record.get("chunk_id")) or 0,
                original_text,
                normalized_refined_text,
                _optional_int(source_record.get("created_at")) or now,
                now,
                _optional_text(model_name),
                _encode_metadata(metadata),
            ),
        )

    def list_session_refined_transcripts(self, session_id: str) -> list[RefinedTranscriptRecord]:
        rows = self.store.query_all(
            """
            SELECT id, source_record_id, session_id, course_id, lesson_id, chunk_id,
                   original_text, refined_text, created_at, refined_at, model_name, metadata_json
            FROM refined_transcript_records
            WHERE session_id = ?
            ORDER BY created_at ASC, chunk_id ASC, id ASC
            """,
            (session_id,),
        )
        return [_row_to_refined_record(row) for row in rows]

    def list_lesson_refined_transcripts(
        self,
        *,
        course_id: str,
        lesson_id: str,
    ) -> list[RefinedTranscriptRecord]:
        rows = self.store.query_all(
            """
            SELECT id, source_record_id, session_id, course_id, lesson_id, chunk_id,
                   original_text, refined_text, created_at, refined_at, model_name, metadata_json
            FROM refined_transcript_records
            WHERE course_id = ? AND lesson_id = ?
            ORDER BY created_at ASC, session_id ASC, chunk_id ASC, id ASC
            """,
            (course_id, lesson_id),
        )
        return [_row_to_refined_record(row) for row in rows]

    def close(self) -> None:
        if callable(self.runtime_closer):
            self.runtime_closer()
        elif self._runtime is not None:
            self._runtime.index_store.close()
        self._runtime = None

    def _run_background_refinement(self, session_id: str) -> None:
        try:
            self.refine_session(session_id)
        except Exception as exc:
            logger.exception("Failed to refine transcript for session %s: %s", session_id, exc)
        finally:
            with self._lock:
                self._running_sessions.discard(session_id)

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

    def _filter_pending_transcript_records(
        self,
        transcript_items: Sequence[Mapping[str, Any]],
    ) -> list[Mapping[str, Any]]:
        candidates: list[Mapping[str, Any]] = []
        source_ids: list[int] = []
        for item in transcript_items:
            source_record_id = self._record_id(item)
            if source_record_id is None:
                continue
            if not self._clean_transcript_text(item):
                continue
            candidates.append(item)
            source_ids.append(source_record_id)

        existing_source_ids = self._list_refined_source_ids(source_ids)
        return [item for item in candidates if self._record_id(item) not in existing_source_ids]

    def _list_refined_source_ids(self, source_ids: Sequence[int]) -> set[int]:
        if not source_ids:
            return set()

        placeholders = ", ".join("?" for _ in source_ids)
        rows = self.store.query_all(
            f"""
            SELECT source_record_id
            FROM refined_transcript_records
            WHERE source_record_id IN ({placeholders})
            """,
            tuple(source_ids),
        )
        return {int(row["source_record_id"]) for row in rows}

    def _build_batches(self, records: Sequence[Mapping[str, Any]]) -> list[list[Mapping[str, Any]]]:
        batches: list[list[Mapping[str, Any]]] = []
        current: list[Mapping[str, Any]] = []
        current_size = 0

        for record in records:
            text = self._clean_transcript_text(record)
            projected_size = current_size + len(text)
            if current and projected_size > self.batch_char_limit:
                batches.append(current)
                current = []
                current_size = 0

            current.append(record)
            current_size += len(text)

        if current:
            batches.append(current)
        return batches

    def _normalize_refined_results(
        self,
        payload: Sequence[Mapping[str, Any]],
        source_records: Sequence[Mapping[str, Any]],
    ) -> list[tuple[Mapping[str, Any], str]]:
        source_by_id = {
            source_record_id: record
            for record in source_records
            if (source_record_id := self._record_id(record)) is not None
        }
        results: list[tuple[Mapping[str, Any], str]] = []
        seen: set[int] = set()
        for item in payload:
            source_record_id = _optional_int(item.get("source_record_id") or item.get("id"))
            refined_text = _as_text(
                item.get("refined_text")
                or item.get("clean_text")
                or item.get("text")
            )
            if source_record_id is None or source_record_id in seen or refined_text is None:
                continue

            source_record = source_by_id.get(source_record_id)
            if source_record is None:
                continue

            seen.add(source_record_id)
            results.append((source_record, refined_text))
        return results

    @staticmethod
    def _complete_text(llm: Any, prompt: str) -> str:
        response = llm.complete(prompt)
        text = getattr(response, "text", None)
        if text is None:
            text = str(response)
        normalized = str(text).strip()
        if not normalized:
            raise ValueError("LLM returned an empty transcript refinement response")
        return normalized

    @staticmethod
    def _parse_json_payload(text: str) -> list[Mapping[str, Any]]:
        stripped = text.strip()
        candidates = [stripped]
        if stripped.startswith("```"):
            lines = stripped.splitlines()
            if len(lines) >= 3:
                candidates.append("\n".join(lines[1:-1]).strip())

        start = stripped.find("[")
        end = stripped.rfind("]")
        if start != -1 and end != -1 and end > start:
            candidates.append(stripped[start:end + 1])

        for candidate in candidates:
            if not candidate:
                continue
            try:
                payload = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, list):
                return [item for item in payload if isinstance(item, Mapping)]
            if isinstance(payload, Mapping):
                for key in ("items", "records", "results"):
                    value = payload.get(key)
                    if isinstance(value, list):
                        return [item for item in value if isinstance(item, Mapping)]
        return []

    @staticmethod
    def _resolve_model_name(runtime: Any) -> str | None:
        config = getattr(runtime, "config", None)
        value = getattr(config, "llm_model", None)
        return _optional_text(value)

    @staticmethod
    def _record_id(record: Mapping[str, Any]) -> int | None:
        return _optional_int(record.get("id") or record.get("source_record_id"))

    @staticmethod
    def _clean_transcript_text(record: Mapping[str, Any]) -> str:
        return " ".join(str(record.get("clean_text") or record.get("text") or "").strip().split())


session_transcript_refine_service = SessionTranscriptRefineService()


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_text(value: Any) -> str | None:
    text = _optional_text(value)
    if text is None:
        return None
    return " ".join(text.split())


def _encode_metadata(value: Mapping[str, Any] | None) -> str | None:
    if not value:
        return None
    return json.dumps(dict(value), ensure_ascii=False, default=str)


def _decode_metadata(value: Any) -> dict[str, Any]:
    if not value:
        return {}
    try:
        payload = json.loads(str(value))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _row_to_refined_record(row: Mapping[str, Any]) -> RefinedTranscriptRecord:
    return RefinedTranscriptRecord(
        id=int(row["id"]),
        source_record_id=int(row["source_record_id"]),
        session_id=str(row["session_id"]),
        course_id=_optional_text(row.get("course_id")),
        lesson_id=_optional_text(row.get("lesson_id")),
        chunk_id=int(row["chunk_id"]),
        original_text=str(row["original_text"]),
        refined_text=str(row["refined_text"]),
        created_at=int(row["created_at"]),
        refined_at=int(row["refined_at"]),
        model_name=_optional_text(row.get("model_name")),
        metadata=_decode_metadata(row.get("metadata_json")),
    )
