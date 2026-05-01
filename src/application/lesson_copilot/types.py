from dataclasses import dataclass
from typing import Any, Mapping

@dataclass(frozen=True)
class CopilotContext:
    course_id: str
    lesson_id: str
    session_id: str | None = None

@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: Mapping[str, Any]

@dataclass(frozen=True)
class ToolResult:
    name: str
    ok: bool
    content: Any = None
    error: str | None = None


@dataclass(frozen=True)
class CopilotStep:
    action: str
    tool_name: str | None = None
    arguments: Mapping[str, Any] | None = None
    tool_ok: bool | None = None
    tool_result: Any = None
    error: str | None = None
    final_answer: str | None = None


@dataclass(frozen=True)
class CopilotRunResult:
    answer: str
    steps: tuple[CopilotStep, ...]
    metadata: Mapping[str, Any]
