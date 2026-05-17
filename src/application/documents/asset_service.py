from __future__ import annotations

import concurrent.futures
import logging
import shutil
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

from pypdf import PdfReader, PdfWriter

from config.settings import settings
from src.application.documents.lesson_asset_record_builder import LessonAssetRecordBuilder
from src.application.rag.ingestion_service import KnowledgeIngestionService
from src.application.rag.runtime import get_shared_rag_runtime
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
from src.domain.lesson_asset import LessonAsset
from src.domain.session import RealtimeSession
from src.infrastructure.storage.database import DatabaseStore
from src.infrastructure.storage.lesson_asset_repository import LessonAssetRepository
from src.infrastructure.storage.runtime import database_store
from src.application.transcripts.service import transcript_service

logger = logging.getLogger(__name__)


_FINAL_STATES = {"done", "failed"}
_PDF_SPLIT_PAGE_LIMIT = 200
_MINERU_BATCH_FILE_LIMIT = 50


@dataclass(frozen=True, slots=True)
class _UploadPart:
    index: int
    data_id: str
    file_name: str
    file_path: Path
    page_start: int | None = None
    page_end: int | None = None


class LessonAssetService:
    """Orchestrate lesson asset upload records, MinerU parsing, transcript persistence, and RAG indexing."""

    def __init__(
        self,
        *,
        store: DatabaseStore = database_store,
        mineru_client: MineruClient | None = None,
        transcript_writer=transcript_service,
        runtime_factory=get_shared_rag_runtime,
        repository: LessonAssetRepository | None = None,
        record_builder: LessonAssetRecordBuilder | None = None,
        ingestion_service: KnowledgeIngestionService | None = None,
    ) -> None:
        self.repository = repository or LessonAssetRepository(store=store)
        self.store = self.repository.store
        self.mineru_client = mineru_client or MineruClient()
        self.transcript_writer = transcript_writer
        self.runtime_factory = runtime_factory
        self.ingestion_service = ingestion_service or KnowledgeIngestionService(
            transcript_writer=transcript_writer,
            runtime_factory=runtime_factory,
            rag_indexing_enabled=settings.MINERU_AUTO_INDEX_ENABLED,
        )
        self.record_builder = record_builder or LessonAssetRecordBuilder(
            transcript_writer=transcript_writer,
        )

    def init_schema(self) -> None:
        self.repository.init_schema()

    def allocate_upload_path(self, *, session_id: str, file_name: str) -> tuple[str, str, Path]:
        return self.repository.allocate_upload_path(session_id=session_id, file_name=file_name)

    def allocate_library_upload_path(self, *, file_name: str) -> tuple[str, str, Path]:
        return self.repository.allocate_library_upload_path(file_name=file_name)

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

    def create_library_asset(
        self,
        *,
        asset_id: str,
        file_name: str,
        file_path: Path,
        file_size: int,
        media_type: str,
        subject: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> LessonAsset:
        return self.repository.create_library_asset(
            asset_id=asset_id,
            file_name=file_name,
            file_path=file_path,
            file_size=file_size,
            media_type=media_type,
            subject=subject,
            metadata=metadata,
        )

    def list_assets(self, *, limit: int = 100) -> list[LessonAsset]:
        return self.repository.list_assets(limit=limit)

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
        except TimeoutError as exc:
            current = self.get_asset(asset_id) or asset
            timeout_state = _extract_timeout_state(str(exc)) or current.mineru_state or "running"
            logger.warning("MinerU asset processing timed out for %s: %s", asset_id, exc)
            self._update_asset(
                asset_id,
                status=_status_from_mineru_state(timeout_state),
                error_message=str(exc),
                mineru_state=timeout_state,
            )
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

        model_version = (
            "MinerU-HTML"
            if Path(asset.file_name).suffix.lower() == ".html"
            else settings.MINERU_MODEL_VERSION
        )
        result_dir = settings.MINERU_RESULT_DIR / asset.asset_id
        result_dir.mkdir(parents=True, exist_ok=True)
        split_work_dir = result_dir / "_split_uploads"
        should_resume = self._should_resume_batch(asset)
        parts = self._restore_upload_parts(asset, file_path=file_path) if should_resume else []
        results_by_id: dict[str, MineruExtractResult]

        try:
            if should_resume:
                if not asset.batch_id:
                    raise MineruApiError("Cannot resume MinerU batch because batch_id is missing")
                logger.info("Resuming MinerU batch %s for asset %s", asset.batch_id, asset.asset_id)
                results_by_id = self._poll_until_complete(
                    asset,
                    asset.batch_id,
                    expected_data_ids=[part.data_id for part in parts],
                )
            else:
                self._update_asset(asset.asset_id, status="submitting")
                parts = self._prepare_upload_parts(asset, file_path=file_path, split_work_dir=split_work_dir)
                source_page_count = self._count_pdf_pages(file_path)
                batch = self.mineru_client.create_upload_batch_for_files(
                    files=[
                        {
                            "name": part.file_name,
                            "data_id": part.data_id,
                            "is_ocr": settings.MINERU_IS_OCR,
                        }
                        for part in parts
                    ],
                    model_version=model_version,
                    language=settings.MINERU_LANGUAGE,
                    enable_formula=settings.MINERU_ENABLE_FORMULA,
                    enable_table=settings.MINERU_ENABLE_TABLE,
                )
                self._update_asset(
                    asset.asset_id,
                    status="uploading",
                    batch_id=batch.batch_id,
                    mineru_state="waiting-file",
                    metadata={
                        "source_file_name": asset.file_name,
                        "source_page_count": source_page_count,
                        "split_part_count": len(parts),
                        "split_ranges": [
                            {
                                "index": part.index,
                                "data_id": part.data_id,
                                "page_start": part.page_start,
                                "page_end": part.page_end,
                                "file_name": part.file_name,
                            }
                            for part in parts
                        ],
                    },
                )
                self._upload_parts_in_parallel(parts, batch.file_urls)

                self._update_asset(asset.asset_id, status="pending", mineru_state="waiting-file")
                results_by_id = self._poll_until_complete(
                    asset,
                    batch.batch_id,
                    expected_data_ids=[part.data_id for part in parts],
                )

            records, markdown_parts = self._download_and_merge_results(
                asset=self.get_asset(asset.asset_id) or asset,
                parts=parts,
                results_by_id=results_by_id,
                result_dir=result_dir,
            )
        finally:
            if not should_resume:
                shutil.rmtree(split_work_dir, ignore_errors=True)

        self.ingestion_service.persist_records(records)

        markdown_path = self._write_merged_markdown(
            result_dir=result_dir,
            file_name=asset.file_name,
            markdown_parts=markdown_parts,
        )
        indexed_at = None
        if settings.MINERU_AUTO_INDEX_ENABLED and records:
            try:
                self.ingestion_service.index_records_immediately(records)
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

    @staticmethod
    def _should_resume_batch(asset: LessonAsset) -> bool:
        return bool(
            asset.batch_id
            and asset.metadata.get("split_ranges")
            and asset.mineru_state in {"pending", "running", "converting", "waiting-file"}
        )

    @staticmethod
    def _restore_upload_parts(asset: LessonAsset, *, file_path: Path) -> list[_UploadPart]:
        ranges = asset.metadata.get("split_ranges")
        if not isinstance(ranges, list) or not ranges:
            return [
                _UploadPart(
                    index=1,
                    data_id=asset.asset_id,
                    file_name=asset.file_name,
                    file_path=file_path,
                )
            ]

        parts: list[_UploadPart] = []
        for index, item in enumerate(ranges, start=1):
            if not isinstance(item, dict):
                continue
            part_index = _as_int(item.get("index"), default=index)
            data_id = str(item.get("data_id") or "").strip() or asset.asset_id
            file_name = str(item.get("file_name") or "").strip() or asset.file_name
            parts.append(
                _UploadPart(
                    index=part_index,
                    data_id=data_id,
                    file_name=file_name,
                    file_path=file_path,
                    page_start=_as_int(item.get("page_start")),
                    page_end=_as_int(item.get("page_end")),
                )
            )
        return sorted(parts, key=lambda item: item.index)

    def _download_and_merge_results(
        self,
        *,
        asset: LessonAsset,
        parts: list[_UploadPart],
        results_by_id: dict[str, MineruExtractResult],
        result_dir: Path,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        self._update_asset(
            asset.asset_id,
            status="downloading",
            mineru_state="done",
            full_zip_url=next((result.full_zip_url for result in results_by_id.values() if result.full_zip_url), None),
        )

        records: list[dict[str, Any]] = []
        next_chunk_id = self.transcript_writer.next_chunk_id(asset.session_id)
        markdown_parts: list[str] = []

        for part in parts:
            result = results_by_id.get(part.data_id)
            if result is None:
                raise MineruApiError(f"MinerU result missing for split part {part.index}")
            if result.state == "failed":
                raise MineruApiError(result.err_msg or f"MinerU parsing failed for split part {part.index}")
            if not result.full_zip_url:
                raise MineruApiError(f"MinerU completed without a full_zip_url for split part {part.index}")

            part_result_dir = result_dir / f"part_{part.index:03d}"
            zip_path = part_result_dir / "result.zip"
            self.mineru_client.download_result_zip(result.full_zip_url, zip_path)
            safe_extract_zip(zip_path, part_result_dir)

            part_records = self.record_builder.build_transcript_records(asset, part_result_dir)
            for record in part_records:
                record["chunk_id"] = next_chunk_id
                next_chunk_id += 1
                metadata = dict(record.get("metadata") or {})
                metadata["asset_split_part_index"] = part.index
                metadata["asset_split_part_count"] = len(parts)
                if part.page_start is not None and "page_idx" in metadata:
                    try:
                        page_idx = int(metadata.get("page_idx") or 0) + max(0, part.page_start - 1)
                        metadata["page_idx"] = page_idx
                        metadata["page_no"] = page_idx + 1
                    except (TypeError, ValueError):
                        pass
                record["metadata"] = metadata
                record["source_file"] = asset.file_name
            records.extend(part_records)

            markdown_path = find_markdown_file(part_result_dir)
            if markdown_path is not None:
                markdown_text = markdown_path.read_text(encoding="utf-8").strip()
                if markdown_text:
                    if part.page_start is not None and part.page_end is not None:
                        header = f"<!-- split part {part.index}: pages {part.page_start}-{part.page_end} -->"
                    else:
                        header = f"<!-- split part {part.index} -->"
                    markdown_parts.append(f"{header}\n{markdown_text}")

        return records, markdown_parts

    def _prepare_upload_parts(
        self,
        asset: LessonAsset,
        *,
        file_path: Path,
        split_work_dir: Path,
    ) -> list[_UploadPart]:
        if file_path.suffix.lower() != ".pdf":
            return [
                _UploadPart(
                    index=1,
                    data_id=asset.asset_id,
                    file_name=asset.file_name,
                    file_path=file_path,
                )
            ]

        page_count = self._count_pdf_pages(file_path)
        if page_count is None or page_count <= _PDF_SPLIT_PAGE_LIMIT:
            return [
                _UploadPart(
                    index=1,
                    data_id=asset.asset_id,
                    file_name=asset.file_name,
                    file_path=file_path,
                    page_start=1 if page_count else None,
                    page_end=page_count,
                )
            ]

        split_work_dir.mkdir(parents=True, exist_ok=True)
        reader = PdfReader(str(file_path))
        parts: list[_UploadPart] = []
        stem = Path(asset.file_name).stem or "document"
        suffix = Path(asset.file_name).suffix or ".pdf"
        for part_index, start_page in enumerate(range(0, page_count, _PDF_SPLIT_PAGE_LIMIT), start=1):
            end_page = min(start_page + _PDF_SPLIT_PAGE_LIMIT, page_count)
            writer = PdfWriter()
            for page_index in range(start_page, end_page):
                writer.add_page(reader.pages[page_index])
            part_file_name = f"{stem}.part{part_index:03d}_p{start_page + 1:04d}-{end_page:04d}{suffix}"
            part_file_path = split_work_dir / part_file_name
            with part_file_path.open("wb") as handle:
                writer.write(handle)
            parts.append(
                _UploadPart(
                    index=part_index,
                    data_id=f"{asset.asset_id}::part-{part_index:03d}",
                    file_name=part_file_name,
                    file_path=part_file_path,
                    page_start=start_page + 1,
                    page_end=end_page,
                )
            )

        if len(parts) > _MINERU_BATCH_FILE_LIMIT:
            raise ValueError(
                f"PDF split produced {len(parts)} parts, exceeding MinerU batch limit "
                f"({_MINERU_BATCH_FILE_LIMIT} files); please split manually."
            )
        return parts

    @staticmethod
    def _count_pdf_pages(file_path: Path) -> int | None:
        if file_path.suffix.lower() != ".pdf":
            return None
        try:
            return len(PdfReader(str(file_path)).pages)
        except Exception as exc:
            logger.warning("Failed to inspect PDF page count for %s: %s", file_path, exc)
            return None

    def _upload_parts_in_parallel(self, parts: list[_UploadPart], file_urls: tuple[str, ...]) -> None:
        if len(parts) != len(file_urls):
            raise MineruApiError("MinerU upload URLs do not match the prepared split parts")
        if not parts:
            return

        with concurrent.futures.ThreadPoolExecutor(max_workers=min(4, len(parts))) as executor:
            futures = [
                executor.submit(self.mineru_client.upload_file, upload_url, part.file_path)
                for part, upload_url in zip(parts, file_urls, strict=True)
            ]
            for future in concurrent.futures.as_completed(futures):
                future.result()

    @staticmethod
    def _write_merged_markdown(
        *,
        result_dir: Path,
        file_name: str,
        markdown_parts: list[str],
    ) -> Path | None:
        if not markdown_parts:
            return None
        merged_path = result_dir / f"{Path(file_name).stem or 'asset'}_merged.md"
        merged_path.write_text("\n\n".join(markdown_parts).strip() + "\n", encoding="utf-8")
        return merged_path

    def _poll_until_complete(
        self,
        asset: LessonAsset,
        batch_id: str,
        *,
        expected_data_ids: list[str] | None = None,
    ) -> dict[str, MineruExtractResult]:
        deadline = time.monotonic() + settings.MINERU_POLL_TIMEOUT_SECONDS
        expected = list(expected_data_ids or [asset.asset_id])
        last_results: dict[str, MineruExtractResult] = {}

        while time.monotonic() < deadline:
            results = self.mineru_client.get_batch_results(batch_id)
            matched = _pick_extract_results(results, asset, expected)
            if matched:
                last_results = matched
                overall_state = _merge_mineru_states(result.state for result in matched.values())
                self._update_asset(
                    asset.asset_id,
                    status=_status_from_mineru_state(overall_state),
                    mineru_state=overall_state,
                    error_message=next((result.err_msg for result in matched.values() if result.err_msg), None),
                    metadata={
                        "extract_progress": {
                            data_id: result.extract_progress
                            for data_id, result in matched.items()
                            if result.extract_progress
                        },
                        "completed_part_count": sum(1 for result in matched.values() if result.state == "done"),
                        "total_part_count": len(expected),
                    },
                )
                if all(
                    data_id in matched and matched[data_id].state in _FINAL_STATES
                    for data_id in expected
                ):
                    return matched
            time.sleep(settings.MINERU_POLL_INTERVAL_SECONDS)

        state = _merge_mineru_states(result.state for result in last_results.values()) if last_results else "pending"
        raise TimeoutError(f"MinerU parsing did not finish before timeout; last state: {state}")

    def _update_asset(self, asset_id: str, **changes: Any) -> None:
        self.repository.update_asset(asset_id, **changes)


lesson_asset_service = LessonAssetService()


def _pick_extract_result(results: Iterable[MineruExtractResult], asset: LessonAsset) -> MineruExtractResult | None:
    matched = _pick_extract_results(results, asset, [asset.asset_id])
    return matched.get(asset.asset_id) if matched else None


def _pick_extract_results(
    results: Iterable[MineruExtractResult],
    asset: LessonAsset,
    expected_data_ids: Iterable[str],
) -> dict[str, MineruExtractResult]:
    materialized = list(results)
    expected = [str(value).strip() for value in expected_data_ids if str(value).strip()]
    matched: dict[str, MineruExtractResult] = {}
    for result in materialized:
        if result.data_id and result.data_id in expected:
            matched[result.data_id] = result
    if matched:
        return matched
    if len(expected) == 1:
        for result in materialized:
            if result.file_name == asset.file_name:
                return {expected[0]: result}
        if len(materialized) == 1:
            return {expected[0]: materialized[0]}
    return {}


def _merge_mineru_states(states: Iterable[str]) -> str:
    normalized = [str(state or "").strip() for state in states if str(state or "").strip()]
    if not normalized:
        return "pending"
    if any(state == "failed" for state in normalized):
        return "failed"
    if all(state == "done" for state in normalized):
        return "done"
    if any(state == "waiting-file" for state in normalized):
        return "waiting-file"
    if any(state == "running" for state in normalized):
        return "running"
    if any(state == "converting" for state in normalized):
        return "converting"
    if any(state == "pending" for state in normalized):
        return "pending"
    return "processing"


def _extract_timeout_state(message: str) -> str | None:
    text = str(message or "").strip()
    marker = "last state:"
    if marker not in text:
        return None
    return text.split(marker, 1)[1].strip() or None


def _as_int(value: Any, *, default: int | None = None) -> int | None:
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _status_from_mineru_state(state: str) -> str:
    if state == "done":
        return "parsed"
    if state == "failed":
        return "failed"
    if state in {"pending", "running", "converting", "waiting-file"}:
        return state
    return "processing"
