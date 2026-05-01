import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from src.application.lesson_notes import LessonNoteService
from src.domain.lesson_note import LessonNoteStatus
from src.infrastructure.storage.lesson_note_repository import SQLiteLessonNoteRepository
from src.infrastructure.storage.sqlite_store import SQLiteStore
from web.backend.app.services.transcript_service import TranscriptService


class FakeLLM:
    def __init__(self, responses):
        self.responses = list(responses)
        self.prompts = []
        self.model_name = "fake-note-model"

    def complete(self, prompt: str):
        self.prompts.append(prompt)
        if not self.responses:
            raise AssertionError("unexpected llm call")
        return SimpleNamespace(text=self.responses.pop(0))


class LessonNoteServiceTests(unittest.TestCase):
    def test_generate_note_persists_structured_note(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            service, transcript_service, repository, llm = self._build_service(
                temp_dir,
                responses=[
                    """
                    {
                      "title": "HTTP Session Notes",
                      "overview": "The lesson explains why HTTP needs sessions to preserve user state.",
                      "key_points": ["HTTP is stateless", "Sessions connect requests"],
                      "concepts": [{"term": "Session", "explanation": "Server-side user state"}],
                      "examples": ["A cookie carries the session identifier"],
                      "timeline": [{"time": "00:01:00", "content": "Session identifiers were introduced"}],
                      "review_items": ["Review cookie and session relationship"],
                      "questions": ["Why does HTTP need a session id?"]
                    }
                    """
                ],
            )
            self._append_transcripts(transcript_service)

            note = service.generate_note(
                course_id="web-course",
                lesson_id="lesson-1",
                session_id="session-a",
                focus="sessions",
                max_items=4,
            )

            self.assertEqual(note.status, LessonNoteStatus.DONE)
            self.assertEqual(note.title, "HTTP Session Notes")
            self.assertIn("preserve user state", note.summary or "")
            self.assertIn("# HTTP Session Notes", note.markdown or "")
            self.assertEqual(note.note["concepts"][0]["term"], "Session")
            self.assertEqual(note.source_record_count, 2)
            self.assertEqual(note.model_name, "fake-note-model")
            self.assertEqual(note.metadata["source_type_counts"], {"realtime": 1, "video": 1})
            self.assertIn("source=realtime", llm.prompts[0])

            latest = repository.get_latest_note(course_id="web-course", lesson_id="lesson-1")
            self.assertIsNotNone(latest)
            self.assertEqual(latest.note_id, note.note_id)

            cached_plan = service.request_generation(course_id="web-course", lesson_id="lesson-1")
            self.assertFalse(cached_plan.should_generate)
            self.assertEqual(cached_plan.note.note_id, note.note_id)

    def test_generate_note_merges_multiple_chunks(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            service, transcript_service, _repository, llm = self._build_service(
                temp_dir,
                responses=[
                    '{"title":"Chunk A","overview":"A","key_points":["A"],"concepts":[],"examples":[],"timeline":[],"review_items":[],"questions":[]}',
                    '{"title":"Chunk B","overview":"B","key_points":["B"],"concepts":[],"examples":[],"timeline":[],"review_items":[],"questions":[]}',
                    '{"title":"Merged","overview":"Merged overview","key_points":["A","B"],"concepts":[],"examples":[],"timeline":[],"review_items":[],"questions":[]}',
                ],
                chunk_char_limit=40,
            )
            self._append_transcripts(transcript_service)

            note = service.generate_note(course_id="web-course", lesson_id="lesson-1")

            self.assertEqual(note.title, "Merged")
            self.assertEqual(note.note["key_points"], ["A", "B"])
            self.assertEqual(note.metadata["chunk_count"], 2)
            self.assertEqual(len(llm.prompts), 3)
            self.assertIn("Merge the chunk-level notes", llm.prompts[-1])

    def test_generate_pending_note_marks_failed_when_llm_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SQLiteStore(Path(temp_dir) / "notes.sqlite3")
            transcript_service = TranscriptService(store=store)
            transcript_service.init_schema()
            repository = SQLiteLessonNoteRepository(store=store)
            repository.init_schema()
            service = LessonNoteService(
                repository=repository,
                transcript_loader=transcript_service.list_lesson_transcripts,
                runtime_factory=lambda: SimpleNamespace(llm=None),
                runtime_closer=lambda: None,
            )
            self._append_transcripts(transcript_service)
            plan = service.request_generation(course_id="web-course", lesson_id="lesson-1")

            failed = service.generate_pending_note(plan.note.note_id, raise_errors=False)

            self.assertEqual(failed.status, LessonNoteStatus.FAILED)
            self.assertIn("LLM is not enabled", failed.error_message or "")

    @staticmethod
    def _build_service(temp_dir, *, responses, chunk_char_limit=6000):
        store = SQLiteStore(Path(temp_dir) / "notes.sqlite3")
        transcript_service = TranscriptService(store=store)
        transcript_service.init_schema()
        repository = SQLiteLessonNoteRepository(store=store)
        repository.init_schema()
        llm = FakeLLM(responses)
        service = LessonNoteService(
            repository=repository,
            transcript_loader=transcript_service.list_lesson_transcripts,
            runtime_factory=lambda: SimpleNamespace(llm=llm),
            runtime_closer=lambda: None,
            chunk_char_limit=chunk_char_limit,
        )
        return service, transcript_service, repository, llm

    @staticmethod
    def _append_transcripts(transcript_service: TranscriptService) -> None:
        transcript_service.append_transcript_record(
            {
                "session_id": "session-b",
                "storage_id": "store-a",
                "course_id": "web-course",
                "lesson_id": "lesson-1",
                "chunk_id": 1,
                "subject": "web",
                "source_type": "realtime",
                "text": "HTTP is stateless by default.",
                "clean_text": "HTTP is stateless by default.",
                "created_at": 100,
            }
        )
        transcript_service.append_transcript_record(
            {
                "session_id": "session-a",
                "storage_id": "store-a",
                "course_id": "web-course",
                "lesson_id": "lesson-1",
                "chunk_id": 2,
                "subject": "web",
                "source_type": "video",
                "source_file": "lesson.webm",
                "start_ms": 60_000,
                "end_ms": 65_000,
                "text": "A cookie can carry the session identifier.",
                "clean_text": "A cookie can carry the session identifier.",
                "created_at": 101,
                "metadata": {"parser": "offline_funasr", "transcript_role": "final"},
            }
        )


if __name__ == "__main__":
    unittest.main()
