from typing import Any, Protocol

from pydantic import BaseModel, Field

from src.application.lesson_copilot.tool_registry import Tool, ToolRegistry


class EmptyToolInput(BaseModel):
    pass


class GenerateLessonNoteInput(BaseModel):
    focus: str | None = Field(default=None, description="Optional review focus.")
    max_items: int | None = Field(default=None, description="Optional maximum number of note items.")
    force: bool = Field(default=False, description="Whether to regenerate an existing note.")


class DeleteLessonNoteInput(BaseModel):
    note_id: str | None = Field(default=None, description="Optional note_id to delete. If omitted, deletes the latest note for the current lesson.")


class LimitInput(BaseModel):
    limit: int | None = Field(default=None, description="Maximum number of items to return.")


class SearchAvailableAssetsInput(BaseModel):
    query: str | None = Field(default=None, description="Optional keyword used to match available uploaded assets.")
    limit: int | None = Field(default=None, description="Maximum number of assets to return.")


class GenerateLessonQuizInput(BaseModel):
    focus: str | None = Field(default=None, description="Optional quiz focus.")
    question_count: int | None = Field(default=None, description="Optional number of questions to generate.")


class GenerateLessonSummaryInput(BaseModel):
    focus: str | None = Field(default=None, description="Optional summary focus.")
    max_items: int | None = Field(default=None, description="Optional maximum number of summary items.")


class QueryLessonKnowledgeInput(BaseModel):
    query: str = Field(description="Question or search query about the lesson.")
    scope: str | None = Field(
        default="current_lesson",
        description="Retrieval scope: current_lesson, course_all, course_history, or global.",
    )
    top_k: int | None = Field(default=None, description="Maximum number of retrieval results.")
    with_llm: bool = Field(default=False, description="Whether the RAG tool should synthesize an answer with an LLM.")
    asset_ids: list[str] | None = Field(
        default=None,
        description="Optional uploaded asset IDs to query directly. Use IDs returned by search_available_assets.",
    )


class LessonNoteServiceLike(Protocol):
    def get_latest_note(self, course_id: str, lesson_id: str) -> Any:
        ...

    def generate_note(self, course_id: str, lesson_id: str) -> Any:
        ...

    def delete_lesson_note(self, course_id: str, lesson_id: str, *, note_id: str | None = None) -> Any:
        ...

    def get_lesson_transcripts(self, course_id: str, lesson_id: str, *, limit: int = 12) -> Any:
        ...

    def get_refined_lesson_transcripts(self, course_id: str, lesson_id: str, *, limit: int = 12) -> Any:
        ...

    def get_lesson_videos(self, course_id: str, lesson_id: str, *, limit: int = 6) -> Any:
        ...

    def get_session_assets(self, session_id: str, *, limit: int = 6) -> Any:
        ...

    def search_available_assets(self, *, query: str | None = None, limit: int = 6) -> Any:
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
        asset_ids: list[str] | None = None,
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
            fn_schema=EmptyToolInput,
            handler=lambda args: note_service.get_latest_note(course_id, lesson_id),
        )
    )

    registry.register(
        Tool(
            name="generate_lesson_note",
            description='Generate or refresh the lesson note. Optional arguments: {"focus": string, "max_items": integer, "force": boolean}.',
            fn_schema=GenerateLessonNoteInput,
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
            name="delete_lesson_note",
            description='Delete a lesson note. Optional arguments: {"note_id": string}. If note_id is omitted, deletes the latest note for the current lesson. Use only when the user explicitly asks to delete/remove a note.',
            fn_schema=DeleteLessonNoteInput,
            handler=lambda args: note_service.delete_lesson_note(
                course_id,
                lesson_id,
                note_id=_optional_text(args.get("note_id")),
            ),
        )
    )

    registry.register(
        Tool(
            name="get_lesson_transcripts",
            description='Get transcript records for the current lesson. Optional arguments: {"limit": integer}.',
            fn_schema=LimitInput,
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
            fn_schema=LimitInput,
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
            fn_schema=LimitInput,
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
            fn_schema=LimitInput,
            handler=lambda args: note_service.get_session_assets(
                session_id or "",
                limit=_positive_int(args.get("limit"), default=6),
            ),
        )
    )

    registry.register(
        Tool(
            name="search_available_assets",
            description='Search available indexed uploaded assets/books that can be used for document RAG. Optional arguments: {"query": string, "limit": integer}. Use this before query_lesson_knowledge when the user asks about uploaded books or materials but no asset_id is known.',
            fn_schema=SearchAvailableAssetsInput,
            handler=lambda args: note_service.search_available_assets(
                query=_optional_text(args.get("query")),
                limit=_positive_int(args.get("limit"), default=6),
            ),
        )
    )

    registry.register(
        Tool(
            name="get_lesson_messages",
            description='Get recent chat messages for the current lesson. Optional arguments: {"limit": integer}.',
            fn_schema=LimitInput,
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
            fn_schema=GenerateLessonQuizInput,
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
            fn_schema=GenerateLessonSummaryInput,
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
            description='Query the lesson knowledge base or selected uploaded assets. Requires a valid session context. Arguments: {"query": string, "scope": "current_lesson|course_all|course_history|global" (optional), "top_k": integer (optional), "with_llm": boolean (optional), "asset_ids": string[] (optional)}.',
            fn_schema=QueryLessonKnowledgeInput,
            handler=lambda args: note_service.query_lesson_knowledge(
                session_id or "",
                query=_required_text(args.get("query"), "query"),
                scope=_optional_text(args.get("scope")) or "current_lesson",
                top_k=_positive_int(args.get("top_k"), default=5),
                with_llm=_optional_bool(args.get("with_llm")),
                asset_ids=_optional_str_list(args.get("asset_ids")),
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


def _optional_str_list(value: Any) -> list[str] | None:
    if value is None or not isinstance(value, list):
        return None
    items: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = str(item or "").strip()
        if text and text not in seen:
            seen.add(text)
            items.append(text)
    return items or None


def _required_text(value: Any, field_name: str) -> str:
    text = _optional_text(value)
    if not text:
        raise ValueError(f"{field_name} is required")
    return text
