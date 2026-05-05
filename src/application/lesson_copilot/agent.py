import json
import re

from src.application.lesson_copilot.executor import Executor
from src.application.lesson_copilot.prompts import build_decision_prompt
from src.application.lesson_copilot.types import CopilotContext, CopilotRunResult, CopilotStep, ToolCall, ToolResult


class LessonCopilotAgent:
    def __init__(self, llm, executor: Executor, max_steps: int = 3) -> None:
        self.llm = llm
        self.executor = executor
        self.max_steps = max_steps

    def run(self, context: CopilotContext, user_message: str) -> CopilotRunResult:
        tool_results: list[ToolResult] = []
        steps: list[CopilotStep] = []

        for _ in range(self.max_steps):
            prompt = build_decision_prompt(
                context=context,
                user_message=user_message,
                tools=self.executor.registry.list_tools(),
                tool_results=tool_results,
            )
            response = self.llm.complete(prompt)
            raw_text = getattr(response, "text", str(response))
            try:
                decision = self._parse_decision(raw_text)
            except (json.JSONDecodeError, ValueError) as exc:
                steps.append(CopilotStep(action="error", error=f"Failed to parse LLM decision JSON: {exc}"))
                answer = self._fallback_answer(tool_results)
                if not tool_results:
                    recovered = self._recover_answer_from_invalid_decision(raw_text)
                    if recovered:
                        answer = recovered
                steps.append(CopilotStep(action="final", final_answer=answer))
                return CopilotRunResult(
                    answer=answer,
                    steps=tuple(steps),
                    metadata={
                        "stopped_by": "parse_error",
                        "step_count": len(steps),
                        "parse_error": str(exc),
                    },
                )
            action = str(decision.get("action") or "").strip().lower()
            thought = self._normalize_optional_text(decision.get("thought"))

            if action == "tool":
                call = ToolCall(
                    name=decision["tool_name"],
                    arguments=decision.get("arguments", {}),
                )
                result = self.executor.execute(call)
                tool_results.append(result)
                steps.append(
                    CopilotStep(
                        action="tool",
                        thought=thought,
                        tool_name=call.name,
                        arguments=call.arguments,
                        tool_ok=result.ok,
                        tool_result=result.content if result.ok else None,
                        error=result.error,
                    )
                )
                continue

            if action == "final":
                answer = str(decision.get("final_answer") or "").strip() or self._fallback_answer(tool_results)
                steps.append(CopilotStep(action="final", thought=thought, final_answer=answer))
                return CopilotRunResult(
                    answer=answer,
                    steps=tuple(steps),
                    metadata={
                        "stopped_by": "final",
                        "step_count": len(steps),
                    },
                )

            steps.append(CopilotStep(action="error", thought=thought, error=f"Unsupported action: {action or '<empty>'}"))
            break

        answer = self._fallback_answer(tool_results)
        steps.append(CopilotStep(action="final", final_answer=answer))
        return CopilotRunResult(
            answer=answer,
            steps=tuple(steps),
            metadata={
                "stopped_by": "max_steps",
                "step_count": len(steps),
            },
        )

    def _parse_decision(self, text: str) -> dict:
        text = self._strip_code_fences(text).strip()

        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            text = text[start:end + 1]

        payload = json.loads(text)
        return payload

    @staticmethod
    def _strip_code_fences(text: str) -> str:
        stripped = text.strip()
        if stripped.startswith("```"):
            lines = stripped.splitlines()
            if len(lines) >= 3:
                return "\n".join(lines[1:-1]).strip()
        return stripped

    @classmethod
    def _recover_answer_from_invalid_decision(cls, text: str) -> str:
        stripped = cls._strip_code_fences(text).strip()
        if not stripped:
            return ""

        final_answer_match = re.search(r'"final_answer"\s*:\s*"', stripped)
        if final_answer_match:
            tail = stripped[final_answer_match.end() :]
            end_candidates = [
                index
                for index in (
                    tail.find('","'),
                    tail.find('"}'),
                    tail.find('",\n'),
                    tail.find('"\n}'),
                )
                if index >= 0
            ]
            end = min(end_candidates) if end_candidates else len(tail)
            candidate = tail[:end].strip().rstrip('"').rstrip("}").strip()
            return candidate

        if not stripped.startswith("{"):
            return stripped

        return ""

    @staticmethod
    def _fallback_answer(tool_results: list[ToolResult]) -> str:
        for item in reversed(tool_results):
            if not item.ok:
                continue
            content = item.content
            if isinstance(content, dict):
                summary = str(content.get("summary") or "").strip()
                if summary:
                    return summary
                note_payload = content.get("note")
                if isinstance(note_payload, dict):
                    overview = str(note_payload.get("overview") or "").strip()
                    if overview:
                        return overview
        return "I could not complete the lesson request within the allowed steps."

    @staticmethod
    def _normalize_optional_text(value) -> str | None:
        text = str(value or "").strip()
        return text or None
