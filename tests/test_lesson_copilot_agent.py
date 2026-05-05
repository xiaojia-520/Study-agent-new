import unittest
from types import SimpleNamespace

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


class LessonCopilotAgentTests(unittest.TestCase):
    def test_package_import_and_build_tools(self) -> None:
        registry = build_tools(FakeLessonNoteService(), "web-course", "lesson-1")

        self.assertIsInstance(registry, ToolRegistry)
        self.assertEqual(registry.get("get_lesson_note").name, "get_lesson_note")
        self.assertEqual(registry.get("generate_lesson_note").name, "generate_lesson_note")
        self.assertEqual(registry.get("get_lesson_transcripts").name, "get_lesson_transcripts")
        self.assertEqual(registry.get("query_lesson_knowledge").name, "query_lesson_knowledge")

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
