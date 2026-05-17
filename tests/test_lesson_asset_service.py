import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace

from pypdf import PdfWriter

from config.settings import settings
from src.infrastructure.storage.sqlite_store import SQLiteStore
from src.domain.session import RealtimeSession
from src.application.documents.asset_service import (
    LessonAssetService,
    MineruExtractResult,
    MineruUploadBatch,
)
from src.application.transcripts.service import TranscriptService


class FakeMineruClient:
    def __init__(self) -> None:
        self.uploaded = []
        self._files = []

    def create_upload_batch(self, **kwargs):
        return MineruUploadBatch(batch_id="batch-a", file_urls=("https://upload.example/file",))

    def create_upload_batch_for_files(self, *, files, **kwargs):
        self._files = list(files)
        return MineruUploadBatch(
            batch_id="batch-a",
            file_urls=tuple(f"https://upload.example/file-{index + 1}" for index, _ in enumerate(self._files)),
        )

    def upload_file(self, upload_url, file_path):
        self.uploaded.append((upload_url, Path(file_path).name))

    def get_batch_results(self, batch_id):
        if self._files:
            return [
                MineruExtractResult(
                    file_name=str(item["name"]),
                    data_id=str(item["data_id"]),
                    state="done",
                    full_zip_url=f"https://download.example/{index + 1}.zip",
                )
                for index, item in enumerate(self._files)
            ]
        return [
            MineruExtractResult(
                file_name="slides.pdf",
                data_id=self.asset_id,
                state="done",
                full_zip_url="https://download.example/result.zip",
            )
        ]

    def download_result_zip(self, full_zip_url, target_path):
        if full_zip_url.endswith("/1.zip"):
            content_list = [
                {"type": "text", "text": "Page one introduces binary trees.", "page_idx": 0},
                {"type": "equation", "text": "$$a+b=c$$", "page_idx": 0},
                {"type": "text", "text": "Page two introduces traversal.", "page_idx": 1},
            ]
        elif full_zip_url.endswith("/2.zip"):
            content_list = [
                {"type": "text", "text": "Page two hundred one discusses heaps.", "page_idx": 0},
                {"type": "text", "text": "Page two hundred five concludes.", "page_idx": 4},
            ]
        else:
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


class SlowFakeMineruClient(FakeMineruClient):
    def __init__(self) -> None:
        super().__init__()
        self.poll_count = 0

    def get_batch_results(self, batch_id):
        self.poll_count += 1
        if self.poll_count == 1:
            if self._files:
                return [
                    MineruExtractResult(
                        file_name=str(item["name"]),
                        data_id=str(item["data_id"]),
                        state="running",
                    )
                    for item in self._files
                ]
            return [
                MineruExtractResult(
                    file_name="slides.pdf",
                    data_id=self.asset_id,
                    state="running",
                )
            ]
        return super().get_batch_results(batch_id)


