from __future__ import annotations

from dataclasses import dataclass

from src.application.chat.memory_service import ChatMemoryService, chat_memory_service
from src.application.documents.asset_service import LessonAssetService, lesson_asset_service
from src.application.lesson_copilot.service import LessonCopilotService, lesson_copilot_service
from src.application.lesson_notes import LessonNoteService
from src.application.lesson_notes.runtime import lesson_note_repository, lesson_note_service
from src.application.live_classroom.realtime_speech_service import RealtimeSpeechService, realtime_speech_service
from src.application.live_classroom.vision_service import SessionVisionService, session_vision_service
from src.application.rag.realtime_indexer import RealtimeRagIndexer, realtime_rag_indexer
from src.application.rag.session_query_service import SessionRagQueryService, session_rag_query_service
from src.application.review.lesson_history_service import LessonHistoryService, lesson_history_service
from src.application.review.lesson_quiz_service import SessionLessonQuizService, session_lesson_quiz_service
from src.application.review.lesson_summary_service import (
    SessionLessonSummaryService,
    session_lesson_summary_service,
)
from src.application.runtime.session_manager import SessionManager, session_manager
from src.application.transcripts.refinement_service import (
    SessionTranscriptRefineService,
    session_transcript_refine_service,
)
from src.application.transcripts.service import TranscriptService, transcript_service
from src.application.video.video_service import SessionVideoService, session_video_service
from src.infrastructure.storage.lesson_note_repository import LessonNoteSqlRepository


@dataclass(frozen=True, slots=True)
class ApplicationServices:
    chat_memory: ChatMemoryService
    lesson_asset: LessonAssetService
    lesson_copilot: LessonCopilotService
    lesson_history: LessonHistoryService
    lesson_note: LessonNoteService
    lesson_note_repository: LessonNoteSqlRepository
    lesson_quiz: SessionLessonQuizService
    lesson_summary: SessionLessonSummaryService
    realtime_rag_indexer: RealtimeRagIndexer
    realtime_speech: RealtimeSpeechService
    session_manager: SessionManager
    session_rag_query: SessionRagQueryService
    session_video: SessionVideoService
    session_vision: SessionVisionService
    transcript: TranscriptService
    transcript_refine: SessionTranscriptRefineService


_application_services = ApplicationServices(
    chat_memory=chat_memory_service,
    lesson_asset=lesson_asset_service,
    lesson_copilot=lesson_copilot_service,
    lesson_history=lesson_history_service,
    lesson_note=lesson_note_service,
    lesson_note_repository=lesson_note_repository,
    lesson_quiz=session_lesson_quiz_service,
    lesson_summary=session_lesson_summary_service,
    realtime_rag_indexer=realtime_rag_indexer,
    realtime_speech=realtime_speech_service,
    session_manager=session_manager,
    session_rag_query=session_rag_query_service,
    session_video=session_video_service,
    session_vision=session_vision_service,
    transcript=transcript_service,
    transcript_refine=session_transcript_refine_service,
)


def get_application_services() -> ApplicationServices:
    return _application_services
