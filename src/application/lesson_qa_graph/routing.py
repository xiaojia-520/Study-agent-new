from __future__ import annotations

from enum import Enum


class LessonQaRoute(str, Enum):
    ANSWER = "answer"
    SUMMARY = "summary"
    QUIZ = "quiz"
    NO_CONTEXT = "no_context"


def default_route() -> LessonQaRoute:
    return LessonQaRoute.ANSWER

