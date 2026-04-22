import tempfile
import unittest
from pathlib import Path

from src.infrastructure.storage.sqlite_store import SQLiteStore
from web.backend.app.domain.session import RealtimeSession
from web.backend.app.services.chat_memory_service import ChatMemoryService


class ChatMemoryServiceTests(unittest.TestCase):
    def test_append_turn_and_list_recent_turns(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SQLiteStore(Path(temp_dir) / "memory.sqlite3")
            service = ChatMemoryService(store=store)
            service.init_schema()
            session = self._session()

            service.append_turn(
                session=session,
                user_text=" What is a session? ",
                assistant_text="A session tracks a lesson conversation.",
                answer_metadata={"answer_strategy": "llm_synthesized"},
            )

            turns = service.list_recent_turns("session-a", limit=3)
            messages = service.list_session_messages("session-a")

            self.assertEqual(len(turns), 1)
            self.assertEqual(turns[0].user, "What is a session?")
            self.assertEqual(turns[0].assistant, "A session tracks a lesson conversation.")
            self.assertEqual([item.role for item in messages], ["user", "assistant"])
            self.assertEqual(messages[0].content, "What is a session?")
            self.assertEqual(messages[1].metadata["answer_strategy"], "llm_synthesized")

    def test_recent_turn_limit_keeps_latest_turns(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SQLiteStore(Path(temp_dir) / "memory.sqlite3")
            service = ChatMemoryService(store=store)
            service.init_schema()
            session = self._session()

            for index in range(3):
                service.append_turn(
                    session=session,
                    user_text=f"question {index}",
                    assistant_text=f"answer {index}",
                )

            turns = service.list_recent_turns("session-a", limit=2)

            self.assertEqual([turn.user for turn in turns], ["question 1", "question 2"])
            self.assertEqual([turn.assistant for turn in turns], ["answer 1", "answer 2"])

    def test_lesson_memory_spans_multiple_sessions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SQLiteStore(Path(temp_dir) / "memory.sqlite3")
            service = ChatMemoryService(store=store)
            service.init_schema()
            first_session = self._session(session_id="session-a")
            second_session = self._session(session_id="session-b")

            service.append_turn(
                session=first_session,
                user_text="first session question",
                assistant_text="first session answer",
            )
            service.append_turn(
                session=second_session,
                user_text="second session question",
                assistant_text="second session answer",
            )

            turns = service.list_recent_lesson_turns(
                course_id="math-course",
                lesson_id="math-course-lesson-1",
                limit=4,
            )
            messages = service.list_lesson_messages(
                course_id="math-course",
                lesson_id="math-course-lesson-1",
            )
            summaries = service.list_lesson_summaries()

            self.assertEqual([turn.user for turn in turns], ["first session question", "second session question"])
            self.assertEqual({message.session_id for message in messages}, {"session-a", "session-b"})
            self.assertEqual(len(summaries), 1)
            self.assertEqual(summaries[0].course_id, "math-course")
            self.assertEqual(summaries[0].lesson_id, "math-course-lesson-1")
            self.assertEqual(summaries[0].session_count, 2)
            self.assertEqual(summaries[0].message_count, 4)

    @staticmethod
    def _session(session_id: str = "session-a") -> RealtimeSession:
        return RealtimeSession(
            session_id=session_id,
            course_id="math-course",
            lesson_id="math-course-lesson-1",
            subject="math",
            created_at=100,
            updated_at=100,
        )


if __name__ == "__main__":
    unittest.main()
