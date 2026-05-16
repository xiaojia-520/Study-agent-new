import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from config.settings import settings
from src.infrastructure.storage.lesson_note_repository import SQLiteLessonNoteRepository
from src.infrastructure.storage.sqlite_store import SQLiteStore
from src.infrastructure.storage.qdrant_index_store import QdrantIndexStoreConfig
from src.application.review.lesson_history_service import LessonHistoryService
from src.application.video.video_service import SessionVideoService


class FakeIndexStore:
    def __init__(self) -> None:
        self.deleted_filters = []

    def delete_by_metadata(self, filters) -> None:
        self.deleted_filters.append(filters)


class LessonHistoryServiceTests(unittest.TestCase):
    def test_delete_lesson_removes_sql_rows_rag_points_and_local_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            transcript_dir = root / "transcripts"
            asset_dir = root / "assets"
            video_dir = root / "videos"
            subtitle_dir = root / "video_subtitles"
            mineru_dir = root / "mineru_results"
            for directory in (transcript_dir, asset_dir, video_dir, subtitle_dir, mineru_dir):
                directory.mkdir(parents=True, exist_ok=True)

            original_paths = (
                settings.TRANSCRIPT_SAVE_DIR,
                settings.ASSET_SAVE_DIR,
                settings.VIDEO_SAVE_DIR,
                settings.VIDEO_SUBTITLE_DIR,
                settings.MINERU_RESULT_DIR,
            )
            settings.TRANSCRIPT_SAVE_DIR = transcript_dir
            settings.ASSET_SAVE_DIR = asset_dir
            settings.VIDEO_SAVE_DIR = video_dir
            settings.VIDEO_SUBTITLE_DIR = subtitle_dir
            settings.MINERU_RESULT_DIR = mineru_dir

            try:
                store = SQLiteStore(root / "study.sqlite3")
                store.init_schema()
                SessionVideoService(store=store, rag_indexing_enabled=False).init_schema()
                note_repository = SQLiteLessonNoteRepository(store=store)
                note_repository.init_schema()

                now = 1710000000
                target_course = "course-a"
                target_lesson = "lesson-1"
                other_course = "course-b"
                other_lesson = "lesson-2"

                store.execute(
                    """
                    INSERT INTO chat_messages(session_id, course_id, lesson_id, role, content, created_at, metadata_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    ("session-a", target_course, target_lesson, "user", "target message", now, None),
                )
                store.execute(
                    """
                    INSERT INTO chat_messages(session_id, course_id, lesson_id, role, content, created_at, metadata_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    ("session-b", other_course, other_lesson, "user", "other message", now, None),
                )

                target_transcript_id = store.execute(
                    """
                    INSERT INTO transcript_records(
                        session_id, storage_id, course_id, lesson_id, chunk_id, subject, source_type,
                        source_file, start_ms, end_ms, text, clean_text, created_at, metadata_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "session-a",
                        "storage-a",
                        target_course,
                        target_lesson,
                        1,
                        target_course,
                        "realtime",
                        None,
                        None,
                        None,
                        "target transcript",
                        "target transcript",
                        now,
                        None,
                    ),
                )
                store.execute(
                    """
                    INSERT INTO transcript_records(
                        session_id, storage_id, course_id, lesson_id, chunk_id, subject, source_type,
                        source_file, start_ms, end_ms, text, clean_text, created_at, metadata_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "session-b",
                        "storage-b",
                        other_course,
                        other_lesson,
                        1,
                        other_course,
                        "realtime",
                        None,
                        None,
                        None,
                        "other transcript",
                        "other transcript",
                        now,
                        None,
                    ),
                )
                store.execute(
                    """
                    INSERT INTO refined_transcript_records(
                        source_record_id, session_id, course_id, lesson_id, chunk_id,
                        original_text, refined_text, created_at, refined_at, model_name, metadata_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        target_transcript_id,
                        "session-a",
                        target_course,
                        target_lesson,
                        1,
                        "target transcript",
                        "target transcript refined",
                        now,
                        now,
                        "deepseek-chat",
                        None,
                    ),
                )

                asset_session_dir = asset_dir / "session-a"
                asset_session_dir.mkdir(parents=True, exist_ok=True)
                asset_file = asset_session_dir / "asset.pdf"
                asset_file.write_text("asset", encoding="utf-8")
                result_dir = mineru_dir / "asset-a"
                result_dir.mkdir(parents=True, exist_ok=True)
                markdown_path = result_dir / "result.md"
                markdown_path.write_text("markdown", encoding="utf-8")
                store.execute(
                    """
                    INSERT INTO lesson_assets(
                        asset_id, session_id, course_id, lesson_id, subject, file_name, file_path,
                        file_size, media_type, status, result_dir, markdown_path, created_at, updated_at, metadata_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "asset-a",
                        "session-a",
                        target_course,
                        target_lesson,
                        target_course,
                        "asset.pdf",
                        str(asset_file),
                        5,
                        "application/pdf",
                        "done",
                        str(result_dir),
                        str(markdown_path),
                        now,
                        now,
                        None,
                    ),
                )

                video_session_dir = video_dir / "session-a"
                video_session_dir.mkdir(parents=True, exist_ok=True)
                video_file = video_session_dir / "lesson.mp4"
                video_file.write_text("video", encoding="utf-8")
                subtitle_output_dir = subtitle_dir / "video-a"
                subtitle_output_dir.mkdir(parents=True, exist_ok=True)
                wav_path = subtitle_output_dir / "lesson.wav"
                srt_path = subtitle_output_dir / "lesson.srt"
                wav_path.write_text("wav", encoding="utf-8")
                srt_path.write_text("srt", encoding="utf-8")
                store.execute(
                    """
                    INSERT INTO lesson_videos(
                        video_id, session_id, course_id, lesson_id, subject, file_name, file_path, file_size,
                        media_type, status, wav_path, srt_path, segment_count, created_at, updated_at, metadata_json, segments_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "video-a",
                        "session-a",
                        target_course,
                        target_lesson,
                        target_course,
                        "lesson.mp4",
                        str(video_file),
                        5,
                        "video/mp4",
                        "done",
                        str(wav_path),
                        str(srt_path),
                        1,
                        now,
                        now,
                        json.dumps({"subtitle_refined_at": now}),
                        json.dumps([{"start_ms": 0, "end_ms": 1000, "text": "hello"}]),
                    ),
                )

                note_repository.create_note(
                    note_id="note-a",
                    course_id=target_course,
                    lesson_id=target_lesson,
                    status="done",
                    markdown="# target note",
                )
                note_repository.create_note(
                    note_id="note-b",
                    course_id=other_course,
                    lesson_id=other_lesson,
                    status="done",
                    markdown="# other note",
                )

                mixed_jsonl = transcript_dir / "mixed.jsonl"
                mixed_jsonl.write_text(
                    "\n".join(
                        [
                            json.dumps(
                                {
                                    "session_id": "session-a",
                                    "storage_id": "storage-a",
                                    "course_id": target_course,
                                    "lesson_id": target_lesson,
                                    "chunk_id": 1,
                                    "text": "target transcript",
                                },
                                ensure_ascii=False,
                            ),
                            json.dumps(
                                {
                                    "session_id": "session-b",
                                    "storage_id": "storage-b",
                                    "course_id": other_course,
                                    "lesson_id": other_lesson,
                                    "chunk_id": 1,
                                    "text": "other transcript",
                                },
                                ensure_ascii=False,
                            ),
                        ]
                    )
                    + "\n",
                    encoding="utf-8",
                )
                target_only_jsonl = transcript_dir / "target-only.jsonl"
                target_only_jsonl.write_text(
                    json.dumps(
                        {
                            "session_id": "session-a",
                            "storage_id": "storage-a",
                            "course_id": target_course,
                            "lesson_id": target_lesson,
                            "chunk_id": 2,
                            "text": "target transcript two",
                        },
                        ensure_ascii=False,
                    )
                    + "\n",
                    encoding="utf-8",
                )

                fake_index_store = FakeIndexStore()
                service = LessonHistoryService(
                    store=store,
                    rag_runtime_factory=lambda: SimpleNamespace(index_store=fake_index_store),
                )

                result = service.delete_lesson(course_id=target_course, lesson_id=target_lesson)

                self.assertTrue(result["deleted"])
                self.assertEqual(result["counts"]["chat_messages"], 1)
                self.assertEqual(result["counts"]["transcript_records"], 1)
                self.assertEqual(result["counts"]["lesson_assets"], 1)
                self.assertEqual(result["counts"]["lesson_videos"], 1)
                self.assertEqual(result["counts"]["lesson_notes"], 1)
                self.assertGreaterEqual(result["counts"]["deleted_jsonl_records"], 2)

                self.assertEqual(
                    self._count_rows(store, "chat_messages", target_course, target_lesson),
                    0,
                )
                self.assertEqual(
                    self._count_rows(store, "transcript_records", target_course, target_lesson),
                    0,
                )
                self.assertEqual(
                    self._count_rows(store, "refined_transcript_records", target_course, target_lesson),
                    0,
                )
                self.assertEqual(
                    self._count_rows(store, "lesson_assets", target_course, target_lesson),
                    0,
                )
                self.assertEqual(
                    self._count_rows(store, "lesson_videos", target_course, target_lesson),
                    0,
                )
                self.assertEqual(
                    self._count_rows(store, "lesson_notes", target_course, target_lesson),
                    0,
                )

                self.assertEqual(
                    self._count_rows(store, "chat_messages", other_course, other_lesson),
                    1,
                )
                self.assertEqual(
                    self._count_rows(store, "transcript_records", other_course, other_lesson),
                    1,
                )
                self.assertEqual(
                    self._count_rows(store, "lesson_notes", other_course, other_lesson),
                    1,
                )

                self.assertFalse(asset_file.exists())
                self.assertFalse(result_dir.exists())
                self.assertFalse(video_file.exists())
                self.assertFalse(wav_path.exists())
                self.assertFalse(srt_path.exists())
                self.assertFalse(target_only_jsonl.exists())
                self.assertTrue(mixed_jsonl.exists())
                mixed_payloads = [json.loads(line) for line in mixed_jsonl.read_text(encoding="utf-8").splitlines() if line]
                self.assertEqual(len(mixed_payloads), 1)
                self.assertEqual(mixed_payloads[0]["course_id"], other_course)

                self.assertEqual(len(fake_index_store.deleted_filters), 1)
                clauses = fake_index_store.deleted_filters[0].clauses
                self.assertEqual([(item.key, item.value) for item in clauses], [("course_id", target_course), ("lesson_id", target_lesson)])
            finally:
                (
                    settings.TRANSCRIPT_SAVE_DIR,
                    settings.ASSET_SAVE_DIR,
                    settings.VIDEO_SAVE_DIR,
                    settings.VIDEO_SUBTITLE_DIR,
                    settings.MINERU_RESULT_DIR,
                ) = original_paths

    @staticmethod
    def _count_rows(store: SQLiteStore, table_name: str, course_id: str, lesson_id: str) -> int:
        rows = store.query_all(
            f"SELECT COUNT(*) AS count FROM {table_name} WHERE course_id = ? AND lesson_id = ?",
            (course_id, lesson_id),
        )
        return int(rows[0]["count"])


if __name__ == "__main__":
    unittest.main()
