from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

from src.infrastructure.storage.sqlite_store import SQLiteStore, sqlite_store
from web.backend.app.domain.session import RealtimeSession


@dataclass(frozen=True, slots=True)
class ChatMessageRecord:
    id: int
    session_id: str
    course_id: str | None
    lesson_id: str | None
    role: str
    content: str
    created_at: int
    metadata: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ChatMemoryTurn:
    user: str
    assistant: str | None
    created_at: int


@dataclass(frozen=True, slots=True)
class ChatLessonSummary:
    course_id: str | None
    lesson_id: str | None
    first_at: int
    last_at: int
    message_count: int
    transcript_count: int
    session_count: int
    last_session_id: str | None


class ChatMemoryService:
    def __init__(self, *, store: SQLiteStore = sqlite_store) -> None:
        self.store = store

    def init_schema(self) -> None:
        self.store.init_schema()

    def append_turn(
        self,
        *,
        session: RealtimeSession,
        user_text: str,
        assistant_text: str | None,
        answer_metadata: dict[str, Any] | None = None,
    ) -> None:
        now = int(time.time())
        self.append_message(
            session=session,
            role="user",
            content=user_text,
            created_at=now,
        )
        if assistant_text:
            self.append_message(
                session=session,
                role="assistant",
                content=assistant_text,
                created_at=now,
                metadata=answer_metadata,
            )

    def append_message(
        self,
        *,
        session: RealtimeSession,
        role: str,
        content: str,
        created_at: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        clean_content = " ".join((content or "").strip().split())
        if not clean_content:
            raise ValueError("chat memory content is required")
        if role not in {"user", "assistant"}:
            raise ValueError("chat memory role must be user or assistant")

        return self.store.execute(
            """
            INSERT INTO chat_messages (
                session_id, course_id, lesson_id, role, content, created_at, metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session.session_id,
                session.course_id,
                session.lesson_id,
                role,
                clean_content,
                int(created_at or time.time()),
                _encode_metadata(metadata),
            ),
        )

    def list_recent_turns(self, session_id: str, *, limit: int = 6) -> list[ChatMemoryTurn]:
        if limit <= 0:
            return []

        rows = self.store.query_all(
            """
            SELECT role, content, created_at
            FROM chat_messages
            WHERE session_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (session_id, max(1, int(limit)) * 2),
        )
        return _rows_to_turns(rows, limit=limit)

    def list_recent_lesson_turns(
        self,
        *,
        course_id: str,
        lesson_id: str,
        limit: int = 6,
    ) -> list[ChatMemoryTurn]:
        if limit <= 0:
            return []

        rows = self.store.query_all(
            """
            SELECT role, content, created_at
            FROM chat_messages
            WHERE course_id = ? AND lesson_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (course_id, lesson_id, max(1, int(limit)) * 2),
        )
        return _rows_to_turns(rows, limit=limit)

    def list_lesson_messages(
        self,
        *,
        course_id: str,
        lesson_id: str,
        limit: int | None = None,
    ) -> list[ChatMessageRecord]:
        limit_clause = ""
        params: tuple[Any, ...] = (course_id, lesson_id)
        if limit is not None:
            limit_clause = " LIMIT ?"
            params = (course_id, lesson_id, max(1, int(limit)))

        rows = self.store.query_all(
            f"""
            SELECT id, session_id, course_id, lesson_id, role, content, created_at, metadata_json
            FROM chat_messages
            WHERE course_id = ? AND lesson_id = ?
            ORDER BY id ASC
            {limit_clause}
            """,
            params,
        )
        return [_row_to_message(row) for row in rows]

    def list_lesson_summaries(self, *, limit: int = 50) -> list[ChatLessonSummary]:
        rows = self.store.query_all(
            """
            WITH lesson_events AS (
                SELECT
                    session_id,
                    course_id,
                    lesson_id,
                    created_at,
                    1 AS message_count,
                    0 AS transcript_count
                FROM chat_messages
                WHERE course_id IS NOT NULL AND lesson_id IS NOT NULL

                UNION ALL

                SELECT
                    session_id,
                    course_id,
                    lesson_id,
                    created_at,
                    0 AS message_count,
                    1 AS transcript_count
                FROM transcript_records
                WHERE course_id IS NOT NULL AND lesson_id IS NOT NULL
            ),
            lesson_groups AS (
                SELECT
                    course_id,
                    lesson_id,
                    MIN(created_at) AS first_at,
                    MAX(created_at) AS last_at,
                    SUM(message_count) AS message_count,
                    SUM(transcript_count) AS transcript_count,
                    COUNT(DISTINCT session_id) AS session_count
                FROM lesson_events
                GROUP BY course_id, lesson_id
            )
            SELECT
                course_id,
                lesson_id,
                first_at,
                last_at,
                message_count,
                transcript_count,
                session_count,
                (
                    SELECT event.session_id
                    FROM lesson_events event
                    WHERE
                        event.course_id = lesson_groups.course_id
                        AND event.lesson_id = lesson_groups.lesson_id
                    ORDER BY event.created_at DESC
                    LIMIT 1
                ) AS last_session_id
            FROM lesson_groups
            ORDER BY last_at DESC
            LIMIT ?
            """,
            (max(1, int(limit)),),
        )
        return [
            ChatLessonSummary(
                course_id=str(row["course_id"]) if row.get("course_id") is not None else None,
                lesson_id=str(row["lesson_id"]) if row.get("lesson_id") is not None else None,
                first_at=int(row["first_at"]),
                last_at=int(row["last_at"]),
                message_count=int(row["message_count"]),
                transcript_count=int(row["transcript_count"]),
                session_count=int(row["session_count"]),
                last_session_id=str(row["last_session_id"]) if row.get("last_session_id") is not None else None,
            )
            for row in rows
        ]

    def list_session_messages(self, session_id: str, *, limit: int | None = None) -> list[ChatMessageRecord]:
        limit_clause = ""
        params: tuple[Any, ...] = (session_id,)
        if limit is not None:
            limit_clause = " LIMIT ?"
            params = (session_id, max(1, int(limit)))

        rows = self.store.query_all(
            f"""
            SELECT id, session_id, course_id, lesson_id, role, content, created_at, metadata_json
            FROM chat_messages
            WHERE session_id = ?
            ORDER BY id ASC
            {limit_clause}
            """,
            params,
        )
        return [_row_to_message(row) for row in rows]

    def clear_session(self, session_id: str) -> None:
        self.store.execute("DELETE FROM chat_messages WHERE session_id = ?", (session_id,))


def _rows_to_turns(rows: list[dict[str, Any]], *, limit: int) -> list[ChatMemoryTurn]:
    rows.reverse()
    turns: list[ChatMemoryTurn] = []
    pending_user: tuple[str, int] | None = None

    for row in rows:
        role = str(row["role"])
        content = str(row["content"])
        created_at = int(row["created_at"])
        if role == "user":
            if pending_user is not None:
                turns.append(ChatMemoryTurn(user=pending_user[0], assistant=None, created_at=pending_user[1]))
            pending_user = (content, created_at)
            continue
        if role == "assistant" and pending_user is not None:
            turns.append(ChatMemoryTurn(user=pending_user[0], assistant=content, created_at=created_at))
            pending_user = None

    if pending_user is not None:
        turns.append(ChatMemoryTurn(user=pending_user[0], assistant=None, created_at=pending_user[1]))
    return turns[-limit:]


def _encode_metadata(metadata: dict[str, Any] | None) -> str | None:
    if not metadata:
        return None
    return json.dumps(metadata, ensure_ascii=False, default=str)


def _decode_metadata(value: Any) -> dict[str, Any]:
    if not value:
        return {}
    try:
        payload = json.loads(str(value))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _row_to_message(row: dict[str, Any]) -> ChatMessageRecord:
    return ChatMessageRecord(
        id=int(row["id"]),
        session_id=str(row["session_id"]),
        course_id=str(row["course_id"]) if row.get("course_id") is not None else None,
        lesson_id=str(row["lesson_id"]) if row.get("lesson_id") is not None else None,
        role=str(row["role"]),
        content=str(row["content"]),
        created_at=int(row["created_at"]),
        metadata=_decode_metadata(row.get("metadata_json")),
    )


chat_memory_service = ChatMemoryService()
