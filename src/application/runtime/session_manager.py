from __future__ import annotations

import re
import threading
import time
import uuid
from typing import Optional

from src.domain.session import RealtimeSession, SessionStatus


class SessionManager:
    """In-memory registry for realtime lesson sessions."""

    def __init__(self) -> None:
        self._sessions: dict[str, RealtimeSession] = {}
        self._lock = threading.RLock()

    def create_session(
        self,
        *,
        course_id: Optional[str] = None,
        lesson_id: Optional[str] = None,
        subject: Optional[str] = None,
        client_id: Optional[str] = None,
        sample_rate: int = 16000,
        channels: int = 1,
        model_name: Optional[str] = None,
    ) -> RealtimeSession:
        now = int(time.time())
        session_id = uuid.uuid4().hex
        resolved_course_id = self._resolve_course_id(course_id=course_id, subject=subject)
        resolved_lesson_id = self._resolve_lesson_id(
            lesson_id=lesson_id,
            course_id=resolved_course_id,
            created_at=now,
            session_id=session_id,
        )
        session = RealtimeSession(
            session_id=session_id,
            course_id=resolved_course_id,
            lesson_id=resolved_lesson_id,
            subject=subject,
            client_id=client_id,
            sample_rate=sample_rate,
            channels=channels,
            model_name=model_name,
            status=SessionStatus.IDLE,
            created_at=now,
            updated_at=now,
        )
        with self._lock:
            self._sessions[session.session_id] = session
        return session

    def get_session(self, session_id: str) -> Optional[RealtimeSession]:
        with self._lock:
            return self._sessions.get(session_id)

    def require_session(self, session_id: str) -> RealtimeSession:
        session = self.get_session(session_id)
        if session is None:
            raise KeyError(session_id)
        return session

    def list_sessions(self) -> list[RealtimeSession]:
        with self._lock:
            return list(self._sessions.values())

    def mark_connected(self, session_id: str) -> RealtimeSession:
        with self._lock:
            session = self.require_session(session_id)
            session.active_connections += 1
            session.status = SessionStatus.CONNECTED
            session.updated_at = int(time.time())
            session.last_error = None
            return session

    def mark_running(self, session_id: str) -> RealtimeSession:
        with self._lock:
            session = self.require_session(session_id)
            session.status = SessionStatus.RUNNING
            session.updated_at = int(time.time())
            return session

    def mark_disconnected(self, session_id: str) -> Optional[RealtimeSession]:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return None
            session.active_connections = max(0, session.active_connections - 1)
            session.status = (
                SessionStatus.STOPPED
                if session.active_connections == 0
                else SessionStatus.CONNECTED
            )
            session.updated_at = int(time.time())
            return session

    def mark_error(self, session_id: str, error: str) -> Optional[RealtimeSession]:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return None
            session.status = SessionStatus.ERROR
            session.last_error = error
            session.updated_at = int(time.time())
            return session

    def next_event_seq(self, session_id: str) -> int:
        with self._lock:
            session = self.require_session(session_id)
            session.event_seq += 1
            session.updated_at = int(time.time())
            return session.event_seq

    @staticmethod
    def _resolve_course_id(*, course_id: Optional[str], subject: Optional[str]) -> str:
        normalized = SessionManager._normalize_identifier(course_id)
        if normalized is not None:
            return normalized

        normalized_subject = SessionManager._normalize_identifier(subject)
        if normalized_subject is not None:
            return normalized_subject
        return "general"

    @staticmethod
    def _resolve_lesson_id(
        *,
        lesson_id: Optional[str],
        course_id: str,
        created_at: int,
        session_id: str,
    ) -> str:
        normalized = SessionManager._normalize_identifier(lesson_id)
        if normalized is not None:
            return normalized

        lesson_date = time.strftime("%Y%m%d_%H%M%S", time.localtime(created_at))
        return f"{course_id}_{lesson_date}_{session_id[:8]}"

    @staticmethod
    def _normalize_identifier(value: Optional[str]) -> Optional[str]:
        text = (value or "").strip()
        if not text:
            return None
        text = re.sub(r"[^\w\u4e00-\u9fff\-]+", "_", text)
        text = re.sub(r"_+", "_", text).strip("_")
        return text or None


session_manager = SessionManager()
