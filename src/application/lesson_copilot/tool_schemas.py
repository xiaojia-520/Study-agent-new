from typing import Any, Protocol

from src.application.lesson_copilot.tool_registry import Tool, ToolRegistry


class LessonNoteServiceLike(Protocol):
    def get_latest_note(self, course_id: str, lesson_id: str) -> Any:
        ...

    def generate_note(self, course_id: str, lesson_id: str) -> Any:
        ...

    def get_lesson_transcripts(self, course_id: str, lesson_id: str, *, limit: int = 12) -> Any:
        ...

    def get_refined_lesson_transcripts(self, course_id: str, lesson_id: str, *, limit: int = 12) -> Any:
        ...

    def get_lesson_videos(self, course_id: str, lesson_id: str, *, limit: int = 6) -> Any:
        ...

    def get_session_assets(self, session_id: str, *, limit: int = 6) -> Any:
        ...

    def get_lesson_messages(self, course_id: str, lesson_id: str, *, limit: int = 10) -> Any:
        ...

    def generate_quiz(self, session_id: str, *, focus: str | None = None, question_count: int | None = None) -> Any:
        ...

    def generate_summary(self, session_id: str, *, focus: str | None = None, max_items: int | None = None) -> Any:
        ...

    def query_lesson_knowledge(
        self,
        session_id: str,
        *,
        query: str,
        scope: str = "current_lesson",
        top_k: int = 5,
        with_llm: bool = False,
    ) -> Any:
        ...


def build_tools(
    note_service: LessonNoteServiceLike,
    course_id: str,
    lesson_id: str,
    *,
    session_id: str | None = None,
) -> ToolRegistry:
    registry = ToolRegistry()

    registry.register(
        Tool(
            name="get_lesson_note",
            description="Get the latest lesson note for the current lesson. No arguments.",
            handler=lambda args: note_service.get_latest_note(course_id, lesson_id),
        )
    )

    registry.register(
        Tool(
            name="generate_lesson_note",
            description='Generate or refresh the lesson note. Optional arguments: {"focus": string, "max_items": integer, "force": boolean}.',
            handler=lambda args: note_service.generate_note(
                course_id,
                lesson_id,
                focus=_optional_text(args.get("focus")),
                max_items=_optional_int(args.get("max_items")),
                force=_optional_bool(args.get("force")),
            ),
        )
    )

    registry.register(
        Tool(
            name="get_lesson_transcripts",
            description='Get transcript records for the current lesson. Optional arguments: {"limit": integer}.',
            handler=lambda args: note_service.get_lesson_transcripts(
                course_id,
                lesson_id,
                limit=_positive_int(args.get("limit"), default=12),
            ),
        )
    )

    registry.register(
        Tool(
            name="get_refined_lesson_transcripts",
            description='Get refined transcript records for the current lesson. Optional arguments: {"limit": integer}.',
            handler=lambda args: note_service.get_refined_lesson_transcripts(
                course_id,
                lesson_id,
                limit=_positive_int(args.get("limit"), default=12),
            ),
        )
    )

    registry.register(
        Tool(
            name="get_lesson_videos",
            description='Get processed classroom videos for the current lesson. Optional arguments: {"limit": integer}.',
            handler=lambda args: note_service.get_lesson_videos(
                course_id,
                lesson_id,
                limit=_positive_int(args.get("limit"), default=6),
            ),
        )
    )

    registry.register(
        Tool(
            name="get_session_assets",
            description='Get uploaded lesson assets from the current session. Requires a valid session context. Optional arguments: {"limit": integer}.',
            handler=lambda args: note_service.get_session_assets(
                session_id or "",
                limit=_positive_int(args.get("limit"), default=6),
            ),
        )
    )

    registry.register(
        Tool(
            name="get_lesson_messages",
            description='Get recent chat messages for the current lesson. Optional arguments: {"limit": integer}.',
            handler=lambda args: note_service.get_lesson_messages(
                course_id,
                lesson_id,
                limit=_positive_int(args.get("limit"), default=10),
            ),
        )
    )

    registry.register(
        Tool(
            name="generate_lesson_quiz",
            description='Generate quiz questions from the current session transcript. Requires a valid session context. Optional arguments: {"focus": string, "question_count": integer}.',
            handler=lambda args: note_service.generate_quiz(
                session_id or "",
                focus=_optional_text(args.get("focus")),
                question_count=_optional_int(args.get("question_count")),
            ),
        )
    )

    registry.register(
        Tool(
            name="generate_lesson_summary",
            description='Generate a structured lesson summary from the current session transcript. Requires a valid session context. Optional arguments: {"focus": string, "max_items": integer}.',
            handler=lambda args: note_service.generate_summary(
                session_id or "",
                focus=_optional_text(args.get("focus")),
                max_items=_optional_int(args.get("max_items")),
            ),
        )
    )

    registry.register(
        Tool(
            name="query_lesson_knowledge",
            description='Query the lesson knowledge base for this lesson or course. Requires a valid session context. Arguments: {"query": string, "scope": "current_lesson|course_all|course_history|global" (optional), "top_k": integer (optional), "with_llm": boolean (optional)}.',
            handler=lambda args: note_service.query_lesson_knowledge(
                session_id or "",
                query=_required_text(args.get("query"), "query"),
                scope=_optional_text(args.get("scope")) or "current_lesson",
                top_k=_positive_int(args.get("top_k"), default=5),
                with_llm=_optional_bool(args.get("with_llm")),
            ),
        )
    )

    return registry


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).strip().split())
    return text or None


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _positive_int(value: Any, *, default: int) -> int:
    parsed = _optional_int(value)
    if parsed is None or parsed <= 0:
        return default
    return parsed


def _optional_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "y", "on"}:
            return True
        if normalized in {"0", "false", "no", "n", "off"}:
            return False
    return bool(value)


def _required_text(value: Any, field_name: str) -> str:
    text = _optional_text(value)
    if not text:
        raise ValueError(f"{field_name} is required")
    return text
