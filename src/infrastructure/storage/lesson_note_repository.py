from __future__ import annotations

import json
import time
from typing import Any, Mapping

from src.domain.lesson_note import LessonNote, LessonNoteStatus
from src.infrastructure.storage.sqlite_store import SQLiteStore, sqlite_store


class SQLiteLessonNoteRepository:
    def __init__(self, *, store: SQLiteStore = sqlite_store) -> None:
        self.store = store

    def init_schema(self) -> None:
        self.store.init_schema()
        self.store.execute(
            """
            CREATE TABLE IF NOT EXISTS lesson_notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                note_id TEXT NOT NULL UNIQUE,
                course_id TEXT NOT NULL,
                lesson_id TEXT NOT NULL,
                session_id TEXT,
                status TEXT NOT NULL,
                title TEXT,
                summary TEXT,
                markdown TEXT,
                note_json TEXT,
                source_record_count INTEGER NOT NULL DEFAULT 0,
                source_hash TEXT,
                model_name TEXT,
                error_message TEXT,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                metadata_json TEXT
            )
            """
        )
        self.store.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_lesson_notes_lesson_updated
            ON lesson_notes(course_id, lesson_id, updated_at, id)
            """
        )
        self.store.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_lesson_notes_status_updated
            ON lesson_notes(status, updated_at, id)
            """
        )

    def create_note(
        self,
        *,
        note_id: str,
        course_id: str,
        lesson_id: str,
        status: LessonNoteStatus,
        session_id: str | None = None,
        title: str | None = None,
        summary: str | None = None,
        markdown: str | None = None,
        note: Mapping[str, Any] | None = None,
        source_record_count: int = 0,
        source_hash: str | None = None,
        model_name: str | None = None,
        error_message: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> LessonNote:
        now = int(time.time())
        self.store.execute(
            """
            INSERT INTO lesson_notes (
                note_id, course_id, lesson_id, session_id, status,
                title, summary, markdown, note_json,
                source_record_count, source_hash, model_name, error_message,
                created_at, updated_at, metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                note_id,
                course_id,
                lesson_id,
                session_id,
                _status_value(status),
                title,
                summary,
                markdown,
                _encode_json(note),
                int(source_record_count),
                source_hash,
                model_name,
                error_message,
                now,
                now,
                _encode_json(metadata),
            ),
        )
        created = self.get_note(note_id)
        if created is None:
            raise RuntimeError("failed to create lesson note")
        return created

    def update_note(self, note_id: str, **changes: Any) -> None:
        if not changes:
            return

        if "status" in changes:
            changes["status"] = _status_value(changes["status"])
        if "note" in changes:
            changes["note_json"] = _encode_json(changes.pop("note"))
        if "metadata" in changes:
            metadata = changes.pop("metadata")
            if metadata is not None:
                existing = self.get_note(note_id)
                merged = dict(existing.metadata if existing is not None else {})
                merged.update(dict(metadata))
                changes["metadata_json"] = _encode_json(merged)

        changes["updated_at"] = int(time.time())
        assignments = ", ".join(f"{key} = ?" for key in changes)
        values = list(changes.values())
        values.append(note_id)
        self.store.execute(
            f"""
            UPDATE lesson_notes
            SET {assignments}
            WHERE note_id = ?
            """,
            values,
        )

    def get_note(self, note_id: str) -> LessonNote | None:
        rows = self.store.query_all(
            """
            SELECT *
            FROM lesson_notes
            WHERE note_id = ?
            LIMIT 1
            """,
            (note_id,),
        )
        return _row_to_note(rows[0]) if rows else None

    def get_latest_note(self, *, course_id: str, lesson_id: str) -> LessonNote | None:
        rows = self.store.query_all(
            """
            SELECT *
            FROM lesson_notes
            WHERE course_id = ? AND lesson_id = ?
            ORDER BY updated_at DESC, id DESC
            LIMIT 1
            """,
            (course_id, lesson_id),
        )
        return _row_to_note(rows[0]) if rows else None


def _row_to_note(row: Mapping[str, Any]) -> LessonNote:
    status_value = str(row["status"])
    try:
        status = LessonNoteStatus(status_value)
    except ValueError:
        status = LessonNoteStatus.FAILED
    return LessonNote(
        id=int(row["id"]),
        note_id=str(row["note_id"]),
        course_id=str(row["course_id"]),
        lesson_id=str(row["lesson_id"]),
        session_id=_optional_str(row.get("session_id")),
        status=status,
        title=_optional_str(row.get("title")),
        summary=_optional_str(row.get("summary")),
        markdown=_optional_str(row.get("markdown")),
        note=_decode_json(row.get("note_json")),
        source_record_count=int(row.get("source_record_count") or 0),
        source_hash=_optional_str(row.get("source_hash")),
        model_name=_optional_str(row.get("model_name")),
        error_message=_optional_str(row.get("error_message")),
        created_at=int(row["created_at"]),
        updated_at=int(row["updated_at"]),
        metadata=_decode_json(row.get("metadata_json")),
    )


def _status_value(value: LessonNoteStatus | str) -> str:
    if isinstance(value, LessonNoteStatus):
        return value.value
    return str(value)


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _encode_json(value: Mapping[str, Any] | None) -> str | None:
    if not value:
        return None
    return json.dumps(dict(value), ensure_ascii=False, default=str)


def _decode_json(value: Any) -> dict[str, Any]:
    if not value:
        return {}
    try:
        payload = json.loads(str(value))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}
