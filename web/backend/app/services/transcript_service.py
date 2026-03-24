from __future__ import annotations

import json
import logging
from pathlib import Path
import threading
import time
import re

from config.settings import settings
from src.core.knowledge.transcript_jsonl_store import TranscriptJsonlStore
from web.backend.app.domain.session import RealtimeSession

logger = logging.getLogger(__name__)


class TranscriptService:
    """Manage realtime transcript persistence for websocket sessions."""

    def __init__(self) -> None:
        self._stores: dict[str, TranscriptJsonlStore] = {}
        self._lock = threading.RLock()

    def _get_or_create_store(self, session: RealtimeSession) -> TranscriptJsonlStore:
        with self._lock:
            store = self._stores.get(session.session_id)
            if store is None:
                store_session_id = self._build_store_session_id(session)
                store = TranscriptJsonlStore(
                    subject=session.subject or "untitled",
                    session_id=store_session_id,
                )
                self._stores[session.session_id] = store
                logger.info("Created transcript store for session %s", session.session_id)
            return store

    def _build_store_session_id(self, session: RealtimeSession) -> str:
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
        logger.debug(
            "Persisted realtime transcript for session %s chunk %s",
            session.session_id,
            record["chunk_id"],
        )
        return record

    def list_session_transcripts(self, session: RealtimeSession | None, session_id: str):
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
        return records

    def _resolve_file_path(self, session: RealtimeSession | None, session_id: str) -> Path | None:
        if session is not None:
            candidate = settings.TRANSCRIPT_SAVE_DIR / f"{self._build_store_session_id(session)}.jsonl"
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
