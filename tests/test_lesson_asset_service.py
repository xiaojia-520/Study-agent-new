import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace

from src.infrastructure.storage.sqlite_store import SQLiteStore
from web.backend.app.domain.session import RealtimeSession
from web.backend.app.services.lesson_asset_service import (
    LessonAssetService,
    MineruExtractResult,
    MineruUploadBatch,
)
from web.backend.app.services.transcript_service import TranscriptService


class FakeMineruClient:
    def __init__(self) -> None:
        self.uploaded = []

    def create_upload_batch(self, **kwargs):
        return MineruUploadBatch(batch_id="batch-a", file_urls=("https://upload.example/file",))

    def upload_file(self, upload_url, file_path):
        self.uploaded.append((upload_url, Path(file_path).name))

    def get_batch_results(self, batch_id):
        return [
            MineruExtractResult(
                file_name="slides.pdf",
                data_id=self.asset_id,
                state="done",
                full_zip_url="https://download.example/result.zip",
            )
        ]

    def download_result_zip(self, full_zip_url, target_path):
        content_list = [
            {"type": "text", "text": "Page one introduces binary trees.", "page_idx": 0},
            {"type": "equation", "text": "$$a+b=c$$", "page_idx": 0},
            {"type": "text", "text": "Page two introduces traversal.", "page_idx": 1},
        ]
        target_path.parent.mkdir(parents=True, exist_ok=True)
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("full.md", "# Slides\n\nBinary trees")
            archive.writestr("slides_content_list.json", json.dumps(content_list, ensure_ascii=False))
        target_path.write_bytes(buffer.getvalue())


class FakeIndexingService:
    def __init__(self) -> None:
        self.records = []

    def index_records(self, records, **kwargs):
        self.records.extend(records)
        return SimpleNamespace(record_count=len(records))


class LessonAssetServiceTests(unittest.TestCase):
    def test_parse_asset_writes_document_records_and_indexes_them(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SQLiteStore(Path(temp_dir) / "asset.sqlite3")
            transcript_service = TranscriptService(store=store)
            transcript_service.init_schema()
            mineru_client = FakeMineruClient()
            indexing_service = FakeIndexingService()
            runtime = SimpleNamespace(indexing_service=indexing_service, embed_model=object())
            service = LessonAssetService(
                store=store,
                mineru_client=mineru_client,
                transcript_writer=transcript_service,
                runtime_factory=lambda: runtime,
            )
            upload_path = Path(temp_dir) / "slides.pdf"
            upload_path.write_bytes(b"%PDF-1.4")

            asset = service.create_asset(
                asset_id="asset-a",
                session=self._session(),
                file_name="slides.pdf",
                file_path=upload_path,
                file_size=upload_path.stat().st_size,
                media_type="application/pdf",
            )
            mineru_client.asset_id = asset.asset_id

            service.parse_and_index_asset(asset.asset_id)

            updated = service.get_asset(asset.asset_id)
            self.assertIsNotNone(updated)
            self.assertEqual(updated.status, "done")
            self.assertEqual(updated.batch_id, "batch-a")
            self.assertEqual(updated.record_count, 2)

            records = transcript_service.list_session_transcripts(self._session(), "session-a")
            self.assertEqual(len(records), 2)
            self.assertEqual(records[0]["source_type"], "document")
            self.assertEqual(records[0]["metadata"]["asset_id"], "asset-a")
            self.assertEqual(records[0]["metadata"]["page_no"], 1)
            self.assertEqual(records[1]["metadata"]["page_no"], 2)
            self.assertEqual([record.chunk_id for record in indexing_service.records], [1, 2])

    @staticmethod
    def _session() -> RealtimeSession:
        return RealtimeSession(
            session_id="session-a",
            course_id="course-a",
            lesson_id="lesson-a",
            subject="data structures",
            created_at=100,
            updated_at=100,
        )


if __name__ == "__main__":
    unittest.main()
