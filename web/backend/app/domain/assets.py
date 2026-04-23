from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class LessonAsset:
    id: int
    asset_id: str
    session_id: str
    course_id: str | None
    lesson_id: str | None
    subject: str | None
    file_name: str
    file_path: str
    file_size: int
    media_type: str
    status: str
    batch_id: str | None = None
    mineru_state: str | None = None
    full_zip_url: str | None = None
    result_dir: str | None = None
    markdown_path: str | None = None
    record_count: int = 0
    indexed_at: int | None = None
    error_message: str | None = None
    created_at: int = 0
    updated_at: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)
