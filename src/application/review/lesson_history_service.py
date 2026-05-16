from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
from typing import Any

from config.settings import settings
from src.application.rag.runtime import get_shared_rag_runtime
from src.core.knowledge.query_filters import MetadataFilterClause, MetadataFilterSpec
from src.infrastructure.storage.database import DatabaseStore
from src.infrastructure.storage.runtime import database_store

logger = logging.getLogger(__name__)


class LessonHistoryService:
    def __init__(
        self,
        *,
        store: DatabaseStore = database_store,
        rag_runtime_factory=get_shared_rag_runtime,
    ) -> None:
        self.store = store
        self.rag_runtime_factory = rag_runtime_factory

    def delete_lesson(self, *, course_id: str, lesson_id: str) -> dict[str, Any]:
        normalized_course_id = _required_text(course_id, "course_id")
        normalized_lesson_id = _required_text(lesson_id, "lesson_id")
        context = self._collect_context(
            course_id=normalized_course_id,
            lesson_id=normalized_lesson_id,
        )

        self._delete_rag(course_id=normalized_course_id, lesson_id=normalized_lesson_id)
        self._delete_sql(course_id=normalized_course_id, lesson_id=normalized_lesson_id)
        file_summary = self._delete_files(
            course_id=normalized_course_id,
            lesson_id=normalized_lesson_id,
            context=context,
        )
        return {
            "deleted": True,
            "course_id": normalized_course_id,
            "lesson_id": normalized_lesson_id,
            "counts": {
                "chat_messages": context["chat_message_count"],
                "transcript_records": context["transcript_record_count"],
                "refined_transcript_records": context["refined_record_count"],
                "lesson_assets": context["asset_count"],
                "lesson_videos": context["video_count"],
                "lesson_notes": context["note_count"],
                **file_summary,
            },
        }

    def _collect_context(self, *, course_id: str, lesson_id: str) -> dict[str, Any]:
        chat_rows = self.store.query_all(
            """
            SELECT id, session_id
            FROM chat_messages
            WHERE course_id = ? AND lesson_id = ?
            """,
            (course_id, lesson_id),
        )
        transcript_rows = self.store.query_all(
            """
            SELECT id, session_id, storage_id, source_file
            FROM transcript_records
            WHERE course_id = ? AND lesson_id = ?
            """,
            (course_id, lesson_id),
        )
        refined_rows = self.store.query_all(
            """
            SELECT id, session_id
            FROM refined_transcript_records
            WHERE course_id = ? AND lesson_id = ?
            """,
            (course_id, lesson_id),
        )
        asset_rows = self.store.query_all(
            """
            SELECT id, session_id, file_path, result_dir, markdown_path
            FROM lesson_assets
            WHERE course_id = ? AND lesson_id = ?
            """,
            (course_id, lesson_id),
        )
        video_rows = self.store.query_all(
            """
            SELECT id, session_id, file_path, wav_path, srt_path
            FROM lesson_videos
            WHERE course_id = ? AND lesson_id = ?
            """,
            (course_id, lesson_id),
        )
        note_rows = self.store.query_all(
            """
            SELECT id
            FROM lesson_notes
            WHERE course_id = ? AND lesson_id = ?
            """,
            (course_id, lesson_id),
        )
        session_ids = {
            str(row["session_id"]).strip()
            for rows in (chat_rows, transcript_rows, refined_rows, asset_rows, video_rows)
            for row in rows
            if row.get("session_id")
        }
        storage_ids = {
            str(row["storage_id"]).strip()
            for row in transcript_rows
            if row.get("storage_id")
        }
        return {
            "chat_message_count": len(chat_rows),
            "transcript_record_count": len(transcript_rows),
            "refined_record_count": len(refined_rows),
            "asset_count": len(asset_rows),
            "video_count": len(video_rows),
            "note_count": len(note_rows),
            "assets": asset_rows,
            "videos": video_rows,
            "session_ids": session_ids,
            "storage_ids": storage_ids,
        }

    def _delete_rag(self, *, course_id: str, lesson_id: str) -> None:
        runtime = self.rag_runtime_factory()
        runtime.index_store.delete_by_metadata(
            MetadataFilterSpec(
                clauses=(
                    MetadataFilterClause("course_id", course_id),
                    MetadataFilterClause("lesson_id", lesson_id),
                )
            )
        )

    def _delete_sql(self, *, course_id: str, lesson_id: str) -> None:
        statements = (
            ("DELETE FROM lesson_notes WHERE course_id = ? AND lesson_id = ?", (course_id, lesson_id)),
            (
                "DELETE FROM refined_transcript_records WHERE course_id = ? AND lesson_id = ?",
                (course_id, lesson_id),
            ),
            ("DELETE FROM lesson_assets WHERE course_id = ? AND lesson_id = ?", (course_id, lesson_id)),
            ("DELETE FROM lesson_videos WHERE course_id = ? AND lesson_id = ?", (course_id, lesson_id)),
            ("DELETE FROM chat_messages WHERE course_id = ? AND lesson_id = ?", (course_id, lesson_id)),
            ("DELETE FROM transcript_records WHERE course_id = ? AND lesson_id = ?", (course_id, lesson_id)),
        )
        for sql, params in statements:
            self.store.execute(sql, params)

    def _delete_files(self, *, course_id: str, lesson_id: str, context: dict[str, Any]) -> dict[str, int]:
        deleted_files = 0
        deleted_dirs = 0

        managed_roots = (
            settings.ASSET_SAVE_DIR,
            settings.VIDEO_SAVE_DIR,
            settings.VIDEO_SUBTITLE_DIR,
            settings.MINERU_RESULT_DIR,
        )
        removable_paths: list[tuple[Path, bool]] = []
        for row in context["assets"]:
            removable_paths.extend(
                (
                    (Path(str(row["file_path"])), False),
                    (_optional_path(row.get("markdown_path")), False),
                    (_optional_path(row.get("result_dir")), True),
                )
            )
        for row in context["videos"]:
            removable_paths.extend(
                (
                    (Path(str(row["file_path"])), False),
                    (_optional_path(row.get("wav_path")), False),
                    (_optional_path(row.get("srt_path")), False),
                )
            )

        seen_paths: set[Path] = set()
        for candidate, is_dir in removable_paths:
            if candidate is None:
                continue
            resolved = candidate.resolve(strict=False)
            if resolved in seen_paths:
                continue
            seen_paths.add(resolved)
            if not _is_within_roots(resolved, managed_roots):
                logger.warning("Skip deleting unmanaged path %s", resolved)
                continue
            removed = _remove_path(resolved, is_dir=is_dir)
            if not removed:
                continue
            if is_dir:
                deleted_dirs += 1
            else:
                deleted_files += 1
            _cleanup_empty_parents(resolved.parent, stop_roots=managed_roots)

        for session_id in context["session_ids"]:
            for root in (settings.ASSET_SAVE_DIR, settings.VIDEO_SAVE_DIR):
                session_dir = (root / session_id).resolve(strict=False)
                if session_dir.exists() and _is_within_roots(session_dir, (root,)):
                    if _remove_path(session_dir, is_dir=True):
                        deleted_dirs += 1

        subtitle_dirs = list(settings.VIDEO_SUBTITLE_DIR.glob("*"))
        for subtitle_dir in subtitle_dirs:
            if subtitle_dir.is_dir() and not any(subtitle_dir.iterdir()):
                if _remove_path(subtitle_dir, is_dir=True):
                    deleted_dirs += 1

        jsonl_summary = self._cleanup_transcript_jsonl(
            course_id=course_id,
            lesson_id=lesson_id,
            session_ids=context["session_ids"],
            storage_ids=context["storage_ids"],
        )
        return {
            "deleted_files": deleted_files + jsonl_summary["deleted_files"],
            "deleted_dirs": deleted_dirs,
            "deleted_jsonl_records": jsonl_summary["deleted_records"],
        }

    def _cleanup_transcript_jsonl(
        self,
        *,
        course_id: str,
        lesson_id: str,
        session_ids: set[str],
        storage_ids: set[str],
    ) -> dict[str, int]:
        deleted_records = 0
        deleted_files = 0
        transcript_root = settings.TRANSCRIPT_SAVE_DIR

        for file_path in sorted(transcript_root.glob("*.jsonl")):
            try:
                lines = file_path.read_text(encoding="utf-8").splitlines()
            except OSError:
                logger.exception("Failed to read transcript file %s", file_path)
                continue

            kept_lines: list[str] = []
            removed_in_file = 0
            for line in lines:
                raw = line.strip()
                if not raw:
                    continue
                try:
                    payload = json.loads(raw)
                except json.JSONDecodeError:
                    kept_lines.append(raw)
                    continue

                same_lesson = payload.get("course_id") == course_id and payload.get("lesson_id") == lesson_id
                same_session = str(payload.get("session_id") or "").strip() in session_ids
                same_storage = str(payload.get("storage_id") or "").strip() in storage_ids
                if same_lesson or same_session or same_storage:
                    removed_in_file += 1
                    continue
                kept_lines.append(raw)

            if removed_in_file <= 0:
                continue

            deleted_records += removed_in_file
            if kept_lines:
                try:
                    file_path.write_text("\n".join(kept_lines) + "\n", encoding="utf-8")
                except OSError:
                    logger.exception("Failed to rewrite transcript file %s", file_path)
            else:
                if _remove_path(file_path.resolve(strict=False), is_dir=False):
                    deleted_files += 1

        return {
            "deleted_records": deleted_records,
            "deleted_files": deleted_files,
        }


lesson_history_service = LessonHistoryService()


def _required_text(value: Any, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} is required")
    return text


def _optional_path(value: Any) -> Path | None:
    text = str(value or "").strip()
    return Path(text) if text else None


def _is_within_roots(path: Path, roots: tuple[Path, ...]) -> bool:
    for root in roots:
        resolved_root = root.resolve(strict=False)
        try:
            path.relative_to(resolved_root)
            return True
        except ValueError:
            continue
    return False


def _remove_path(path: Path, *, is_dir: bool) -> bool:
    if not path.exists():
        return False
    try:
        if is_dir:
            shutil.rmtree(path, ignore_errors=False)
        else:
            path.unlink()
        return True
    except OSError:
        logger.exception("Failed to delete path %s", path)
        return False


def _cleanup_empty_parents(path: Path, *, stop_roots: tuple[Path, ...]) -> None:
    current = path
    stop_set = {root.resolve(strict=False) for root in stop_roots}
    while True:
        resolved = current.resolve(strict=False)
        if resolved in stop_set:
            break
        if not current.exists() or not current.is_dir():
            break
        try:
            current.rmdir()
        except OSError:
            break
        current = current.parent
