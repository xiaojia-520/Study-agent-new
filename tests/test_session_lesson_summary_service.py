import unittest
from types import SimpleNamespace

from web.backend.app.domain.session import RealtimeSession
from web.backend.app.services.session_lesson_summary_service import SessionLessonSummaryService


class FakeLLM:
    def __init__(self, responses):
        self.responses = list(responses)
        self.prompts = []

    def complete(self, prompt: str):
        self.prompts.append(prompt)
        if not self.responses:
            raise AssertionError("unexpected llm call")
        return SimpleNamespace(text=self.responses.pop(0))


class SessionLessonSummaryServiceTests(unittest.TestCase):
    def test_generate_summary_returns_structured_output(self) -> None:
        llm = FakeLLM(
            [
                """
                {
                  "summary": "This lesson explained how sessions restore state across HTTP requests.",
                  "key_points": ["HTTP is stateless by default", "Sessions track users across requests"],
                  "review_items": ["Cookie and session id relationship"],
                  "important_terms": [{"term": "Session", "definition": "A server-side mechanism for tracking a user"}]
                }
                """
            ]
        )
        service = SessionLessonSummaryService(
            runtime_factory=lambda: SimpleNamespace(llm=llm),
            runtime_closer=lambda: None,
            session_getter=lambda _: self._session(),
            transcript_loader=lambda session, session_id: self._transcript_items(),
        )

        result = service.generate_summary(
            session_id="session-a",
            focus="Focus on sessions and cookies",
            max_items=4,
        )

        self.assertEqual(result.session_id, "session-a")
        self.assertEqual(result.course_id, "web-course")
        self.assertEqual(result.lesson_id, "lesson-1")
        self.assertIn("restore state", result.summary)
        self.assertEqual(result.key_points[0], "HTTP is stateless by default")
        self.assertEqual(result.review_items, ["Cookie and session id relationship"])
        self.assertEqual(result.important_terms[0].term, "Session")
        self.assertEqual(result.metadata["chunk_count"], 1)
        self.assertEqual(result.metadata["max_items"], 4)
        self.assertIn("Focus instruction: Focus on sessions and cookies", llm.prompts[0])

    def test_generate_summary_merges_multiple_chunks(self) -> None:
        llm = FakeLLM(
            [
                '{"summary":"Chunk one","key_points":["Point A"],"review_items":["Review A"],"important_terms":[{"term":"HTTP","definition":"Stateless protocol"}]}',
                '{"summary":"Chunk two","key_points":["Point B"],"review_items":["Review B"],"important_terms":[{"term":"Cookie","definition":"Browser-side identifier carrier"}]}',
                '{"summary":"Merged lesson summary","key_points":["Point A","Point B"],"review_items":["Review A","Review B"],"important_terms":[{"term":"HTTP","definition":"Stateless protocol"},{"term":"Cookie","definition":"Browser-side identifier carrier"}]}',
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
                "clean_text": "Sessions restore user state across requests using cookies.",
            },
        ]
        service = SessionLessonSummaryService(
            runtime_factory=lambda: SimpleNamespace(llm=llm),
            runtime_closer=lambda: None,
            session_getter=lambda _: self._session(),
            transcript_loader=lambda session, session_id: transcript_items,
            chunk_char_limit=40,
        )

        result = service.generate_summary(session_id="session-a")

        self.assertEqual(result.summary, "Merged lesson summary")
        self.assertEqual(result.key_points, ["Point A", "Point B"])
        self.assertEqual(result.metadata["chunk_count"], 2)
        self.assertEqual(len(llm.prompts), 3)
        self.assertIn("Merge the chunk summaries", llm.prompts[-1])

    def test_generate_summary_uses_transcript_context_when_session_is_missing(self) -> None:
        llm = FakeLLM(
            [
                '{"summary":"Transcript-only summary","key_points":[],"review_items":[],"important_terms":[]}'
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
        service = SessionLessonSummaryService(
            runtime_factory=lambda: SimpleNamespace(llm=llm),
            runtime_closer=lambda: None,
            session_getter=lambda _: None,
            transcript_loader=lambda session, session_id: transcript_items,
        )

        result = service.generate_summary(session_id="orphan-session")

        self.assertEqual(result.course_id, "archived-course")
        self.assertEqual(result.lesson_id, "archived-lesson")
        self.assertEqual(result.subject, "archived-subject")
        self.assertEqual(result.summary, "Transcript-only summary")

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
                "clean_text": "A session lets the server track a user across requests.",
            },
        ]


if __name__ == "__main__":
    unittest.main()
