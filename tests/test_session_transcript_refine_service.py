import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from src.infrastructure.storage.sqlite_store import SQLiteStore
from web.backend.app.services.session_transcript_refine_service import SessionTranscriptRefineService
from web.backend.app.services.transcript_service import TranscriptService


class FakeLLM:
    def __init__(self, responses):
        self.responses = list(responses)
        self.prompts = []

    def complete(self, prompt: str):
        self.prompts.append(prompt)
        if not self.responses:
            raise AssertionError("unexpected llm call")
        return SimpleNamespace(text=self.responses.pop(0))


class SessionTranscriptRefineServiceTests(unittest.TestCase):
    def test_refine_session_persists_llm_refined_records(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SQLiteStore(Path(temp_dir) / "transcripts.sqlite3")
            transcript_service = TranscriptService(store=store)
            transcript_service.init_schema()
            first_id = self._append_record(transcript_service, chunk_id=1, text="Today we talk about limit")
            second_id = self._append_record(transcript_service, chunk_id=2, text="Limit is approach value")
            llm = FakeLLM(
                [
                    f"""
                    [
                      {{"source_record_id": {first_id}, "refined_text": "Today we talk about limits."}},
                      {{"source_record_id": {second_id}, "refined_text": "A limit is an approach value."}}
                    ]
                    """
                ]
            )
            service = SessionTranscriptRefineService(
                store=store,
                runtime_factory=lambda: SimpleNamespace(
                    config=SimpleNamespace(llm_model="deepseek-chat"),
                    llm=llm,
                ),
                runtime_closer=lambda: None,
                session_getter=lambda _: None,
                transcript_loader=transcript_service.list_session_transcripts,
            )

            records = service.refine_session("session-a")

            self.assertEqual(len(records), 2)
            self.assertEqual(records[0].source_record_id, first_id)
            self.assertEqual(records[0].refined_text, "Today we talk about limits.")
            self.assertEqual(records[0].model_name, "deepseek-chat")
            self.assertEqual(records[0].metadata["prompt_version"], "transcript-refine-v1")
            self.assertIn("Input records JSON:", llm.prompts[0])

            lesson_records = service.list_lesson_refined_transcripts(
                course_id="math-course",
                lesson_id="lesson-1",
            )
            self.assertEqual([item.source_record_id for item in lesson_records], [first_id, second_id])

    def test_refine_session_skips_existing_refined_records(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SQLiteStore(Path(temp_dir) / "transcripts.sqlite3")
            transcript_service = TranscriptService(store=store)
            transcript_service.init_schema()
            source_id = self._append_record(transcript_service, chunk_id=1, text="Raw text")
            service = SessionTranscriptRefineService(
                store=store,
                runtime_factory=lambda: SimpleNamespace(
                    config=SimpleNamespace(llm_model="deepseek-chat"),
                    llm=FakeLLM([]),
                ),
                runtime_closer=lambda: None,
                session_getter=lambda _: None,
                transcript_loader=transcript_service.list_session_transcripts,
            )
            service.append_refined_transcript_record(
                source_record={
                    "id": source_id,
                    "session_id": "session-a",
                    "course_id": "math-course",
                    "lesson_id": "lesson-1",
                    "chunk_id": 1,
                    "text": "Raw text",
                    "clean_text": "Raw text",
                    "created_at": 100,
                },
                refined_text="Refined text.",
            )

            records = service.refine_session("session-a")

            self.assertEqual(len(records), 1)
            self.assertEqual(records[0].refined_text, "Refined text.")

    @staticmethod
    def _append_record(transcript_service: TranscriptService, *, chunk_id: int, text: str) -> int:
        return transcript_service.append_transcript_record(
            {
                "session_id": "session-a",
                "storage_id": "store-a",
                "course_id": "math-course",
                "lesson_id": "lesson-1",
                "chunk_id": chunk_id,
                "subject": "math",
                "source_type": "realtime",
                "text": text,
                "clean_text": text,
                "created_at": 100 + chunk_id,
            }
        )


if __name__ == "__main__":
    unittest.main()
