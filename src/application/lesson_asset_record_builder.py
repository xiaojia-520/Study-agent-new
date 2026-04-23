from __future__ import annotations

import json
import re
import time
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Mapping, Protocol

from src.core.documents.asset_files import (
    find_content_list_file,
    find_markdown_file,
    source_type_for_file,
)


class TranscriptRecordWriter(Protocol):
    def next_chunk_id(self, session_id: str) -> int: ...


class LessonAssetLike(Protocol):
    asset_id: str
    session_id: str
    course_id: str | None
    lesson_id: str | None
    subject: str | None
    file_name: str
    media_type: str
    batch_id: str | None


_AUXILIARY_TYPES = {"header", "footer", "page_number"}


class LessonAssetRecordBuilder:
    def __init__(self, *, transcript_writer: TranscriptRecordWriter) -> None:
        self.transcript_writer = transcript_writer

    def build_transcript_records(self, asset: LessonAssetLike, result_dir: Path) -> list[dict[str, Any]]:
        content_list_v2 = find_content_list_file(result_dir, suffix="_content_list_v2.json")
        if content_list_v2 is not None:
            records = self._records_from_content_list_v2(asset, content_list_v2)
            if records:
                return records

        content_list = find_content_list_file(result_dir, suffix="_content_list.json")
        if content_list is not None:
            records = self._records_from_content_list(asset, content_list)
            if records:
                return records

        markdown_path = find_markdown_file(result_dir)
        if markdown_path is None:
            raise FileNotFoundError("MinerU result zip did not contain full.md or content_list.json")
        return self._records_from_markdown(asset, markdown_path)

    def _records_from_content_list_v2(self, asset: LessonAssetLike, file_path: Path) -> list[dict[str, Any]]:
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
            records.append(
                self._make_asset_record(
                    asset,
                    next_chunk_id,
                    text,
                    page_index=page_index,
                    parser="content_list_v2",
                )
            )
            next_chunk_id += 1
        return records

    def _records_from_content_list(self, asset: LessonAssetLike, file_path: Path) -> list[dict[str, Any]]:
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
            records.append(
                self._make_asset_record(
                    asset,
                    next_chunk_id,
                    text,
                    page_index=page_index,
                    parser="content_list",
                )
            )
            next_chunk_id += 1
        return records

    def _records_from_markdown(self, asset: LessonAssetLike, file_path: Path) -> list[dict[str, Any]]:
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
        asset: LessonAssetLike,
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
            "source_type": source_type_for_file(asset.file_name),
            "source_file": asset.file_name,
            "text": text,
            "clean_text": text,
            "created_at": int(time.time()),
            "metadata": metadata,
        }


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


def _optional_int(value: Any, *, default: int | None = None) -> int | None:
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
