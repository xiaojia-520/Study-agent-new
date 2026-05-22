from __future__ import annotations

from pydantic import BaseModel, Field

from src.application.rag.session_query_service import ClassroomContextMode, QueryScope


class CreateSessionRequest(BaseModel):
    course_id: str | None = None
    lesson_id: str | None = None
    subject: str | None = None
    client_id: str | None = None
    sample_rate: int = 16000
    channels: int = 1
    model_name: str | None = None


class SessionQueryRequest(BaseModel):
    query: str
    scope: QueryScope = QueryScope.AUTO
    top_k: int | None = None
    with_llm: bool = True
    include_rag_context: bool = False
    classroom_context_mode: ClassroomContextMode = ClassroomContextMode.SESSION
    asset_ids: list[str] = Field(default_factory=list)
    live_transcript: str | None = None


class SessionSummaryRequest(BaseModel):
    focus: str | None = None
    max_items: int | None = None


class SessionQuizRequest(BaseModel):
    focus: str | None = None
    question_count: int | None = None


class LessonNoteGenerateRequest(BaseModel):
    session_id: str | None = None
    focus: str | None = None
    max_items: int | None = None
    force: bool = False


class LessonCopilotRequest(BaseModel):
    message: str
    session_id: str | None = None