class LessonAssetServiceTests(unittest.TestCase):
    def test_create_library_asset_uses_independent_asset_session(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SQLiteStore(Path(temp_dir) / "asset.sqlite3")
            transcript_service = TranscriptService(store=store)
            transcript_service.init_schema()
            service = LessonAssetService(
                store=store,
                mineru_client=FakeMineruClient(),
                transcript_writer=transcript_service,
                runtime_factory=lambda: SimpleNamespace(indexing_service=FakeIndexingService(), embed_model=object()),
            )
            upload_path = Path(temp_dir) / "library.pdf"
            upload_path.write_bytes(b"%PDF-1.4")

            asset = service.create_library_asset(
                asset_id="asset-library",
                file_name="library.pdf",
                file_path=upload_path,
                file_size=upload_path.stat().st_size,
                media_type="application/pdf",
                subject="shared docs",
            )

            self.assertEqual(asset.session_id, "asset-asset-library")
            self.assertIsNone(asset.course_id)
            self.assertIsNone(asset.lesson_id)
            self.assertEqual(asset.subject, "shared docs")
            self.assertEqual(service.list_assets(limit=10)[0].asset_id, "asset-library")

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

    def test_parse_large_pdf_splits_upload_and_merges_page_numbers(self) -> None:
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
            upload_path = Path(temp_dir) / "book.pdf"
            self._write_pdf(upload_path, page_count=205)

            asset = service.create_asset(
                asset_id="asset-large",
                session=self._session(),
                file_name="book.pdf",
                file_path=upload_path,
                file_size=upload_path.stat().st_size,
                media_type="application/pdf",
            )
            mineru_client.asset_id = asset.asset_id

            service.parse_and_index_asset(asset.asset_id)

            updated = service.get_asset(asset.asset_id)
            self.assertIsNotNone(updated)
            self.assertEqual(updated.status, "done")
            self.assertEqual(updated.record_count, 4)
            self.assertEqual(updated.metadata["split_part_count"], 2)
            self.assertEqual(len(mineru_client.uploaded), 2)
            self.assertTrue(updated.markdown_path)

            records = transcript_service.list_session_transcripts(self._session(), "session-a")
            self.assertEqual(len(records), 4)
            self.assertEqual([item["metadata"]["page_no"] for item in records], [1, 2, 201, 205])
            self.assertEqual([record.chunk_id for record in indexing_service.records], [1, 2, 3, 4])

    def test_timeout_can_resume_existing_batch_without_reupload(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            original_timeout = settings.MINERU_POLL_TIMEOUT_SECONDS
            original_interval = settings.MINERU_POLL_INTERVAL_SECONDS
            try:
                settings.MINERU_POLL_TIMEOUT_SECONDS = 0.01
                settings.MINERU_POLL_INTERVAL_SECONDS = 0.001

                store = SQLiteStore(Path(temp_dir) / "asset.sqlite3")
                transcript_service = TranscriptService(store=store)
                transcript_service.init_schema()
                mineru_client = SlowFakeMineruClient()
                indexing_service = FakeIndexingService()
                runtime = SimpleNamespace(indexing_service=indexing_service, embed_model=object())
                service = LessonAssetService(
                    store=store,
                    mineru_client=mineru_client,
                    transcript_writer=transcript_service,
                    runtime_factory=lambda: runtime,
                )
                upload_path = Path(temp_dir) / "book.pdf"
                self._write_pdf(upload_path, page_count=205)

                asset = service.create_asset(
                    asset_id="asset-timeout",
                    session=self._session(),
                    file_name="book.pdf",
                    file_path=upload_path,
                    file_size=upload_path.stat().st_size,
                    media_type="application/pdf",
                )
                mineru_client.asset_id = asset.asset_id

                service.parse_and_index_asset(asset.asset_id)
                timed_out = service.get_asset(asset.asset_id)
                self.assertIsNotNone(timed_out)
                self.assertEqual(timed_out.status, "running")
                self.assertEqual(timed_out.mineru_state, "running")
                first_upload_count = len(mineru_client.uploaded)

                settings.MINERU_POLL_TIMEOUT_SECONDS = 5
                settings.MINERU_POLL_INTERVAL_SECONDS = 0.001
                service.parse_and_index_asset(asset.asset_id)

                resumed = service.get_asset(asset.asset_id)
                self.assertIsNotNone(resumed)
                self.assertEqual(resumed.status, "done")
                self.assertEqual(len(mineru_client.uploaded), first_upload_count)
                records = transcript_service.list_session_transcripts(self._session(), "session-a")
                self.assertEqual(len(records), 4)
            finally:
                settings.MINERU_POLL_TIMEOUT_SECONDS = original_timeout
                settings.MINERU_POLL_INTERVAL_SECONDS = original_interval

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

    @staticmethod
    def _write_pdf(path: Path, *, page_count: int) -> None:
        writer = PdfWriter()
        for _ in range(page_count):
            writer.add_blank_page(width=595, height=842)
        with path.open("wb") as handle:
            writer.write(handle)


if __name__ == "__main__":
    unittest.main()
