from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class LessonConcept:
    term: str
    definition: str


@dataclass(slots=True)
class LessonSummary:
    session_id: str
    course_id: str
    lesson_id: str
    subject: str
    summary: str
    key_points: list[str] = field(default_factory=list)
    review_items: list[str] = field(default_factory=list)
    important_terms: list[LessonConcept] = field(default_factory=list)
    metadata: dict[str, object] = field(default_factory=dict)
