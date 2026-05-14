from __future__ import annotations

import json
import re
import threading
import time
import uuid
from typing import Optional, Protocol

from config.settings import settings
from src.domain.session import RealtimeSession, SessionStatus


class SessionStore(Protocol):
    def save(self, session: RealtimeSession) -> RealtimeSession: ...

    def get(self, session_id: str) -> Optional[RealtimeSession]: ...

    def list(self) -> list[RealtimeSession]: ...

    def update_connected(self, session_id: str, *, now: int) -> Optional[RealtimeSession]: ...

    def update_running(self, session_id: str, *, now: int) -> Optional[RealtimeSession]: ...

    def update_disconnected(self, session_id: str, *, now: int) -> Optional[RealtimeSession]: ...

    def update_error(self, session_id: str, *, error: str, now: int) -> Optional[RealtimeSession]: ...

    def increment_event_seq(self, session_id: str, *, now: int) -> int: ...

    def ping(self) -> None: ...


class InMemorySessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, RealtimeSession] = {}
        self._lock = threading.RLock()

    def save(self, session: RealtimeSession) -> RealtimeSession:
        with self._lock:
            self._sessions[session.session_id] = session
        return session

    def get(self, session_id: str) -> Optional[RealtimeSession]:
        with self._lock:
            return self._sessions.get(session_id)

    def list(self) -> list[RealtimeSession]:
        with self._lock:
            return list(self._sessions.values())

    def update_connected(self, session_id: str, *, now: int) -> Optional[RealtimeSession]:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return None
            session.active_connections += 1
            session.status = SessionStatus.CONNECTED
            session.updated_at = now
            session.last_error = None
            return session

    def update_running(self, session_id: str, *, now: int) -> Optional[RealtimeSession]:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return None
            session.status = SessionStatus.RUNNING
            session.updated_at = now
            return session

    def update_disconnected(self, session_id: str, *, now: int) -> Optional[RealtimeSession]:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return None
            session.active_connections = max(0, session.active_connections - 1)
            session.status = SessionStatus.STOPPED if session.active_connections == 0 else SessionStatus.CONNECTED
            session.updated_at = now
            return session

    def update_error(self, session_id: str, *, error: str, now: int) -> Optional[RealtimeSession]:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return None
            session.status = SessionStatus.ERROR
            session.last_error = error
            session.updated_at = now
            return session

    def increment_event_seq(self, session_id: str, *, now: int) -> int:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                raise KeyError(session_id)
            session.event_seq += 1
            session.updated_at = now
            return session.event_seq

    def ping(self) -> None:
        return None


