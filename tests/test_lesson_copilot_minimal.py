import unittest
from types import SimpleNamespace

from src.application.lesson_copilot import (
    CopilotContext,
    Executor,
    LessonCopilotAgent,
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
            "summary": "This lesson covered HTTP statelessness and the role of sessions.",
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


class LessonCopilotMinimalTests(unittest.TestCase):
    def test_agent_reads_existing_note_before_generating(self) -> None:
        note_service = FakeLessonNoteService()
        note_service.note = {
            "course_id": "web-course",
            "lesson_id": "lesson-1",
            "summary": "Existing lesson note.",
            "status": "done",
        }
        registry = build_tools(note_service, "web-course", "lesson-1")
        llm = FakeLLM(
            [
                '{"action":"tool","tool_name":"get_lesson_note","arguments":{}}',
                '{"action":"final","final_answer":"This lesson already has a note: Existing lesson note."}',
            ]
        )
        agent = LessonCopilotAgent(llm, Executor(registry))

        result = agent.run(
            CopilotContext(course_id="web-course", lesson_id="lesson-1"),
            "Help me review this lesson.",
        )

        self.assertEqual(result.answer, "This lesson already has a note: Existing lesson note.")
        self.assertEqual(result.metadata["stopped_by"], "final")
        self.assertEqual(result.steps[0].tool_name, "get_lesson_note")

    def test_agent_generates_note_when_missing(self) -> None:
        note_service = FakeLessonNoteService()
        registry = build_tools(note_service, "web-course", "lesson-1")
        llm = FakeLLM(
            [
                '{"action":"tool","tool_name":"get_lesson_note","arguments":{}}',
                '{"action":"tool","tool_name":"generate_lesson_note","arguments":{}}',
                '{"action":"final","final_answer":"I just generated a lesson note: This lesson covered HTTP statelessness and the role of sessions."}',
            ]
        )
        agent = LessonCopilotAgent(llm, Executor(registry))

        result = agent.run(
            CopilotContext(course_id="web-course", lesson_id="lesson-1"),
            "Help me review this lesson.",
        )

        self.assertEqual(
            result.answer,
            "I just generated a lesson note: This lesson covered HTTP statelessness and the role of sessions.",
        )
        self.assertEqual(result.steps[1].tool_name, "generate_lesson_note")
        self.assertIsNotNone(note_service.note)
        self.assertEqual(note_service.note["status"], "done")


if __name__ == "__main__":
    unittest.main()
