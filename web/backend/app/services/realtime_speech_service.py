from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import numpy as np
from fastapi import WebSocket

from src.application.speech_pipeline import WebSpeechPipeline
from web.backend.app.domain.session import RealtimeSession
from web.backend.app.services.realtime_rag_indexer import realtime_rag_indexer
from web.backend.app.services.session_manager import session_manager
from web.backend.app.services.session_transcript_refine_service import session_transcript_refine_service
from web.backend.app.services.transcript_service import transcript_service

logger = logging.getLogger(__name__)


class RealtimeSpeechService:
    """Coordinate websocket audio events, pipeline lifecycle, and transcript persistence."""

    def make_event_payload(
        self,
        *,
        session_id: str,
        seq: int,
        event_type: str,
        text: str | None = None,
        is_final: bool = False,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "type": event_type,
            "session_id": session_id,
            "seq": seq,
            "is_final": is_final,
            "timestamp": int(time.time()),
        }
        if text is not None:
            payload["text"] = text
        if extra:
            payload.update(extra)
        return payload

    def make_sender(self, websocket: WebSocket, loop: asyncio.AbstractEventLoop, session_id: str):
        def _send(event_type: str, text: str, *, is_final: bool) -> None:
            if not text:
                return
            seq = session_manager.next_event_seq(session_id)
            payload = self.make_event_payload(
                session_id=session_id,
                seq=seq,
                event_type=event_type,
                text=text,
                is_final=is_final,
            )
            asyncio.run_coroutine_threadsafe(websocket.send_json(payload), loop)

        return _send

    def create_pipeline(
        self,
        *,
        websocket: WebSocket,
        loop: asyncio.AbstractEventLoop,
        session: RealtimeSession,
    ) -> WebSpeechPipeline:
        sender = self.make_sender(websocket, loop, session.session_id)
        pipeline = WebSpeechPipeline(
            on_partial=lambda text: sender("partial_transcript", text, is_final=False),
            on_final=lambda text: self._handle_final_transcript(session.session_id, sender, text),
            model_name=session.model_name,
        )
        pipeline.start()
        return pipeline

    def _handle_final_transcript(self, session_id: str, sender, text: str) -> None:
        sender("final_transcript", text, is_final=True)
        if not text:
            return

        session = session_manager.get_session(session_id)
        if session is None:
            logger.warning("Skip transcript persistence because session %s was not found", session_id)
            return
        record = transcript_service.append_realtime_transcript(session, text)
        if record is not None:
            try:
                realtime_rag_indexer.append_record(session, record)
            except Exception as exc:
                logger.exception("Failed to enqueue realtime transcript for RAG indexing: %s", exc)

    async def make_session_started_payload(self, session: RealtimeSession) -> dict[str, Any]:
        seq = session_manager.next_event_seq(session.session_id)
        return self.make_event_payload(
            session_id=session.session_id,
            seq=seq,
            event_type="session_started",
            extra={
                "course_id": session.course_id,
                "lesson_id": session.lesson_id,
                "status": session.status.value,
                "sample_rate": session.sample_rate,
                "channels": session.channels,
                "model_name": session.model_name,
            },
        )

    async def process_audio_message(
        self,
        *,
        session_id: str,
        audio_bytes: bytes,
        pipeline: WebSpeechPipeline,
        last_metrics_at: float,
    ) -> tuple[float, dict[str, Any] | None]:
        session_manager.mark_running(session_id)
        audio = np.frombuffer(audio_bytes, dtype=np.float32)
        metrics_payload = None
        now = time.monotonic()
        if audio.size > 0 and now - last_metrics_at >= 1.0:
            peak = float(np.max(np.abs(audio)))
            rms = float(np.sqrt(np.mean(audio * audio)))
            seq = session_manager.next_event_seq(session_id)
            metrics_payload = self.make_event_payload(
                session_id=session_id,
                seq=seq,
                event_type="audio_metrics",
                extra={"peak": peak, "rms": rms},
            )
            last_metrics_at = now

        await asyncio.to_thread(pipeline.feed_audio_bytes, audio_bytes)
        return last_metrics_at, metrics_payload

    async def make_pong_payload(self, session_id: str) -> dict[str, Any]:
        return self.make_event_payload(
            session_id=session_id,
            seq=session_manager.next_event_seq(session_id),
            event_type="pong",
        )

    async def make_error_payload(self, session_id: str, exc: Exception) -> dict[str, Any]:
        session_manager.mark_error(session_id, str(exc))
        return self.make_event_payload(
            session_id=session_id,
            seq=session_manager.next_event_seq(session_id),
            event_type="session_error",
            extra={"error": str(exc)},
        )

    async def shutdown_session(self, session_id: str, pipeline: WebSpeechPipeline) -> dict[str, Any] | None:
        pipeline.stop()
        realtime_rag_indexer.flush_session(session_id)
        transcript_service.release_session(session_id)
        session = session_manager.mark_disconnected(session_id)
        if session is None:
            return None
        session_transcript_refine_service.enqueue_session(session_id)
        return self.make_event_payload(
            session_id=session_id,
            seq=session_manager.next_event_seq(session_id),
            event_type="session_stopped",
            extra={"status": session.status.value},
        )


realtime_speech_service = RealtimeSpeechService()
