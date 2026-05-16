from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any, Mapping

from config.settings import settings
from src.core.documents.asset_files import sanitize_asset_filename
from src.domain.lesson_asset import LessonAsset
from src.domain.session import RealtimeSession
from src.infrastructure.storage.database import DatabaseStore
from src.infrastructure.storage.runtime import database_store


class LessonAssetRepository:
    def __init__(self, *, store: DatabaseStore = database_store) -> None:
        self.store = store

    def init_schema(self) -> None:
        self.store.init_schema()

    def allocate_upload_path(self, *, session_id: str, file_name: str) -> tuple[str, str, Path]:
        asset_id = uuid.uuid4().hex
        safe_name = sanitize_asset_filename(file_name)
        target_dir = settings.ASSET_SAVE_DIR / session_id
        target_dir.mkdir(parents=True, exist_ok=True)
        return asset_id, safe_name, target_dir / f"{asset_id}_{safe_name}"

    def allocate_library_upload_path(self, *, file_name: str) -> tuple[str, str, Path]:
        asset_id = uuid.uuid4().hex
        safe_name = sanitize_asset_filename(file_name)
        target_dir = settings.ASSET_SAVE_DIR / "library"
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
        return self._create_asset_record(
            asset_id=asset_id,
            session_id=session.session_id,
            course_id=session.course_id,
            lesson_id=session.lesson_id,
            subject=session.subject,
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
        return self._create_asset_record(
            asset_id=asset_id,
            session_id=f"asset-{asset_id}",
            course_id=None,
            lesson_id=None,
            subject=subject,
            file_name=file_name,
            file_path=file_path,
            file_size=file_size,
            media_type=media_type,
            metadata=metadata,
        )

    def _create_asset_record(
        self,
        *,
        asset_id: str,
        session_id: str,
        course_id: str | None,
        lesson_id: str | None,
        subject: str | None,
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
                session_id,
                course_id,
                lesson_id,
                subject,
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

    def list_assets(self, *, limit: int = 100) -> list[LessonAsset]:
        rows = self.store.query_all(
            """
            SELECT *
            FROM lesson_assets
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (int(limit),),
        )
        return [_row_to_asset(row) for row in rows]

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

    def update_asset(self, asset_id: str, **changes: Any) -> None:
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
