import json
import re
from typing import Callable

from src.application.lesson_copilot.executor import Executor
from src.application.lesson_copilot.prompts import build_decision_prompt, build_tool_calling_system_prompt
from src.application.lesson_copilot.types import CopilotContext, CopilotRunResult, CopilotStep, ToolCall, ToolResult


class LessonCopilotAgent:
    def __init__(self, llm, executor: Executor, max_steps: int = 3) -> None:
        self.llm = llm
        self.executor = executor
        self.max_steps = max_steps

    def run(
        self,
        context: CopilotContext,
        user_message: str,
        on_step: Callable[[CopilotStep], None] | None = None,
    ) -> CopilotRunResult:
        if self._supports_native_tool_calling():
            try:
                return self._run_with_native_tool_calling(context, user_message, on_step=on_step)
            except Exception as exc:
                if not self._should_fallback_to_prompt_json(exc):
                    raise

        return self._run_with_prompt_json(context, user_message, on_step=on_step)

    def _run_with_native_tool_calling(
        self,
        context: CopilotContext,
        user_message: str,
        on_step: Callable[[CopilotStep], None] | None = None,
    ) -> CopilotRunResult:
        from llama_index.core.llms import ChatMessage, MessageRole

        tool_results: list[ToolResult] = []
        steps: list[CopilotStep] = []
        messages = [
            ChatMessage(role=MessageRole.SYSTEM, content=build_tool_calling_system_prompt(context)),
            ChatMessage(role=MessageRole.USER, content=user_message),
        ]
        tools = [tool.to_llamaindex_tool() for tool in self.executor.registry.list_tools()]

        for _ in range(self.max_steps):
            response = self.llm.chat_with_tools(
                tools=tools,
                chat_history=messages,
                allow_parallel_tool_calls=False,
            )
            tool_calls = self.llm.get_tool_calls_from_response(response, error_on_no_tool_call=False)

            if not tool_calls:
                answer = self._extract_chat_response_text(response) or self._fallback_answer(tool_results)
                self._append_step(steps, CopilotStep(action="final", final_answer=answer), on_step)
                return CopilotRunResult(
                    answer=answer,
                    steps=tuple(steps),
                    metadata={
                        "stopped_by": "final",
                        "step_count": len(steps),
                        "tool_protocol": "native",
                    },
                )

            messages.append(response.message)
            for selection in tool_calls:
                call = ToolCall(
                    name=selection.tool_name,
                    arguments=selection.tool_kwargs,
                )
                result = self.executor.execute(call)
                tool_results.append(result)
                self._append_step(
                    steps,
                    CopilotStep(
                        action="tool",
                        thought=self._native_tool_thought(call),
                        tool_name=call.name,
                        arguments=call.arguments,
                        tool_ok=result.ok,
                        tool_result=result.content if result.ok else None,
                        error=result.error,
                    ),
                    on_step,
                )
                messages.append(
                    ChatMessage(
                        role=MessageRole.TOOL,
                        content=self._serialize_tool_result(result),
                        additional_kwargs={"tool_call_id": selection.tool_id},
                    )
                )

        answer = self._fallback_answer(tool_results)
        self._append_step(
            steps,
            CopilotStep(
                action="final",
                thought="Reached the maximum tool steps; using the collected tool results to answer.",
                final_answer=answer,
            ),
            on_step,
        )
        return CopilotRunResult(
            answer=answer,
            steps=tuple(steps),
            metadata={
                "stopped_by": "max_steps",
                "step_count": len(steps),
                "tool_protocol": "native",
            },
        )

    def _run_with_prompt_json(
        self,
        context: CopilotContext,
        user_message: str,
        on_step: Callable[[CopilotStep], None] | None = None,
    ) -> CopilotRunResult:
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
                self._append_step(
                    steps,
                    CopilotStep(action="error", error=f"Failed to parse LLM decision JSON: {exc}"),
                    on_step,
                )
                answer = self._fallback_answer(tool_results)
                if not tool_results:
                    recovered = self._recover_answer_from_invalid_decision(raw_text)
                    if recovered:
                        answer = recovered
                self._append_step(steps, CopilotStep(action="final", final_answer=answer), on_step)
                return CopilotRunResult(
                    answer=answer,
                    steps=tuple(steps),
                    metadata={
                        "stopped_by": "parse_error",
                        "step_count": len(steps),
                        "parse_error": str(exc),
                        "tool_protocol": "prompt_json",
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
                self._append_step(
                    steps,
                    CopilotStep(
                        action="tool",
                        thought=thought,
                        tool_name=call.name,
                        arguments=call.arguments,
                        tool_ok=result.ok,
                        tool_result=result.content if result.ok else None,
                        error=result.error,
                    ),
                    on_step,
                )
                continue

            if action == "final":
                answer = str(decision.get("final_answer") or "").strip() or self._fallback_answer(tool_results)
                self._append_step(
                    steps,
                    CopilotStep(action="final", thought=thought, final_answer=answer),
                    on_step,
                )
                return CopilotRunResult(
                    answer=answer,
                    steps=tuple(steps),
                    metadata={
                        "stopped_by": "final",
                        "step_count": len(steps),
                        "tool_protocol": "prompt_json",
                    },
                )

            self._append_step(
                steps,
                CopilotStep(action="error", thought=thought, error=f"Unsupported action: {action or '<empty>'}"),
                on_step,
            )
            break

        answer = self._fallback_answer(tool_results)
        self._append_step(steps, CopilotStep(action="final", final_answer=answer), on_step)
        return CopilotRunResult(
            answer=answer,
            steps=tuple(steps),
            metadata={
                "stopped_by": "max_steps",
                "step_count": len(steps),
                "tool_protocol": "prompt_json",
            },
        )

    def _supports_native_tool_calling(self) -> bool:
        return callable(getattr(self.llm, "chat_with_tools", None)) and callable(
            getattr(self.llm, "get_tool_calls_from_response", None)
        )

    @staticmethod
    def _should_fallback_to_prompt_json(exc: Exception) -> bool:
        message = str(exc).lower()
        fallback_markers = (
            "tool",
            "function",
            "chat_with_tools",
            "tool_choice",
            "parallel_tool_calls",
            "unsupported",
            "not support",
            "not implemented",
        )
        return any(marker in message for marker in fallback_markers)

    def _parse_decision(self, text: str) -> dict:
        text = self._strip_code_fences(text).strip()

        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            text = text[start:end + 1]

        payload = json.loads(text)
        return payload

    @staticmethod
    def _extract_chat_response_text(response) -> str:
        message = getattr(response, "message", None)
        content = getattr(message, "content", "") if message is not None else ""
        return str(content or "").strip()

    @staticmethod
    def _serialize_tool_result(result: ToolResult) -> str:
        payload = result.content if result.ok else {"error": result.error or "tool execution failed"}
        return json.dumps(payload, ensure_ascii=False, default=str)

    @staticmethod
    def _native_tool_thought(call: ToolCall) -> str:
        descriptions = {
            "get_lesson_note": "Checking whether an existing lesson note already answers the request.",
            "generate_lesson_note": "Generating or refreshing the lesson note because existing notes are not enough.",
            "delete_lesson_note": "Deleting the lesson note because the user explicitly requested removal.",
            "get_lesson_transcripts": "Reading raw lesson transcripts for additional classroom context.",
            "get_refined_lesson_transcripts": "Reading refined transcripts to get cleaner classroom context.",
            "get_lesson_videos": "Checking processed classroom videos for relevant replay or subtitle context.",
            "get_session_assets": "Checking assets uploaded in the current session.",
            "search_available_assets": "Searching indexed uploaded materials to find a relevant document source.",
            "get_lesson_messages": "Checking recent lesson chat messages for conversation context.",
            "generate_lesson_quiz": "Generating quiz questions because the user asked for practice or self-check items.",
            "generate_lesson_summary": "Generating a structured lesson summary from the current session context.",
            "query_lesson_knowledge": "Retrieving relevant knowledge from the lesson or selected materials before answering.",
        }
        return descriptions.get(call.name, f"Calling {call.name} to gather information needed for the answer.")

    @staticmethod
    def _append_step(
        steps: list[CopilotStep],
        step: CopilotStep,
        on_step: Callable[[CopilotStep], None] | None,
    ) -> None:
        steps.append(step)
        if on_step is not None:
            on_step(step)

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