class RedisSessionStore:
    def __init__(
        self,
        redis_url: str,
        *,
        key_prefix: str = "study-agent:sessions",
        ttl_seconds: int = 24 * 60 * 60,
        terminal_ttl_seconds: int = 6 * 60 * 60,
    ) -> None:
        try:
            import redis
        except ImportError as exc:
            raise RuntimeError(
                "redis package is required when REDIS_URL is configured. Install it with `pip install redis`."
            ) from exc

        self._redis_module = redis
        self._redis = redis.Redis.from_url(redis_url, decode_responses=True)
        self._key_prefix = key_prefix.rstrip(":")
        self._session_index_key = f"{self._key_prefix}:index"
        self._ttl_seconds = max(1, int(ttl_seconds))
        self._terminal_ttl_seconds = max(1, int(terminal_ttl_seconds))

    def _session_key(self, session_id: str) -> str:
        return f"{self._key_prefix}:session:{session_id}"

    def _ttl_for_status(self, status: SessionStatus) -> int:
        if status in {SessionStatus.STOPPED, SessionStatus.ERROR}:
            return self._terminal_ttl_seconds
        return self._ttl_seconds

    def save(self, session: RealtimeSession) -> RealtimeSession:
        payload = _session_to_payload(session)
        key = self._session_key(session.session_id)
        pipeline = self._redis.pipeline()
        pipeline.hset(key, mapping=payload)
        pipeline.expire(key, self._ttl_for_status(session.status))
        pipeline.sadd(self._session_index_key, session.session_id)
        pipeline.execute()
        return session

    def get(self, session_id: str) -> Optional[RealtimeSession]:
        payload = self._redis.hgetall(self._session_key(session_id))
        if not payload:
            return None
        return _payload_to_session(payload)

    def list(self) -> list[RealtimeSession]:
        session_ids = sorted(str(item) for item in self._redis.smembers(self._session_index_key))
        if not session_ids:
            return []

        pipeline = self._redis.pipeline()
        for session_id in session_ids:
            pipeline.hgetall(self._session_key(session_id))
        rows = pipeline.execute()
        sessions: list[RealtimeSession] = []
        missing_ids: list[str] = []
        for session_id, payload in zip(session_ids, rows):
            if not payload:
                missing_ids.append(session_id)
                continue
            sessions.append(_payload_to_session(payload))
        if missing_ids:
            self._redis.srem(self._session_index_key, *missing_ids)
        return sessions

    def update_connected(self, session_id: str, *, now: int) -> Optional[RealtimeSession]:
        key = self._session_key(session_id)
        if not self._redis.exists(key):
            return None
        pipeline = self._redis.pipeline()
        pipeline.hincrby(key, "active_connections", 1)
        pipeline.hset(
            key,
            mapping={
                "status": SessionStatus.CONNECTED.value,
                "updated_at": str(now),
                "last_error": "",
            },
        )
        pipeline.expire(key, self._ttl_for_status(SessionStatus.CONNECTED))
        pipeline.execute()
        return self.get(session_id)

    def update_running(self, session_id: str, *, now: int) -> Optional[RealtimeSession]:
        key = self._session_key(session_id)
        if not self._redis.exists(key):
            return None
        self._redis.hset(
            key,
            mapping={
                "status": SessionStatus.RUNNING.value,
                "updated_at": str(now),
            },
        )
        self._redis.expire(key, self._ttl_for_status(SessionStatus.RUNNING))
        return self.get(session_id)

    def update_disconnected(self, session_id: str, *, now: int) -> Optional[RealtimeSession]:
        key = self._session_key(session_id)
        if not self._redis.exists(key):
            return None

        with self._redis.pipeline() as pipeline:
            while True:
                try:
                    pipeline.watch(key)
                    payload = pipeline.hgetall(key)
                    if not payload:
                        pipeline.reset()
                        return None
                    session = _payload_to_session(payload)
                    session.active_connections = max(0, session.active_connections - 1)
                    session.status = SessionStatus.STOPPED if session.active_connections == 0 else SessionStatus.CONNECTED
                    session.updated_at = now

                    pipeline.multi()
                    pipeline.hset(key, mapping=_session_to_payload(session))
                    pipeline.expire(key, self._ttl_for_status(session.status))
                    pipeline.execute()
                    return session
                except self._redis_module.WatchError:
                    continue

    def update_error(self, session_id: str, *, error: str, now: int) -> Optional[RealtimeSession]:
        key = self._session_key(session_id)
        if not self._redis.exists(key):
            return None
        self._redis.hset(
            key,
            mapping={
                "status": SessionStatus.ERROR.value,
                "updated_at": str(now),
                "last_error": error,
            },
        )
        self._redis.expire(key, self._ttl_for_status(SessionStatus.ERROR))
        return self.get(session_id)

    def increment_event_seq(self, session_id: str, *, now: int) -> int:
        key = self._session_key(session_id)
        if not self._redis.exists(key):
            raise KeyError(session_id)
        pipeline = self._redis.pipeline()
        pipeline.hincrby(key, "event_seq", 1)
        pipeline.hset(key, "updated_at", str(now))
        status = _optional_text(self._redis.hget(key, "status")) or SessionStatus.IDLE.value
        pipeline.expire(key, self._ttl_for_status(SessionStatus(status)))
        event_seq, _, _ = pipeline.execute()
        return int(event_seq)

    def ping(self) -> None:
        self._redis.ping()


