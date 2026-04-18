import unittest
from types import SimpleNamespace

from web.backend.app.domain.session import RealtimeSession
from web.backend.app.services.session_lesson_quiz_service import SessionLessonQuizService


class FakeLLM:
    def __init__(self, responses):
        self.responses = list(responses)
        self.prompts = []

    def complete(self, prompt: str):
        self.prompts.append(prompt)
        if not self.responses:
            raise AssertionError("unexpected llm call")
        return SimpleNamespace(text=self.responses.pop(0))


class SessionLessonQuizServiceTests(unittest.TestCase):
    def test_generate_quiz_returns_structured_questions(self) -> None:
        llm = FakeLLM(
            [
                """
                {
                  "questions": [
                    {
                      "question": "What does HTTP being stateless mean?",
                      "question_type": "short_answer",
                      "options": [],
                      "answer": "The server does not remember previous requests by default.",
                      "explanation": "The lesson states that HTTP is stateless."
                    },
                    {
                      "question": "Which browser-side item commonly carries the session identifier?",
                      "question_type": "multiple_choice",
                      "options": ["Cookie", "HTML title", "DNS record", "CSS selector"],
                      "answer": "Cookie",
                      "explanation": "The transcript says the browser stores the session identifier in a cookie."
                    }
                  ]
                }
                """
            ]
        )
        service = SessionLessonQuizService(
            runtime_factory=lambda: SimpleNamespace(llm=llm),
            runtime_closer=lambda: None,
            session_getter=lambda _: self._session(),
            transcript_loader=lambda session, session_id: self._transcript_items(),
        )

        result = service.generate_quiz(
            session_id="session-a",
            focus="Focus on HTTP and cookies",
            question_count=4,
        )

        self.assertEqual(result.session_id, "session-a")
        self.assertEqual(result.course_id, "web-course")
        self.assertEqual(result.lesson_id, "lesson-1")
        self.assertEqual(len(result.questions), 2)
        self.assertEqual(result.questions[0].question_type, "short_answer")
        self.assertEqual(result.questions[1].question_type, "multiple_choice")
        self.assertEqual(result.questions[1].options[0], "Cookie")
        self.assertEqual(result.metadata["question_count_requested"], 4)
        self.assertEqual(result.metadata["question_count_generated"], 2)
        self.assertIn("Focus instruction: Focus on HTTP and cookies", llm.prompts[0])

    def test_generate_quiz_merges_multiple_chunks(self) -> None:
        llm = FakeLLM(
            [
                '{"questions":[{"question":"Chunk one question","question_type":"short_answer","options":[],"answer":"Chunk one answer","explanation":"Chunk one explanation"}]}',
                '{"questions":[{"question":"Chunk two question","question_type":"multiple_choice","options":["Cookie","DNS"],"answer":"Cookie","explanation":"Chunk two explanation"}]}',
                '{"questions":[{"question":"Merged question one","question_type":"short_answer","options":[],"answer":"Merged answer one","explanation":"Merged explanation one"},{"question":"Merged question two","question_type":"multiple_choice","options":["Cookie","DNS","HTML"],"answer":"Cookie","explanation":"Merged explanation two"}]}',
            ]
        )
        transcript_items = [
            {
                "session_id": "session-a",
                "course_id": "web-course",
                "lesson_id": "lesson-1",
                "subject": "web",
                "clean_text": "HTTP is stateless.",
            },
            {
                "session_id": "session-a",
                "course_id": "web-course",
                "lesson_id": "lesson-1",
                "subject": "web",
                "clean_text": "Sessions restore state using cookies.",
            },
        ]
        service = SessionLessonQuizService(
            runtime_factory=lambda: SimpleNamespace(llm=llm),
            runtime_closer=lambda: None,
            session_getter=lambda _: self._session(),
            transcript_loader=lambda session, session_id: transcript_items,
            chunk_char_limit=40,
        )

        result = service.generate_quiz(session_id="session-a", question_count=3)

        self.assertEqual(len(result.questions), 2)
        self.assertEqual(result.questions[0].question, "Merged question one")
        self.assertEqual(result.metadata["chunk_count"], 2)
        self.assertEqual(len(llm.prompts), 3)
        self.assertIn("Merge the chunk-level questions", llm.prompts[-1])

    def test_generate_quiz_uses_transcript_context_when_session_is_missing(self) -> None:
        llm = FakeLLM(
            [
                '{"questions":[{"question":"Archived question","question_type":"short_answer","options":[],"answer":"Archived answer","explanation":"Archived explanation"}]}'
            ]
        )
        transcript_items = [
            {
                "session_id": "orphan-session",
                "course_id": "archived-course",
                "lesson_id": "archived-lesson",
                "subject": "archived-subject",
                "clean_text": "Archived transcript line.",
            }
        ]
        service = SessionLessonQuizService(
            runtime_factory=lambda: SimpleNamespace(llm=llm),
            runtime_closer=lambda: None,
            session_getter=lambda _: None,
            transcript_loader=lambda session, session_id: transcript_items,
        )

        result = service.generate_quiz(session_id="orphan-session")

        self.assertEqual(result.course_id, "archived-course")
        self.assertEqual(result.lesson_id, "archived-lesson")
        self.assertEqual(result.subject, "archived-subject")
        self.assertEqual(result.questions[0].question, "Archived question")

    @staticmethod
    def _session() -> RealtimeSession:
        return RealtimeSession(
            session_id="session-a",
            course_id="web-course",
            lesson_id="lesson-1",
            subject="web",
            created_at=100,
            updated_at=100,
        )

    @staticmethod
    def _transcript_items():
        return [
            {
                "session_id": "session-a",
                "course_id": "web-course",
                "lesson_id": "lesson-1",
                "subject": "web",
                "clean_text": "HTTP is stateless by default.",
            },
            {
                "session_id": "session-a",
                "course_id": "web-course",
                "lesson_id": "lesson-1",
                "subject": "web",
                "clean_text": "A cookie usually carries the session identifier in the browser.",
            },
        ]


if __name__ == "__main__":
    unittest.main()
