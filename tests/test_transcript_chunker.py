import json
import tempfile
import unittest
from pathlib import Path

from src.core.knowledge.chunker import (
    build_chunks,
    build_chunks_for_session,
    group_records_by_session,
    load_records_from_dir,
    load_transcript_records,
)
from src.core.knowledge.document_models import ChunkingOptions, TranscriptRecord


class TranscriptChunkerTests(unittest.TestCase):
    def test_transcript_record_from_dict_uses_clean_text_fallback(self) -> None:
        record = TranscriptRecord.from_dict(
            {
                "session_id": "session-a",
                "chunk_id": 1,
                "subject": "math",
                "source_type": "realtime",
                "text": "raw-text",
                "clean_text": "",
                "created_at": 100,
            }
        )

        self.assertEqual(record.content, "raw-text")
        self.assertEqual(record.record_id, "session-a:1")

    def test_load_transcript_records_reads_jsonl(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "session-a.jsonl"
            payloads = [
                {
                    "session_id": "session-a",
                    "chunk_id": 2,
                    "subject": "math",
                    "source_type": "realtime",
                    "text": "two",
                    "clean_text": "two",
                    "created_at": 102,
                },
                {
                    "session_id": "session-a",
                    "chunk_id": 1,
                    "subject": "math",
                    "source_type": "realtime",
                    "text": "one",
                    "clean_text": "one",
                    "created_at": 101,
                },
            ]
            file_path.write_text(
                "\n".join(json.dumps(payload) for payload in payloads) + "\n",
                encoding="utf-8",
            )

            records = load_transcript_records(file_path)

        self.assertEqual([record.chunk_id for record in records], [1, 2])
        self.assertEqual(records[0].content, "one")

    def test_load_records_from_dir_sorts_across_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "b.jsonl").write_text(
                json.dumps(
                    {
                        "session_id": "session-b",
                        "chunk_id": 1,
                        "subject": "physics",
                        "source_type": "realtime",
                        "text": "bbb",
                        "clean_text": "bbb",
                        "created_at": 201,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            nested = root / "nested"
            nested.mkdir()
            (nested / "a.jsonl").write_text(
                json.dumps(
                    {
                        "session_id": "session-a",
                        "chunk_id": 1,
                        "subject": "math",
                        "source_type": "realtime",
                        "text": "aaa",
                        "clean_text": "aaa",
                        "created_at": 101,
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            records = load_records_from_dir(root)

        self.assertEqual([record.session_id for record in records], ["session-a", "session-b"])

    def test_group_records_by_session_keeps_chunk_order(self) -> None:
        records = [
            self._record(session_id="session-b", chunk_id=1, text="b"),
            self._record(session_id="session-a", chunk_id=2, text="a2"),
            self._record(session_id="session-a", chunk_id=1, text="a1"),
        ]

        grouped = group_records_by_session(records)

        self.assertEqual(list(grouped.keys()), ["session-a", "session-b"])
        self.assertEqual([record.chunk_id for record in grouped["session-a"]], [1, 2])

    def test_build_chunks_for_session_applies_overlap(self) -> None:
        records = [
            self._record(chunk_id=1, text="aaaa"),
            self._record(chunk_id=2, text="bbbb"),
            self._record(chunk_id=3, text="cccc"),
            self._record(chunk_id=4, text="dddd"),
        ]

        chunks = build_chunks_for_session(
            records,
            ChunkingOptions(max_chars=9, overlap_records=1, min_chunk_chars=1),
        )

        self.assertEqual([chunk.doc_id for chunk in chunks], ["session-a:1-2:0", "session-a:2-3:1", "session-a:3-4:2"])
        self.assertEqual([chunk.content for chunk in chunks], ["aaaa\nbbbb", "bbbb\ncccc", "cccc\ndddd"])
        self.assertEqual(chunks[1].metadata["record_ids"], ["session-a:2", "session-a:3"])
        self.assertEqual(chunks[1].course_id, "math-course")
        self.assertEqual(chunks[1].lesson_id, "math-course-lesson-1")
        self.assertEqual(chunks[1].storage_id, "storage-session-a")

    def test_build_chunks_for_session_splits_long_record(self) -> None:
        chunks = build_chunks_for_session(
            [self._record(chunk_id=1, text="abcdefghijk")],
            ChunkingOptions(max_chars=5, overlap_records=0, min_chunk_chars=1),
        )

        self.assertEqual([chunk.content for chunk in chunks], ["abcde", "fghij", "k"])
        self.assertTrue(all(chunk.first_chunk_id == 1 for chunk in chunks))
        self.assertTrue(all(chunk.last_chunk_id == 1 for chunk in chunks))

    def test_build_chunks_handles_multiple_sessions(self) -> None:
        records = [
            self._record(session_id="session-b", chunk_id=1, text="bbbb"),
            self._record(session_id="session-a", chunk_id=1, text="aaaa"),
        ]

        chunks = build_chunks(records, ChunkingOptions(max_chars=20, overlap_records=0, min_chunk_chars=1))

        self.assertEqual([chunk.session_id for chunk in chunks], ["session-a", "session-b"])

    def _record(
        self,
        *,
        session_id: str = "session-a",
        chunk_id: int,
        text: str,
        created_at: int | None = None,
    ) -> TranscriptRecord:
        return TranscriptRecord(
            session_id=session_id,
            chunk_id=chunk_id,
            subject="math",
            source_type="realtime",
            text=text,
            clean_text=text,
            created_at=created_at or 100 + chunk_id,
            storage_id=f"storage-{session_id}",
            course_id="math-course",
            lesson_id="math-course-lesson-1",
            source_file=None,
            start_ms=None,
            end_ms=None,
        )


if __name__ == "__main__":
    unittest.main()
