from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class LessonVideo:
    id: int
    video_id: str
    session_id: str
    course_id: str | None
    lesson_id: str | None
    subject: str | None
    file_name: str
    file_path: str
    file_size: int
    media_type: str
    status: str
    wav_path: str | None = None
    srt_path: str | None = None
    text: str | None = None
    segment_count: int = 0
    error_message: str | None = None
    created_at: int = 0
    updated_at: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)
    segments: tuple[dict[str, Any], ...] = field(default_factory=tuple)
