from __future__ import annotations

from typing import Any

from src.application.lesson_copilot import CopilotContext, Executor, LessonCopilotAgent, build_tools
from src.application.lesson_copilot.adapter import LessonCopilotAdapter
from src.application.lesson_copilot.types import CopilotRunResult, CopilotStep
from src.application.rag.runtime import build_default_llm


class LessonCopilotService:
    def __init__(self, *, llm_factory=build_default_llm, max_steps: int = 3) -> None:
        self.llm_factory = llm_factory
        self.max_steps = max_steps
        self._llm = None
        self._adapter = LessonCopilotAdapter()

    def run(
        self,
        *,
        course_id: str,
        lesson_id: str,
        message: str,
        session_id: str | None = None,
    ) -> CopilotRunResult:
        llm = self._get_llm()
        agent = LessonCopilotAgent(
            llm=llm,
            executor=Executor(build_tools(self._adapter, course_id, lesson_id, session_id=session_id)),
            max_steps=self.max_steps,
        )
        return agent.run(
            CopilotContext(course_id=course_id, lesson_id=lesson_id, session_id=session_id),
            message,
        )

    def close(self) -> None:
        self._llm = None

    def _get_llm(self):
        if self._llm is None:
            self._llm = self.llm_factory()
        if self._llm is None:
            raise ValueError("LLM is not enabled. Set RAG_ENABLE_LLM=true and configure DeepSeek first.")
        return self._llm


def lesson_copilot_step_to_dict(step: CopilotStep) -> dict[str, Any]:
    return {
        "action": step.action,
        "thought": step.thought,
        "tool_name": step.tool_name,
        "arguments": dict(step.arguments or {}),
        "tool_ok": step.tool_ok,
        "tool_result": _compact_tool_result(step.tool_result),
        "error": step.error,
        "final_answer": step.final_answer,
    }


def lesson_copilot_result_to_dict(result: CopilotRunResult) -> dict[str, Any]:
    return {
        "answer": result.answer,
        "steps": [lesson_copilot_step_to_dict(step) for step in result.steps],
        "metadata": dict(result.metadata),
    }


def _compact_tool_result(value: Any) -> Any:
    if not isinstance(value, dict):
        return value
    payload: dict[str, Any] = {}
    for key in (
        "note_id",
        "status",
        "title",
        "summary",
        "overview",
        "count",
        "query",
        "answer",
        "course_id",
        "lesson_id",
        "session_id",
        "error_message",
    ):
        if key in value and value[key] is not None:
            payload[key] = value[key]
    for key in ("note", "items", "questions", "results", "citations", "key_points", "review_items", "important_terms"):
        item = value.get(key)
        if isinstance(item, list):
            payload[f"{key}_count"] = len(item)
            payload[key] = item[:3]
        elif isinstance(item, dict) and key == "note":
            overview = item.get("overview")
            if overview is not None:
                payload.setdefault("overview", overview)
    return payload or value


lesson_copilot_service = LessonCopilotService()
