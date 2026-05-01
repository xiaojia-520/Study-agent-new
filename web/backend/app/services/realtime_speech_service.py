from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import numpy as np
from fastapi import WebSocket

from src.application.live_classroom.realtime_event_publisher import RealtimeEventPublisher
from src.application.live_classroom.transcript_finalization import TranscriptFinalizationService
from src.application.runtime.session_manager import session_manager
from src.application.speech.pipeline import WebSpeechPipeline
from src.domain.session import RealtimeSession
from web.backend.app.services.knowledge_ingestion_service import knowledge_ingestion_service

logger = logging.getLogger(__name__)


class RealtimeSpeechService:
    """Coordinate websocket audio events, pipeline lifecycle, and transcript ingestion."""

    def __init__(
        self,
        *,
        event_publisher: RealtimeEventPublisher | None = None,
        transcript_finalizer: TranscriptFinalizationService | None = None,
    ) -> None:
        self.event_publisher = event_publisher or RealtimeEventPublisher(
            sequence_getter=lambda session_id: session_manager.next_event_seq(session_id),
        )
        self.transcript_finalizer = transcript_finalizer or TranscriptFinalizationService(
            session_getter=lambda session_id: session_manager.get_session(session_id),
            transcript_writer=knowledge_ingestion_service,
            logger=logger,
        )

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
        return self.event_publisher.make_event_payload(
            session_id=session_id,
            seq=seq,
            event_type=event_type,
            text=text,
            is_final=is_final,
            extra=extra,
        )

    def make_sender(self, websocket: WebSocket, loop: asyncio.AbstractEventLoop, session_id: str):
        return self.event_publisher.make_sender(
            send_json=websocket.send_json,
            loop=loop,
            session_id=session_id,
        )

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
        self.transcript_finalizer.finalize(session_id, text)

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
        knowledge_ingestion_service.flush_session(session_id)
        knowledge_ingestion_service.release_session(session_id)
        session = session_manager.mark_disconnected(session_id)
        if session is None:
            return None
        return self.make_event_payload(
            session_id=session_id,
            seq=session_manager.next_event_seq(session_id),
            event_type="session_stopped",
            extra={"status": session.status.value},
        )


realtime_speech_service = RealtimeSpeechService()
