from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from src.application.lesson_notes import LessonNoteService
from src.application.rag.runtime import build_default_llm
from src.domain.lesson_note import LessonNote
from src.infrastructure.storage.lesson_note_repository import SQLiteLessonNoteRepository
from web.backend.app.services.transcript_service import transcript_service


_shared_lesson_note_runtime: SimpleNamespace | None = None


def _get_shared_lesson_note_runtime() -> SimpleNamespace:
    global _shared_lesson_note_runtime
    if _shared_lesson_note_runtime is None:
        _shared_lesson_note_runtime = SimpleNamespace(llm=build_default_llm())
    return _shared_lesson_note_runtime


def _close_shared_lesson_note_runtime() -> None:
    global _shared_lesson_note_runtime
    _shared_lesson_note_runtime = None


lesson_note_repository = SQLiteLessonNoteRepository()

lesson_note_service = LessonNoteService(
    repository=lesson_note_repository,
    transcript_loader=transcript_service.list_lesson_transcripts,
    runtime_factory=_get_shared_lesson_note_runtime,
    runtime_closer=_close_shared_lesson_note_runtime,
)


def lesson_note_to_dict(note: LessonNote) -> dict[str, Any]:
    return {
        "id": note.id,
        "note_id": note.note_id,
        "course_id": note.course_id,
        "lesson_id": note.lesson_id,
        "session_id": note.session_id,
        "status": note.status.value,
        "title": note.title,
        "summary": note.summary,
        "markdown": note.markdown,
        "note": dict(note.note),
        "source_record_count": note.source_record_count,
        "source_hash": note.source_hash,
        "model_name": note.model_name,
        "error_message": note.error_message,
        "created_at": note.created_at,
        "updated_at": note.updated_at,
        "metadata": dict(note.metadata),
    }
