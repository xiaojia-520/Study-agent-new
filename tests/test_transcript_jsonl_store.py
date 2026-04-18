import json
import tempfile
import unittest
from pathlib import Path

from src.core.knowledge.transcript_jsonl_store import TranscriptJsonlStore


class TranscriptJsonlStoreTests(unittest.TestCase):
    def test_append_writes_runtime_session_and_scope_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir)
            store = TranscriptJsonlStore(
                subject="math",
                session_id="runtime-session-1",
                storage_id="storage-session-1",
                course_id="math-course",
                lesson_id="math-course-lesson-1",
                root_dir=root_dir,
            )

            record = store.append("final transcript", source_type="realtime")

            self.assertEqual(store.file_path, root_dir / "storage-session-1.jsonl")
            self.assertEqual(record["session_id"], "runtime-session-1")
            self.assertEqual(record["storage_id"], "storage-session-1")
            self.assertEqual(record["course_id"], "math-course")
            self.assertEqual(record["lesson_id"], "math-course-lesson-1")

            payload = json.loads(store.file_path.read_text(encoding="utf-8").strip())
            self.assertEqual(payload["session_id"], "runtime-session-1")
            self.assertEqual(payload["storage_id"], "storage-session-1")


if __name__ == "__main__":
    unittest.main()
