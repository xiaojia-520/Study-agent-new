from __future__ import annotations

import json
import logging
from pathlib import Path
import threading
import time
import re
from typing import Any, Mapping

from config.settings import settings
from src.core.knowledge.transcript_jsonl_store import TranscriptJsonlStore
from src.infrastructure.storage.sqlite_store import SQLiteStore, sqlite_store
from web.backend.app.domain.session import RealtimeSession

logger = logging.getLogger(__name__)

_FINAL_TRANSCRIPT_PARSERS = {"offline_funasr"}
_FINAL_TRANSCRIPT_ROLES = {"final", "final_subtitle"}


class TranscriptService:
    """Manage realtime transcript persistence for websocket sessions."""

    def __init__(self, *, store: SQLiteStore = sqlite_store) -> None:
        self.store = store
        self._stores: dict[str, TranscriptJsonlStore] = {}
        self._lock = threading.RLock()

    def init_schema(self) -> None:
        self.store.init_schema()

    def _get_or_create_store(self, session: RealtimeSession) -> TranscriptJsonlStore:
        with self._lock:
            store = self._stores.get(session.session_id)
            if store is None:
                storage_id = self._build_storage_id(session)
                store = TranscriptJsonlStore(
                    subject=session.subject or "untitled",
                    session_id=session.session_id,
                    storage_id=storage_id,
                    course_id=session.course_id,
                    lesson_id=session.lesson_id,
                )
                self._stores[session.session_id] = store
                logger.info("Created transcript store for session %s", session.session_id)
            return store

    def _build_storage_id(self, session: RealtimeSession) -> str:
        subject_tag = self._sanitize_for_name(session.subject or "untitled")
        created_date = time.strftime("%Y%m%d", time.localtime(session.created_at or time.time()))
        return f"{created_date}_{subject_tag}_{session.session_id}"

    @staticmethod
    def _sanitize_for_name(value: str) -> str:
        cleaned = (value or "").strip()
        if not cleaned:
            return "untitled"
        cleaned = re.sub(r"[^\w\u4e00-\u9fff\-]+", "_", cleaned)
        cleaned = re.sub(r"_+", "_", cleaned).strip("_")
        return cleaned or "untitled"

    def append_realtime_transcript(self, session: RealtimeSession, text: str):
        clean_text = (text or "").strip()
        if not clean_text:
            return None

        store = self._get_or_create_store(session)
        record = store.append(
            text=clean_text,
            source_type="realtime",
        )
        self.append_transcript_record(record)
        logger.debug(
            "Persisted realtime transcript for session %s chunk %s",
            session.session_id,
            record["chunk_id"],
        )
        return record

    def append_transcript_record(self, record: Mapping[str, Any]) -> int:
        text = str(record.get("text") or "").strip()
        clean_text = str(record.get("clean_text") or text).strip()
        if not clean_text:
            raise ValueError("transcript text is required")

        return self.store.execute(
            """
            INSERT OR IGNORE INTO transcript_records (
                session_id, storage_id, course_id, lesson_id, chunk_id, subject,
                source_type, source_file, start_ms, end_ms, text, clean_text, created_at, metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _optional_text(record.get("session_id")) or "",
                _optional_text(record.get("storage_id")),
                _optional_text(record.get("course_id")),
                _optional_text(record.get("lesson_id")),
                int(record.get("chunk_id") or 0),
                _optional_text(record.get("subject")),
                _optional_text(record.get("source_type")) or "realtime",
                _optional_text(record.get("source_file")),
                _optional_int(record.get("start_ms")),
                _optional_int(record.get("end_ms")),
                text or clean_text,
                clean_text,
                int(record.get("created_at") or time.time()),
                _encode_metadata(record.get("metadata")),
            ),
        )

    def next_chunk_id(self, session_id: str) -> int:
        rows = self.store.query_all(
            """
            SELECT MAX(chunk_id) AS max_chunk_id
            FROM transcript_records
            WHERE session_id = ?
            """,
            (session_id,),
        )
        if not rows or rows[0].get("max_chunk_id") is None:
            return 1
        return int(rows[0]["max_chunk_id"]) + 1

    def list_session_transcripts(
        self,
        session: RealtimeSession | None,
        session_id: str,
        *,
        prefer_final: bool = True,
    ):
        sqlite_records = self._list_session_transcripts_from_sqlite(session_id)
        if sqlite_records:
            return _prefer_final_transcripts(sqlite_records) if prefer_final else sqlite_records

        file_path = self._resolve_file_path(session, session_id)
        if file_path is None or not file_path.exists():
            return []

        records = []
        with file_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                records.append(json.loads(line))
        return _prefer_final_transcripts(records) if prefer_final else records

    def list_lesson_transcripts(
        self,
        *,
        course_id: str,
        lesson_id: str,
        prefer_final: bool = True,
    ):
        sqlite_records = self._list_lesson_transcripts_from_sqlite(course_id=course_id, lesson_id=lesson_id)
        if sqlite_records:
            return _prefer_final_transcripts(sqlite_records) if prefer_final else sqlite_records

        records = []
        for file_path in sorted(settings.TRANSCRIPT_SAVE_DIR.glob("*.jsonl")):
            try:
                with file_path.open("r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        record = json.loads(line)
                        if record.get("course_id") == course_id and record.get("lesson_id") == lesson_id:
                            records.append(record)
            except (OSError, json.JSONDecodeError):
                logger.warning("Failed to read transcript file %s", file_path, exc_info=True)

        records = _sort_transcript_records(records)
        return _prefer_final_transcripts(records) if prefer_final else records

    def delete_final_video_transcripts(self, *, session_id: str, video_id: str) -> None:
        self.store.execute(
            """
            DELETE FROM transcript_records
            WHERE session_id = ?
              AND source_type = 'video'
              AND metadata_json LIKE ?
            """,
            (session_id, f'%"video_id": "{video_id}"%'),
        )

    def _list_session_transcripts_from_sqlite(self, session_id: str) -> list[dict[str, Any]]:
        rows = self.store.query_all(
            """
            SELECT id, session_id, storage_id, course_id, lesson_id, chunk_id, subject,
                   source_type, source_file, start_ms, end_ms, text, clean_text, created_at, metadata_json
            FROM transcript_records
            WHERE session_id = ?
            ORDER BY created_at ASC, chunk_id ASC, id ASC
            """,
            (session_id,),
        )
        return [_row_to_transcript_record(row) for row in rows]

    def _list_lesson_transcripts_from_sqlite(self, *, course_id: str, lesson_id: str) -> list[dict[str, Any]]:
        rows = self.store.query_all(
            """
            SELECT id, session_id, storage_id, course_id, lesson_id, chunk_id, subject,
                   source_type, source_file, start_ms, end_ms, text, clean_text, created_at, metadata_json
            FROM transcript_records
            WHERE course_id = ? AND lesson_id = ?
            ORDER BY created_at ASC, session_id ASC, chunk_id ASC, id ASC
            """,
            (course_id, lesson_id),
        )
        return [_row_to_transcript_record(row) for row in rows]

    def _resolve_file_path(self, session: RealtimeSession | None, session_id: str) -> Path | None:
        if session is not None:
            candidate = settings.TRANSCRIPT_SAVE_DIR / f"{self._build_storage_id(session)}.jsonl"
            if candidate.exists():
                return candidate

        direct = settings.TRANSCRIPT_SAVE_DIR / f"{session_id}.jsonl"
        if direct.exists():
            return direct

        matches = sorted(settings.TRANSCRIPT_SAVE_DIR.glob(f"*_{session_id}.jsonl"))
        return matches[-1] if matches else None

    def release_session(self, session_id: str) -> None:
        with self._lock:
            removed = self._stores.pop(session_id, None)
        if removed is not None:
            logger.info("Released transcript store for session %s", session_id)


transcript_service = TranscriptService()


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


def _encode_metadata(value: Any) -> str | None:
    if not value:
        return None
    return json.dumps(value, ensure_ascii=False, default=str)


def _decode_metadata(value: Any) -> dict[str, Any]:
    if not value:
        return {}
    try:
        payload = json.loads(str(value))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _prefer_final_transcripts(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    final_session_ids = {
        str(record.get("session_id") or "")
        for record in records
        if _is_final_transcript(record)
    }
    if not final_session_ids:
        return _sort_transcript_records(records)

    preferred = [
        record
        for record in records
        if str(record.get("session_id") or "") not in final_session_ids
        or not _is_realtime_transcript(record)
    ]
    return _sort_transcript_records(preferred)


def _is_realtime_transcript(record: Mapping[str, Any]) -> bool:
    return str(record.get("source_type") or "").lower() == "realtime"


def _is_final_transcript(record: Mapping[str, Any]) -> bool:
    metadata = record.get("metadata")
    if not isinstance(metadata, Mapping):
        metadata = {}
    parser = str(metadata.get("parser") or "").lower()
    role = str(metadata.get("transcript_role") or "").lower()
    return parser in _FINAL_TRANSCRIPT_PARSERS or role in _FINAL_TRANSCRIPT_ROLES


def _sort_transcript_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        records,
        key=lambda item: (
            _record_sort_ms(item),
            str(item.get("session_id") or ""),
            _record_timeline_ms(item),
            int(item.get("chunk_id") or 0),
            int(item.get("id") or 0),
        ),
    )


def _record_sort_ms(record: Mapping[str, Any]) -> int:
    metadata = record.get("metadata")
    if not isinstance(metadata, Mapping):
        metadata = {}

    timeline_ms = _record_timeline_ms(record)
    recording_started_at_ms = _optional_int(metadata.get("recording_started_at_ms"))
    if recording_started_at_ms is not None and recording_started_at_ms > 0:
        return recording_started_at_ms + timeline_ms

    frame_captured_at_ms = _optional_int(metadata.get("frame_captured_at_ms"))
    if frame_captured_at_ms is not None and frame_captured_at_ms > 0:
        return frame_captured_at_ms

    created_at_ms = max(0, int(record.get("created_at") or 0) * 1000)
    start_ms = _optional_int(record.get("start_ms"))
    if start_ms is not None and start_ms >= 0:
        return created_at_ms + start_ms % 1000
    return created_at_ms


def _record_timeline_ms(record: Mapping[str, Any]) -> int:
    metadata = record.get("metadata")
    if not isinstance(metadata, Mapping):
        metadata = {}

    for value in (
        metadata.get("timeline_ms"),
        record.get("start_ms"),
        metadata.get("frame_timestamp_ms"),
    ):
        parsed = _optional_int(value)
        if parsed is not None:
            return max(0, parsed)
    return max(0, int(record.get("created_at") or 0) * 1000)


def _row_to_transcript_record(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "session_id": str(row["session_id"]),
        "storage_id": _optional_text(row.get("storage_id")),
        "course_id": _optional_text(row.get("course_id")),
        "lesson_id": _optional_text(row.get("lesson_id")),
        "chunk_id": int(row["chunk_id"]),
        "subject": _optional_text(row.get("subject")) or "untitled",
        "source_type": _optional_text(row.get("source_type")) or "realtime",
        "source_file": _optional_text(row.get("source_file")),
        "start_ms": _optional_int(row.get("start_ms")),
        "end_ms": _optional_int(row.get("end_ms")),
        "text": str(row["text"]),
        "clean_text": str(row["clean_text"]),
        "created_at": int(row["created_at"]),
        "metadata": _decode_metadata(row.get("metadata_json")),
    }
