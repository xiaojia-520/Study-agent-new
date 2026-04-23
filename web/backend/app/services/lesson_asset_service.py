from __future__ import annotations

import json
import logging
import re
import time
import uuid
import zipfile
from dataclasses import asdict, dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable, Mapping

import requests

from config.settings import settings
from src.application.rag_runtime import get_shared_rag_runtime
from src.core.knowledge.document_models import TranscriptRecord
from src.infrastructure.storage.sqlite_store import SQLiteStore, sqlite_store
from web.backend.app.domain.assets import LessonAsset
from web.backend.app.domain.session import RealtimeSession
from web.backend.app.services.transcript_service import transcript_service

logger = logging.getLogger(__name__)


_FINAL_STATES = {"done", "failed"}
_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".jp2", ".webp", ".gif", ".bmp"}
_SLIDE_EXTENSIONS = {".ppt", ".pptx"}
_SUPPORTED_EXTENSIONS = {
    ".pdf",
    ".doc",
    ".docx",
    ".ppt",
    ".pptx",
    ".png",
    ".jpg",
    ".jpeg",
    ".jp2",
    ".webp",
    ".gif",
    ".bmp",
    ".html",
}
_AUXILIARY_TYPES = {"header", "footer", "page_number"}


class MineruApiError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class MineruUploadBatch:
    batch_id: str
    file_urls: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MineruExtractResult:
    file_name: str | None
    state: str
    data_id: str | None = None
    full_zip_url: str | None = None
    err_msg: str | None = None
    extract_progress: dict[str, Any] | None = None


