from __future__ import annotations

import logging
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterable

from config.settings import settings
from src.application.documents.lesson_asset_record_builder import LessonAssetRecordBuilder
from src.application.rag.runtime import get_shared_rag_runtime
from src.core.knowledge.document_models import TranscriptRecord
from src.core.documents.asset_files import (
    find_markdown_file,
    safe_extract_zip,
    validate_asset_file_name,
)
from src.infrastructure.document.mineru_client import (
    MineruApiError,
    MineruClient,
    MineruExtractResult,
    MineruUploadBatch,
)
from src.infrastructure.storage.sqlite_store import SQLiteStore, sqlite_store
from web.backend.app.domain.assets import LessonAsset
from web.backend.app.domain.session import RealtimeSession
from web.backend.app.services.lesson_asset_repository import LessonAssetRepository
from web.backend.app.services.transcript_service import transcript_service

logger = logging.getLogger(__name__)


_FINAL_STATES = {"done", "failed"}


class LessonAssetService:
    """Orchestrate lesson asset upload records, MinerU parsing, transcript persistence, and RAG indexing."""

    def __init__(
        self,
        *,
        store: SQLiteStore = sqlite_store,
        mineru_client: MineruClient | None = None,
        transcript_writer=transcript_service,
        runtime_factory=get_shared_rag_runtime,
        repository: LessonAssetRepository | None = None,
        record_builder: LessonAssetRecordBuilder | None = None,
    ) -> None:
        self.repository = repository or LessonAssetRepository(store=store)
        self.store = self.repository.store
        self.mineru_client = mineru_client or MineruClient()
        self.transcript_writer = transcript_writer
        self.runtime_factory = runtime_factory
        self.record_builder = record_builder or LessonAssetRecordBuilder(
            transcript_writer=transcript_writer,
        )

    def init_schema(self) -> None:
        self.repository.init_schema()

    def allocate_upload_path(self, *, session_id: str, file_name: str) -> tuple[str, str, Path]:
        return self.repository.allocate_upload_path(session_id=session_id, file_name=file_name)

    def create_asset(
        self,
        *,
        asset_id: str,
        session: RealtimeSession,
        file_name: str,
        file_path: Path,
        file_size: int,
        media_type: str,
        metadata: dict[str, Any] | None = None,
    ) -> LessonAsset:
        return self.repository.create_asset(
            asset_id=asset_id,
            session=session,
            file_name=file_name,
            file_path=file_path,
            file_size=file_size,
            media_type=media_type,
            metadata=metadata,
        )

    def list_session_assets(self, session_id: str) -> list[LessonAsset]:
        return self.repository.list_session_assets(session_id)

    def get_asset(self, asset_id: str) -> LessonAsset | None:
        return self.repository.get_asset(asset_id)

    def parse_and_index_asset(self, asset_id: str) -> None:
        asset = self.get_asset(asset_id)
        if asset is None:
            logger.warning("Skip MinerU parsing because asset %s was not found", asset_id)
            return

        try:
            self._parse_and_index(asset)
        except Exception as exc:
            logger.exception("MinerU asset processing failed for %s: %s", asset_id, exc)
            self._update_asset(
                asset_id,
                status="failed",
                error_message=str(exc),
                mineru_state="failed",
            )

    def to_dict(self, asset: LessonAsset) -> dict[str, Any]:
        return asdict(asset)

    def _parse_and_index(self, asset: LessonAsset) -> None:
        file_path = Path(asset.file_path)
        if not file_path.exists():
            raise FileNotFoundError(file_path)

        self._update_asset(asset.asset_id, status="submitting")
        model_version = (
            "MinerU-HTML"
            if Path(asset.file_name).suffix.lower() == ".html"
            else settings.MINERU_MODEL_VERSION
        )
        batch = self.mineru_client.create_upload_batch(
            file_name=asset.file_name,
            data_id=asset.asset_id,
            model_version=model_version,
            language=settings.MINERU_LANGUAGE,
            enable_formula=settings.MINERU_ENABLE_FORMULA,
            enable_table=settings.MINERU_ENABLE_TABLE,
            is_ocr=settings.MINERU_IS_OCR,
        )
        self._update_asset(
            asset.asset_id,
            status="uploading",
            batch_id=batch.batch_id,
            mineru_state="waiting-file",
        )
        self.mineru_client.upload_file(batch.file_urls[0], file_path)

        self._update_asset(asset.asset_id, status="pending", mineru_state="waiting-file")
        result = self._poll_until_complete(asset, batch.batch_id)
        if result.state == "failed":
            raise MineruApiError(result.err_msg or "MinerU parsing failed")
        if not result.full_zip_url:
            raise MineruApiError("MinerU completed without a full_zip_url")

        self._update_asset(
            asset.asset_id,
            status="downloading",
            mineru_state=result.state,
            full_zip_url=result.full_zip_url,
        )
        result_dir = settings.MINERU_RESULT_DIR / asset.asset_id
        zip_path = result_dir / "result.zip"
        self.mineru_client.download_result_zip(result.full_zip_url, zip_path)
        safe_extract_zip(zip_path, result_dir)

        asset = self.get_asset(asset.asset_id) or asset
        records = self.record_builder.build_transcript_records(asset, result_dir)
        for record in records:
            self.transcript_writer.append_transcript_record(record)

        markdown_path = find_markdown_file(result_dir)
        indexed_at = None
        if settings.MINERU_AUTO_INDEX_ENABLED and records:
            try:
                runtime = self.runtime_factory()
                runtime.indexing_service.index_records(
                    [TranscriptRecord.from_dict(record) for record in records],
                    embed_model=runtime.embed_model,
                )
                indexed_at = int(time.time())
            except Exception as exc:
                self._update_asset(
                    asset.asset_id,
                    status="indexing_failed",
                    mineru_state="done",
                    result_dir=str(result_dir),
                    markdown_path=str(markdown_path) if markdown_path else None,
                    record_count=len(records),
                    error_message=str(exc),
                )
                return

        self._update_asset(
            asset.asset_id,
            status="done",
            mineru_state="done",
            result_dir=str(result_dir),
            markdown_path=str(markdown_path) if markdown_path else None,
            record_count=len(records),
            indexed_at=indexed_at,
            error_message=None,
        )

    def _poll_until_complete(self, asset: LessonAsset, batch_id: str) -> MineruExtractResult:
        deadline = time.monotonic() + settings.MINERU_POLL_TIMEOUT_SECONDS
        last_result: MineruExtractResult | None = None

        while time.monotonic() < deadline:
            results = self.mineru_client.get_batch_results(batch_id)
            result = _pick_extract_result(results, asset)
            if result is not None:
                last_result = result
                self._update_asset(
                    asset.asset_id,
                    status=_status_from_mineru_state(result.state),
                    mineru_state=result.state,
                    error_message=result.err_msg,
                    metadata={"extract_progress": result.extract_progress} if result.extract_progress else None,
                )
                if result.state in _FINAL_STATES:
                    return result
            time.sleep(settings.MINERU_POLL_INTERVAL_SECONDS)

        state = last_result.state if last_result is not None else "pending"
        raise TimeoutError(f"MinerU parsing did not finish before timeout; last state: {state}")

    def _update_asset(self, asset_id: str, **changes: Any) -> None:
        self.repository.update_asset(asset_id, **changes)


lesson_asset_service = LessonAssetService()


def _pick_extract_result(results: Iterable[MineruExtractResult], asset: LessonAsset) -> MineruExtractResult | None:
    materialized = list(results)
    for result in materialized:
        if result.data_id == asset.asset_id:
            return result
    for result in materialized:
        if result.file_name == asset.file_name:
            return result
    return materialized[0] if len(materialized) == 1 else None


def _status_from_mineru_state(state: str) -> str:
    if state == "done":
        return "parsed"
    if state == "failed":
        return "failed"
    if state in {"pending", "running", "converting", "waiting-file"}:
        return state
    return "processing"
