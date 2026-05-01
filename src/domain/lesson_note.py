from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class LessonNoteStatus(str, Enum):
    GENERATING = "generating"
    DONE = "done"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class LessonNote:
    note_id: str
    course_id: str
    lesson_id: str
    status: LessonNoteStatus
    id: int | None = None
    session_id: str | None = None
    title: str | None = None
    summary: str | None = None
    markdown: str | None = None
    note: dict[str, Any] = field(default_factory=dict)
    source_record_count: int = 0
    source_hash: str | None = None
    model_name: str | None = None
    error_message: str | None = None
    created_at: int = 0
    updated_at: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def is_fresh_for(self, source_hash: str | None) -> bool:
        return bool(source_hash) and self.status is LessonNoteStatus.DONE and self.source_hash == source_hash
