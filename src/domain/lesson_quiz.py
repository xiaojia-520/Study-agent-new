from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class QuizQuestion:
    question: str
    question_type: str
    answer: str
    explanation: str
    options: list[str] = field(default_factory=list)


@dataclass(slots=True)
class LessonQuiz:
    session_id: str
    course_id: str
    lesson_id: str
    subject: str
    questions: list[QuizQuestion] = field(default_factory=list)
    metadata: dict[str, object] = field(default_factory=dict)
