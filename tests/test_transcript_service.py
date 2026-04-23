import tempfile
import unittest
from pathlib import Path

from src.infrastructure.storage.sqlite_store import SQLiteStore
from web.backend.app.services.transcript_service import TranscriptService


class TranscriptServiceTests(unittest.TestCase):
    def test_append_and_list_lesson_transcripts_from_sqlite(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SQLiteStore(Path(temp_dir) / "transcripts.sqlite3")
            service = TranscriptService(store=store)
            service.init_schema()

            service.append_transcript_record(
                {
                    "session_id": "session-a",
                    "storage_id": "store-a",
                    "course_id": "math-course",
                    "lesson_id": "lesson-1",
                    "chunk_id": 1,
                    "subject": "math",
                    "source_type": "realtime",
                    "text": "raw transcript",
                    "clean_text": "clean transcript",
                    "created_at": 100,
                }
            )

            records = service.list_lesson_transcripts(course_id="math-course", lesson_id="lesson-1")

            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["session_id"], "session-a")
            self.assertEqual(records[0]["chunk_id"], 1)
            self.assertEqual(records[0]["clean_text"], "clean transcript")
            self.assertEqual(records[0]["created_at"], 100)


if __name__ == "__main__":
    unittest.main()
