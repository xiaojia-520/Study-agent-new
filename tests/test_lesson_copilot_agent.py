import unittest
from types import SimpleNamespace

from llama_index.core.llms import ChatMessage, MessageRole

from src.application.lesson_copilot import (
    CopilotContext,
    Executor,
    LessonCopilotAgent,
    ToolRegistry,
    build_tools,
)


class FakeLessonNoteService:
    def __init__(self) -> None:
        self.note = None

    def get_latest_note(self, course_id: str, lesson_id: str):
        return self.note

    def generate_note(self, course_id: str, lesson_id: str, **kwargs):
        self.note = {
            "course_id": course_id,
            "lesson_id": lesson_id,
            "summary": "Generated from fake service.",
            "status": "done",
        }
        return self.note


class FakeLLM:
    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)

    def complete(self, prompt: str):
        if not self.responses:
            raise AssertionError("unexpected llm call")
        return SimpleNamespace(text=self.responses.pop(0))


class FakeToolCallingLLM:
    def __init__(self) -> None:
        self.calls = 0
        self.tool_names = []

    def chat_with_tools(self, tools, chat_history, allow_parallel_tool_calls=False):
        self.calls += 1
        self.tool_names = [tool.metadata.name for tool in tools]
        if self.calls == 1:
            return SimpleNamespace(
                message=ChatMessage(role=MessageRole.ASSISTANT, content=""),
                tool_calls=[
                    SimpleNamespace(
                        tool_id="call-1",
                        tool_name="get_lesson_note",
                        tool_kwargs={},
                    )
                ],
            )
        return SimpleNamespace(
            message=ChatMessage(
                role=MessageRole.ASSISTANT,
                content="This lesson already has a note: Existing lesson note.",
            ),
            tool_calls=[],
        )

    def get_tool_calls_from_response(self, response, error_on_no_tool_call=True):
        return response.tool_calls

    def complete(self, prompt: str):
        raise AssertionError("prompt JSON fallback should not be used")


class LessonCopilotAgentTests(unittest.TestCase):
    def test_package_import_and_build_tools(self) -> None:
        registry = build_tools(FakeLessonNoteService(), "web-course", "lesson-1")

        self.assertIsInstance(registry, ToolRegistry)
        self.assertEqual(registry.get("get_lesson_note").name, "get_lesson_note")
        self.assertEqual(registry.get("generate_lesson_note").name, "generate_lesson_note")
        self.assertEqual(registry.get("get_lesson_transcripts").name, "get_lesson_transcripts")
        self.assertEqual(registry.get("query_lesson_knowledge").name, "query_lesson_knowledge")

    def test_agent_uses_native_tool_calling_when_available(self) -> None:
        note_service = FakeLessonNoteService()
        note_service.note = {
            "course_id": "web-course",
            "lesson_id": "lesson-1",
            "summary": "Existing lesson note.",
            "status": "done",
        }
        registry = build_tools(note_service, "web-course", "lesson-1")
        llm = FakeToolCallingLLM()
        agent = LessonCopilotAgent(llm, Executor(registry))

        result = agent.run(
            CopilotContext(course_id="web-course", lesson_id="lesson-1"),
            "Help me review this lesson.",
        )

        self.assertEqual(result.answer, "This lesson already has a note: Existing lesson note.")
        self.assertEqual(result.metadata["tool_protocol"], "native")
        self.assertIn("get_lesson_note", llm.tool_names)
        self.assertEqual(result.steps[0].tool_name, "get_lesson_note")
        self.assertTrue(result.steps[0].tool_ok)

    def test_agent_generates_note_via_registry(self) -> None:
        registry = build_tools(FakeLessonNoteService(), "web-course", "lesson-1")
        llm = FakeLLM(
            [
                '{"action":"tool","thought":"Check whether a note already exists first.","tool_name":"get_lesson_note","arguments":{}}',
                '{"action":"tool","thought":"No note found, so generate one now.","tool_name":"generate_lesson_note","arguments":{}}',
                '{"action":"final","thought":"The note is ready, so I can answer directly.","final_answer":"I just generated a lesson note: Generated from fake service."}',
            ]
        )
        agent = LessonCopilotAgent(llm, Executor(registry))

        result = agent.run(
            CopilotContext(course_id="web-course", lesson_id="lesson-1"),
            "Help me review this lesson.",
        )

        self.assertEqual(result.answer, "I just generated a lesson note: Generated from fake service.")
        self.assertEqual(result.steps[0].thought, "Check whether a note already exists first.")
        self.assertEqual(result.steps[1].tool_name, "generate_lesson_note")

    def test_agent_falls_back_when_llm_returns_invalid_json(self) -> None:
        registry = build_tools(FakeLessonNoteService(), "web-course", "lesson-1")
        llm = FakeLLM(
            [
                '{"action":"tool","tool_name":"get_lesson_note","arguments":{}}',
                '{"action":"tool","tool_name":"generate_lesson_note","arguments":{}}',
                '{"action":"final","final_answer":"I just generated a lesson note: Generated from fake service.',
            ]
        )
        agent = LessonCopilotAgent(llm, Executor(registry))

        result = agent.run(
            CopilotContext(course_id="web-course", lesson_id="lesson-1"),
            "Help me review this lesson.",
        )

        self.assertEqual(result.answer, "Generated from fake service.")
        self.assertEqual(result.metadata["stopped_by"], "parse_error")
        self.assertEqual(result.steps[-1].final_answer, "Generated from fake service.")


if __name__ == "__main__":
    unittest.main()
