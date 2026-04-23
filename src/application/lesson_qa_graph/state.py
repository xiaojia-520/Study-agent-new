from __future__ import annotations

from typing import Any, TypedDict


class LessonQaState(TypedDict, total=False):
    session_id: str
    course_id: str | None
    lesson_id: str | None
    query: str
    rewritten_query: str | None
    requested_scope: str
    resolved_scope: str
    route: str
    conversation_history: list[Any]
    recent_transcripts: list[str]
    retrieval_results: list[Any]
    citations: list[Any]
    answer: str | None
    errors: list[str]
    metadata: dict[str, Any]