class MineruClient:
    def __init__(
        self,
        *,
        token: str | None = None,
        base_url: str | None = None,
        request_timeout: float | None = None,
        upload_timeout: float | None = None,
        download_timeout: float | None = None,
        session: requests.Session | None = None,
    ) -> None:
        self.token = (token if token is not None else settings.MINERU_API_TOKEN).strip()
        self.base_url = (base_url or settings.MINERU_BASE_URL).rstrip("/")
        self.request_timeout = float(request_timeout or settings.MINERU_REQUEST_TIMEOUT_SECONDS)
        self.upload_timeout = float(upload_timeout or settings.MINERU_UPLOAD_TIMEOUT_SECONDS)
        self.download_timeout = float(download_timeout or settings.MINERU_DOWNLOAD_TIMEOUT_SECONDS)
        self.session = session or requests.Session()

    def create_upload_batch(
        self,
        *,
        file_name: str,
        data_id: str,
        model_version: str,
        language: str,
        enable_formula: bool,
        enable_table: bool,
        is_ocr: bool,
    ) -> MineruUploadBatch:
        payload = {
            "files": [
                {
                    "name": file_name,
                    "data_id": data_id,
                    "is_ocr": is_ocr,
                }
            ],
            "model_version": model_version,
            "language": language,
            "enable_formula": enable_formula,
            "enable_table": enable_table,
        }
        data = self._request_json("POST", "/api/v4/file-urls/batch", json_payload=payload)
        batch_id = str(data.get("batch_id") or "").strip()
        file_urls = tuple(str(url) for url in data.get("file_urls") or [] if str(url).strip())
        if not batch_id or not file_urls:
            raise MineruApiError("MinerU did not return a batch_id and upload URL")
        return MineruUploadBatch(batch_id=batch_id, file_urls=file_urls)

    def upload_file(self, upload_url: str, file_path: Path) -> None:
        with Path(file_path).open("rb") as handle:
            response = self.session.put(upload_url, data=handle, timeout=self.upload_timeout)
        if response.status_code not in {200, 201, 204}:
            raise MineruApiError(f"MinerU file upload failed: HTTP {response.status_code}")

    def get_batch_results(self, batch_id: str) -> list[MineruExtractResult]:
        data = self._request_json("GET", f"/api/v4/extract-results/batch/{batch_id}")
        results = data.get("extract_result") or []
        if not isinstance(results, list):
            raise MineruApiError("MinerU returned an invalid extract_result payload")
        return [
            MineruExtractResult(
                file_name=_optional_str(item.get("file_name")),
                state=str(item.get("state") or "").strip(),
                data_id=_optional_str(item.get("data_id")),
                full_zip_url=_optional_str(item.get("full_zip_url")),
                err_msg=_optional_str(item.get("err_msg")),
                extract_progress=item.get("extract_progress") if isinstance(item.get("extract_progress"), dict) else None,
            )
            for item in results
            if isinstance(item, Mapping)
        ]

    def download_result_zip(self, full_zip_url: str, target_path: Path) -> None:
        response = self.session.get(full_zip_url, stream=True, timeout=self.download_timeout)
        if response.status_code != 200:
            raise MineruApiError(f"MinerU result download failed: HTTP {response.status_code}")
        target_path.parent.mkdir(parents=True, exist_ok=True)
        with target_path.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    handle.write(chunk)

    def _request_json(self, method: str, path: str, *, json_payload: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self.token:
            raise MineruApiError("MINERU_API_TOKEN is required")

        url = f"{self.base_url}{path}"
        headers = {
            "Accept": "*/*",
            "Authorization": f"Bearer {self.token}",
        }
        if json_payload is not None:
            headers["Content-Type"] = "application/json"

        response = self.session.request(
            method,
            url,
            json=json_payload,
            headers=headers,
            timeout=self.request_timeout,
        )
        try:
            body = response.json()
        except ValueError as exc:
            raise MineruApiError(f"MinerU returned non-JSON response: HTTP {response.status_code}") from exc

        if response.status_code != 200:
            message = body.get("msg") if isinstance(body, dict) else None
            raise MineruApiError(message or f"MinerU request failed: HTTP {response.status_code}")
        if not isinstance(body, dict):
            raise MineruApiError("MinerU returned an invalid response body")
        if body.get("code") != 0:
            code = body.get("code")
            message = body.get("msg") or "MinerU request failed"
            raise MineruApiError(f"{message} ({code})")
        data = body.get("data")
        if not isinstance(data, dict):
            raise MineruApiError("MinerU returned an invalid data payload")
        return data


class LessonAssetService:
    def __init__(
        self,
        *,
        store: SQLiteStore = sqlite_store,
        mineru_client: MineruClient | None = None,
        transcript_writer=transcript_service,
        runtime_factory=get_shared_rag_runtime,
    ) -> None:
        self.store = store
        self.mineru_client = mineru_client or MineruClient()
        self.transcript_writer = transcript_writer
        self.runtime_factory = runtime_factory

    def init_schema(self) -> None:
        self.store.init_schema()

    def allocate_upload_path(self, *, session_id: str, file_name: str) -> tuple[str, str, Path]:
        asset_id = uuid.uuid4().hex
        safe_name = _sanitize_filename(file_name)
        target_dir = settings.ASSET_SAVE_DIR / session_id
        target_dir.mkdir(parents=True, exist_ok=True)
        return asset_id, safe_name, target_dir / f"{asset_id}_{safe_name}"

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
        if file_size <= 0:
            raise ValueError("uploaded file is empty")
        if file_size > settings.MINERU_MAX_UPLOAD_BYTES:
            raise ValueError("uploaded file exceeds MinerU precise API size limit")

        now = int(time.time())
        self.store.execute(
            """
            INSERT INTO lesson_assets (
                asset_id, session_id, course_id, lesson_id, subject,
                file_name, file_path, file_size, media_type, status,
                created_at, updated_at, metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                asset_id,
                session.session_id,
                session.course_id,
                session.lesson_id,
                session.subject,
                file_name,
                str(file_path),
                int(file_size),
                media_type,
                "uploaded",
                now,
                now,
                _encode_metadata(metadata),
            ),
        )
        asset = self.get_asset(asset_id)
        if asset is None:
            raise RuntimeError("failed to create lesson asset")
        return asset

    def list_session_assets(self, session_id: str) -> list[LessonAsset]:
        rows = self.store.query_all(
            """
            SELECT *
            FROM lesson_assets
            WHERE session_id = ?
            ORDER BY created_at DESC, id DESC
            """,
            (session_id,),
        )
        return [_row_to_asset(row) for row in rows]

    def get_asset(self, asset_id: str) -> LessonAsset | None:
        rows = self.store.query_all(
            """
            SELECT *
            FROM lesson_assets
            WHERE asset_id = ?
            LIMIT 1
            """,
            (asset_id,),
        )
        return _row_to_asset(rows[0]) if rows else None

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
        _safe_extract_zip(zip_path, result_dir)

        asset = self.get_asset(asset.asset_id) or asset
        records = self._build_transcript_records(asset, result_dir)
        for record in records:
            self.transcript_writer.append_transcript_record(record)

        markdown_path = _find_markdown_file(result_dir)
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

    def _build_transcript_records(self, asset: LessonAsset, result_dir: Path) -> list[dict[str, Any]]:
        content_list_v2 = _find_content_list_file(result_dir, suffix="_content_list_v2.json")
        if content_list_v2 is not None:
            records = self._records_from_content_list_v2(asset, content_list_v2)
            if records:
                return records

        content_list = _find_content_list_file(result_dir, suffix="_content_list.json")
        if content_list is not None:
            records = self._records_from_content_list(asset, content_list)
            if records:
                return records

        markdown_path = _find_markdown_file(result_dir)
        if markdown_path is None:
            raise FileNotFoundError("MinerU result zip did not contain full.md or content_list.json")
        return self._records_from_markdown(asset, markdown_path)

    def _records_from_content_list_v2(self, asset: LessonAsset, file_path: Path) -> list[dict[str, Any]]:
        payload = _read_json(file_path)
        if not isinstance(payload, list):
            return []

        records: list[dict[str, Any]] = []
        next_chunk_id = self.transcript_writer.next_chunk_id(asset.session_id)
        for page_index, page_items in enumerate(payload):
            if not isinstance(page_items, list):
                continue
            text = "\n".join(
                part
                for part in (_text_from_content_list_v2_item(item) for item in page_items if isinstance(item, dict))
                if part
            ).strip()
            if not text:
                continue
            records.append(self._make_asset_record(asset, next_chunk_id, text, page_index=page_index, parser="content_list_v2"))
            next_chunk_id += 1
        return records

    def _records_from_content_list(self, asset: LessonAsset, file_path: Path) -> list[dict[str, Any]]:
        payload = _read_json(file_path)
        if not isinstance(payload, list):
            return []

        pages: dict[int, list[str]] = {}
        for item in payload:
            if not isinstance(item, dict):
                continue
            page_index = _optional_int(item.get("page_idx"), default=0)
            text = _text_from_content_list_item(item)
            if not text:
                continue
            pages.setdefault(page_index, []).append(text)

        records: list[dict[str, Any]] = []
        next_chunk_id = self.transcript_writer.next_chunk_id(asset.session_id)
        for page_index in sorted(pages):
            text = "\n".join(pages[page_index]).strip()
            if not text:
                continue
            records.append(self._make_asset_record(asset, next_chunk_id, text, page_index=page_index, parser="content_list"))
            next_chunk_id += 1
        return records

    def _records_from_markdown(self, asset: LessonAsset, file_path: Path) -> list[dict[str, Any]]:
        text = file_path.read_text(encoding="utf-8").strip()
        if not text:
            return []
        records: list[dict[str, Any]] = []
        next_chunk_id = self.transcript_writer.next_chunk_id(asset.session_id)
        for segment in _split_markdown(text):
            records.append(self._make_asset_record(asset, next_chunk_id, segment, parser="markdown"))
            next_chunk_id += 1
        return records

    def _make_asset_record(
        self,
        asset: LessonAsset,
        chunk_id: int,
        text: str,
        *,
        parser: str,
        page_index: int | None = None,
    ) -> dict[str, Any]:
        metadata: dict[str, Any] = {
            "asset_id": asset.asset_id,
            "asset_file_name": asset.file_name,
            "media_type": asset.media_type,
            "mineru_batch_id": asset.batch_id,
            "mineru_parser": parser,
        }
        if page_index is not None:
            metadata["page_idx"] = page_index
            metadata["page_no"] = page_index + 1

        return {
            "session_id": asset.session_id,
            "storage_id": f"asset-{asset.asset_id}",
            "course_id": asset.course_id,
            "lesson_id": asset.lesson_id,
            "chunk_id": chunk_id,
            "subject": asset.subject or asset.file_name,
            "source_type": _source_type_for_file(asset.file_name),
            "source_file": asset.file_name,
            "text": text,
            "clean_text": text,
            "created_at": int(time.time()),
            "metadata": metadata,
        }

    def _update_asset(self, asset_id: str, **changes: Any) -> None:
        if "metadata" in changes:
            metadata = changes.pop("metadata")
            if metadata is not None:
                existing = self.get_asset(asset_id)
                merged = dict(existing.metadata if existing is not None else {})
                merged.update(metadata)
                changes["metadata_json"] = _encode_metadata(merged)
        changes["updated_at"] = int(time.time())
        assignments = ", ".join(f"{key} = ?" for key in changes)
        values = list(changes.values())
        values.append(asset_id)
        self.store.execute(
            f"""
            UPDATE lesson_assets
            SET {assignments}
            WHERE asset_id = ?
            """,
            values,
        )


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


def _row_to_asset(row: Mapping[str, Any]) -> LessonAsset:
    return LessonAsset(
        id=int(row["id"]),
        asset_id=str(row["asset_id"]),
        session_id=str(row["session_id"]),
        course_id=_optional_str(row.get("course_id")),
        lesson_id=_optional_str(row.get("lesson_id")),
        subject=_optional_str(row.get("subject")),
        file_name=str(row["file_name"]),
        file_path=str(row["file_path"]),
        file_size=int(row["file_size"]),
        media_type=str(row["media_type"]),
        status=str(row["status"]),
        batch_id=_optional_str(row.get("batch_id")),
        mineru_state=_optional_str(row.get("mineru_state")),
        full_zip_url=_optional_str(row.get("full_zip_url")),
        result_dir=_optional_str(row.get("result_dir")),
        markdown_path=_optional_str(row.get("markdown_path")),
        record_count=int(row.get("record_count") or 0),
        indexed_at=_optional_int(row.get("indexed_at")),
        error_message=_optional_str(row.get("error_message")),
        created_at=int(row["created_at"]),
        updated_at=int(row["updated_at"]),
        metadata=_decode_metadata(row.get("metadata_json")),
    )


def _sanitize_filename(file_name: str) -> str:
    name = Path(file_name or "document").name.strip() or "document"
    cleaned = re.sub(r"[^\w.\-\u4e00-\u9fff]+", "_", name)
    cleaned = re.sub(r"_+", "_", cleaned).strip("._")
    return cleaned or "document"


def validate_asset_file_name(file_name: str) -> None:
    extension = Path(file_name or "").suffix.lower()
    if extension not in _SUPPORTED_EXTENSIONS:
        supported = ", ".join(sorted(_SUPPORTED_EXTENSIONS))
        raise ValueError(f"unsupported asset file type; supported extensions: {supported}")


def _source_type_for_file(file_name: str) -> str:
    extension = Path(file_name).suffix.lower()
    if extension in _IMAGE_EXTENSIONS:
        return "image"
    if extension in _SLIDE_EXTENSIONS:
        return "slide"
    return "document"


def _safe_extract_zip(zip_path: Path, result_dir: Path) -> None:
    result_dir.mkdir(parents=True, exist_ok=True)
    root = result_dir.resolve()
    with zipfile.ZipFile(zip_path) as archive:
        for member in archive.infolist():
            target_path = (result_dir / member.filename).resolve()
            if root not in target_path.parents and target_path != root:
                raise ValueError(f"unsafe path in MinerU zip: {member.filename}")
        archive.extractall(result_dir)


def _find_markdown_file(result_dir: Path) -> Path | None:
    full_md = [path for path in result_dir.rglob("full.md") if path.is_file()]
    if full_md:
        return sorted(full_md)[0]
    markdown_files = [path for path in result_dir.rglob("*.md") if path.is_file()]
    return sorted(markdown_files)[0] if markdown_files else None


def _find_content_list_file(result_dir: Path, *, suffix: str) -> Path | None:
    matches = [
        path
        for path in result_dir.rglob("*.json")
        if path.is_file() and (path.name == suffix.lstrip("_") or path.name.endswith(suffix))
    ]
    return sorted(matches)[0] if matches else None


def _read_json(file_path: Path) -> Any:
    with file_path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _text_from_content_list_item(item: Mapping[str, Any]) -> str:
    item_type = str(item.get("type") or "").strip()
    if item_type in _AUXILIARY_TYPES:
        return ""
    parts: list[str] = []
    if item.get("text"):
        parts.append(str(item["text"]))
    if item.get("content"):
        parts.append(str(item["content"]))
    if item.get("table_body"):
        parts.append(_html_to_text(str(item["table_body"])))
    if item.get("code_body"):
        parts.append(str(item["code_body"]))
    if isinstance(item.get("list_items"), list):
        parts.extend(str(value) for value in item["list_items"] if str(value).strip())
    for key in ("image_caption", "image_footnote", "table_caption", "table_footnote", "chart_caption", "chart_footnote"):
        value = item.get(key)
        if isinstance(value, list):
            parts.extend(str(part) for part in value if str(part).strip())
    return "\n".join(part.strip() for part in parts if part and part.strip())


def _text_from_content_list_v2_item(item: Mapping[str, Any]) -> str:
    item_type = str(item.get("type") or "").strip()
    if item_type in _AUXILIARY_TYPES:
        return ""
    content = item.get("content")
    if item_type == "title" and isinstance(content, Mapping):
        text = _flatten_content(content.get("title_content"))
        level = _optional_int(content.get("level"), default=1)
        return f"{'#' * max(1, min(level, 6))} {text}".strip()
    if isinstance(content, Mapping):
        return _flatten_content(content)
    return _flatten_content(content)


def _flatten_content(value: Any) -> str:
    parts: list[str] = []
    _collect_text(value, parts)
    return "\n".join(part for part in parts if part).strip()


def _collect_text(value: Any, parts: list[str]) -> None:
    if value is None:
        return
    if isinstance(value, str):
        text = value.strip()
        if text:
            parts.append(_html_to_text(text) if "<" in text and ">" in text else text)
        return
    if isinstance(value, Mapping):
        if "content" in value and len(value) <= 3:
            _collect_text(value.get("content"), parts)
            return
        for key, item in value.items():
            key_text = str(key)
            if key_text.endswith("_path") or key_text in {"bbox", "anchor", "type", "level"}:
                continue
            _collect_text(item, parts)
        return
    if isinstance(value, list):
        for item in value:
            _collect_text(item, parts)
        return
    if isinstance(value, (int, float)):
        return
    text = str(value).strip()
    if text:
        parts.append(text)


class _HtmlTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        text = data.strip()
        if text:
            self.parts.append(text)


def _html_to_text(value: str) -> str:
    parser = _HtmlTextExtractor()
    parser.feed(value)
    text = " ".join(parser.parts).strip()
    return text or value


def _split_markdown(text: str, *, max_chars: int = 2400) -> list[str]:
    paragraphs = [part.strip() for part in re.split(r"\n{2,}", text) if part.strip()]
    segments: list[str] = []
    current = ""
    for paragraph in paragraphs:
        projected = paragraph if not current else f"{current}\n\n{paragraph}"
        if current and len(projected) > max_chars:
            segments.append(current)
            current = paragraph
            continue
        current = projected
    if current:
        segments.append(current)
    return segments or [text]


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_int(value: Any, *, default: int | None = None) -> int | None:
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _encode_metadata(value: dict[str, Any] | None) -> str | None:
    if not value:
        return None
    return json.dumps(value, ensure_ascii=False, default=str)


def _decode_metadata(value: Any) -> dict[str, Any]:
    if not value:
        return {}
    try:
        payload = json.loads(str(value))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}
