from __future__ import annotations

import logging
from typing import Callable, Protocol

from src.application.live_classroom.events import TranscriptFinalized
from src.domain.session import RealtimeSession


class TranscriptWriter(Protocol):
    def append_realtime_transcript(self, session: RealtimeSession, text: str): ...


class TranscriptFinalizationService:
    def __init__(
        self,
        *,
        session_getter: Callable[[str], RealtimeSession | None],
        transcript_writer: TranscriptWriter,
        on_finalized: Callable[[TranscriptFinalized], None] | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.session_getter = session_getter
        self.transcript_writer = transcript_writer
        self.on_finalized = on_finalized
        self.logger = logger or logging.getLogger(__name__)

    def finalize(self, session_id: str, text: str) -> TranscriptFinalized | None:
        clean_text = (text or "").strip()
        if not clean_text:
            return None

        session = self.session_getter(session_id)
        if session is None:
            self.logger.warning(
                "Skip transcript persistence because session %s was not found",
                session_id,
            )
            return None

        record = self.transcript_writer.append_realtime_transcript(session, clean_text)
        if record is None:
            return None

        event = TranscriptFinalized(session=session, record=record)
        if self.on_finalized is not None:
            self.on_finalized(event)
        return event
