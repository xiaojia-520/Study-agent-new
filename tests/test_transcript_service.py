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

    def test_list_lesson_transcripts_prefers_offline_final_over_realtime(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SQLiteStore(Path(temp_dir) / "transcripts.sqlite3")
            service = TranscriptService(store=store)
            service.init_schema()

            service.append_transcript_record(
                {
                    "session_id": "session-a",
                    "course_id": "math-course",
                    "lesson_id": "lesson-1",
                    "chunk_id": 1,
                    "subject": "math",
                    "source_type": "realtime",
                    "text": "draft realtime",
                    "clean_text": "draft realtime",
                    "created_at": 100,
                }
            )
            service.append_transcript_record(
                {
                    "session_id": "session-a",
                    "course_id": "math-course",
                    "lesson_id": "lesson-1",
                    "chunk_id": 2,
                    "subject": "math",
                    "source_type": "video",
                    "start_ms": 1000,
                    "end_ms": 2000,
                    "text": "final subtitle",
                    "clean_text": "final subtitle",
                    "created_at": 101,
                    "metadata": {"parser": "offline_funasr", "transcript_role": "final", "video_id": "video-1"},
                }
            )
            service.append_transcript_record(
                {
                    "session_id": "session-a",
                    "course_id": "math-course",
                    "lesson_id": "lesson-1",
                    "chunk_id": 3,
                    "subject": "math",
                    "source_type": "video",
                    "start_ms": 1500,
                    "end_ms": 1500,
                    "text": "PPT: visual",
                    "clean_text": "PPT: visual",
                    "created_at": 102,
                    "metadata": {"parser": "manual_roi_ocr_vlm", "frame_timestamp_ms": 1500},
                }
            )

            records = service.list_lesson_transcripts(course_id="math-course", lesson_id="lesson-1")
            all_records = service.list_lesson_transcripts(
                course_id="math-course",
                lesson_id="lesson-1",
                prefer_final=False,
            )

            self.assertEqual([record["clean_text"] for record in records], ["final subtitle", "PPT: visual"])
            self.assertEqual([record["clean_text"] for record in all_records], [
                "draft realtime",
                "final subtitle",
                "PPT: visual",
            ])

    def test_delete_final_video_transcripts_removes_only_matching_video(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SQLiteStore(Path(temp_dir) / "transcripts.sqlite3")
            service = TranscriptService(store=store)
            service.init_schema()

            for chunk_id, video_id in ((1, "video-a"), (2, "video-b")):
                service.append_transcript_record(
                    {
                        "session_id": "session-a",
                        "course_id": "math-course",
                        "lesson_id": "lesson-1",
                        "chunk_id": chunk_id,
                        "subject": "math",
                        "source_type": "video",
                        "text": video_id,
                        "clean_text": video_id,
                        "created_at": 100 + chunk_id,
                        "metadata": {"parser": "offline_funasr", "video_id": video_id},
                    }
                )

            service.delete_final_video_transcripts(session_id="session-a", video_id="video-a")

            records = service.list_session_transcripts(None, "session-a", prefer_final=False)

            self.assertEqual([record["clean_text"] for record in records], ["video-b"])


if __name__ == "__main__":
    unittest.main()