class SessionManager:
    """Registry for realtime lesson sessions, backed by Redis when configured."""

    def __init__(self, *, store: SessionStore | None = None) -> None:
        self._store = store or self._build_default_store()

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
        return self._store.save(session)

    def get_session(self, session_id: str) -> Optional[RealtimeSession]:
        return self._store.get(session_id)

    def require_session(self, session_id: str) -> RealtimeSession:
        session = self.get_session(session_id)
        if session is None:
            raise KeyError(session_id)
        return session

    def list_sessions(self) -> list[RealtimeSession]:
        return self._store.list()

    def mark_connected(self, session_id: str) -> RealtimeSession:
        session = self._store.update_connected(session_id, now=int(time.time()))
        if session is None:
            raise KeyError(session_id)
        return session

    def mark_running(self, session_id: str) -> RealtimeSession:
        session = self._store.update_running(session_id, now=int(time.time()))
        if session is None:
            raise KeyError(session_id)
        return session

    def mark_disconnected(self, session_id: str) -> Optional[RealtimeSession]:
        return self._store.update_disconnected(session_id, now=int(time.time()))

    def mark_error(self, session_id: str, error: str) -> Optional[RealtimeSession]:
        return self._store.update_error(session_id, error=error, now=int(time.time()))

    def next_event_seq(self, session_id: str) -> int:
        return self._store.increment_event_seq(session_id, now=int(time.time()))

    def ping(self) -> None:
        self._store.ping()

    @staticmethod
    def _build_default_store() -> SessionStore:
        redis_url = settings.REDIS_URL.strip()
        if redis_url:
            return RedisSessionStore(
                redis_url,
                key_prefix=settings.SESSION_REDIS_PREFIX,
                ttl_seconds=settings.SESSION_REDIS_TTL_SECONDS,
                terminal_ttl_seconds=settings.SESSION_REDIS_TERMINAL_TTL_SECONDS,
            )
        return InMemorySessionStore()

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


def _session_to_payload(session: RealtimeSession) -> dict[str, str]:
    return {
        "session_id": session.session_id,
        "course_id": session.course_id,
        "lesson_id": session.lesson_id,
        "subject": session.subject or "",
        "client_id": session.client_id or "",
        "sample_rate": str(int(session.sample_rate)),
        "channels": str(int(session.channels)),
        "model_name": session.model_name or "",
        "status": session.status.value,
        "active_connections": str(int(session.active_connections)),
        "created_at": str(int(session.created_at)),
        "updated_at": str(int(session.updated_at)),
        "last_error": session.last_error or "",
        "event_seq": str(int(session.event_seq)),
    }


def _payload_to_session(payload: dict[str, str]) -> RealtimeSession:
    return RealtimeSession(
        session_id=str(payload.get("session_id") or ""),
        course_id=str(payload.get("course_id") or "general"),
        lesson_id=str(payload.get("lesson_id") or ""),
        subject=_optional_text(payload.get("subject")),
        client_id=_optional_text(payload.get("client_id")),
        sample_rate=int(payload.get("sample_rate") or 16000),
        channels=int(payload.get("channels") or 1),
        model_name=_optional_text(payload.get("model_name")),
        status=SessionStatus(str(payload.get("status") or SessionStatus.IDLE.value)),
        active_connections=max(0, int(payload.get("active_connections") or 0)),
        created_at=int(payload.get("created_at") or 0),
        updated_at=int(payload.get("updated_at") or 0),
        last_error=_optional_text(payload.get("last_error")),
        event_seq=max(0, int(payload.get("event_seq") or 0)),
    )


def _optional_text(value: object) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


session_manager = SessionManager()
