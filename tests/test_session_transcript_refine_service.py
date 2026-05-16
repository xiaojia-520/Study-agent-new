import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from src.infrastructure.storage.sqlite_store import SQLiteStore
from src.application.transcripts.refinement_service import SessionTranscriptRefineService
from src.application.transcripts.service import TranscriptService


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
                session_getter=lambda _: SimpleNamespace(
                    course_id="math-course",
                    lesson_id="lesson-1",
                    subject="math",
                ),
                transcript_loader=transcript_service.list_session_transcripts,
            )

            records = service.refine_session("session-a")

            self.assertEqual(len(records), 2)
            self.assertEqual(records[0].source_record_id, first_id)
            self.assertEqual(records[0].refined_text, "Today we talk about limits.")
            self.assertEqual(records[0].model_name, "deepseek-chat")
            self.assertEqual(records[0].metadata["prompt_version"], "transcript-refine-v1")
            self.assertIn("Subject: math", llm.prompts[0])
            self.assertIn("Keep filler words", llm.prompts[0])
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

    def test_refine_session_replaces_previous_refined_records_when_final_transcript_arrives(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SQLiteStore(Path(temp_dir) / "transcripts.sqlite3")
            transcript_service = TranscriptService(store=store)
            transcript_service.init_schema()
            realtime_id = self._append_record(transcript_service, chunk_id=1, text="Raw text")
            final_id = transcript_service.append_transcript_record(
                {
                    "session_id": "session-a",
                    "storage_id": "store-a-final",
                    "course_id": "math-course",
                    "lesson_id": "lesson-1",
                    "chunk_id": 2,
                    "subject": "math",
                    "source_type": "video",
                    "text": "Final text",
                    "clean_text": "Final text",
                    "created_at": 120,
                    "metadata": {
                        "parser": "offline_funasr",
                        "transcript_role": "final",
                    },
                }
            )
            llm = FakeLLM(
                [
                    f"""
                    [
                      {{"source_record_id": {final_id}, "refined_text": "Final text."}}
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
                session_getter=lambda _: SimpleNamespace(
                    course_id="math-course",
                    lesson_id="lesson-1",
                    subject="math",
                ),
                transcript_loader=transcript_service.list_session_transcripts,
            )
            service.append_refined_transcript_record(
                source_record={
                    "id": realtime_id,
                    "session_id": "session-a",
                    "course_id": "math-course",
                    "lesson_id": "lesson-1",
                    "chunk_id": 1,
                    "text": "Raw text",
                    "clean_text": "Raw text",
                    "created_at": 100,
                },
                refined_text="Draft text.",
            )

            records = service.refine_session("session-a")

            self.assertEqual(len(records), 1)
            self.assertEqual(records[0].source_record_id, final_id)
            self.assertEqual(records[0].refined_text, "Final text.")

    def test_refine_session_only_processes_new_records_when_transcript_set_is_extended(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SQLiteStore(Path(temp_dir) / "transcripts.sqlite3")
            transcript_service = TranscriptService(store=store)
            transcript_service.init_schema()
            first_id = self._append_record(transcript_service, chunk_id=1, text="First raw text")
            second_id = self._append_record(transcript_service, chunk_id=2, text="Second raw text")
            llm = FakeLLM(
                [
                    f"""
                    [
                      {{"source_record_id": {second_id}, "refined_text": "Second refined text."}}
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
                session_getter=lambda _: SimpleNamespace(
                    course_id="math-course",
                    lesson_id="lesson-1",
                    subject="math",
                ),
                transcript_loader=transcript_service.list_session_transcripts,
            )
            service.append_refined_transcript_record(
                source_record={
                    "id": first_id,
                    "session_id": "session-a",
                    "course_id": "math-course",
                    "lesson_id": "lesson-1",
                    "chunk_id": 1,
                    "text": "First raw text",
                    "clean_text": "First raw text",
                    "created_at": 101,
                },
                refined_text="First refined text.",
            )

            records = service.refine_session("session-a")

            input_records_json = llm.prompts[0].split("Input records JSON:", maxsplit=1)[-1]
            self.assertEqual(len(llm.prompts), 1)
            self.assertIn(f'"source_record_id": {second_id}', input_records_json)
            self.assertNotIn(f'"source_record_id": {first_id}', input_records_json)
            self.assertEqual(
                [(item.source_record_id, item.refined_text) for item in records],
                [
                    (first_id, "First refined text."),
                    (second_id, "Second refined text."),
                ],
            )

    def test_refine_session_splits_large_batches_by_record_limit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SQLiteStore(Path(temp_dir) / "transcripts.sqlite3")
            transcript_service = TranscriptService(store=store)
            transcript_service.init_schema()
            source_ids = [
                self._append_record(transcript_service, chunk_id=index, text=f"Raw text {index}")
                for index in range(1, 6)
            ]
            llm = FakeLLM(
                [
                    f"""
                    [
                      {{"source_record_id": {source_ids[0]}, "refined_text": "Refined text 1."}},
                      {{"source_record_id": {source_ids[1]}, "refined_text": "Refined text 2."}}
                    ]
                    """,
                    f"""
                    [
                      {{"source_record_id": {source_ids[2]}, "refined_text": "Refined text 3."}},
                      {{"source_record_id": {source_ids[3]}, "refined_text": "Refined text 4."}}
                    ]
                    """,
                    f"""
                    [
                      {{"source_record_id": {source_ids[4]}, "refined_text": "Refined text 5."}}
                    ]
                    """,
                ]
            )
            service = SessionTranscriptRefineService(
                store=store,
                runtime_factory=lambda: SimpleNamespace(
                    config=SimpleNamespace(llm_model="deepseek-chat"),
                    llm=llm,
                ),
                runtime_closer=lambda: None,
                session_getter=lambda _: SimpleNamespace(
                    course_id="math-course",
                    lesson_id="lesson-1",
                    subject="math",
                ),
                transcript_loader=transcript_service.list_session_transcripts,
                batch_record_limit=2,
            )

            records = service.refine_session("session-a")

            self.assertEqual(len(records), 5)
            self.assertEqual(len(llm.prompts), 3)
            self.assertIn("Transcript batch: 1/3", llm.prompts[0])
            self.assertIn("Transcript batch: 3/3", llm.prompts[2])

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
