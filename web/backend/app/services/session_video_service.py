from __future__ import annotations

import json
import logging
import re
import time
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Any, Mapping

from config.settings import settings
from src.application.video.subtitle_service import VideoSubtitleService
from src.infrastructure.storage.sqlite_store import SQLiteStore, sqlite_store
from web.backend.app.domain.session import RealtimeSession
from web.backend.app.domain.video import LessonVideo

logger = logging.getLogger(__name__)

_SUPPORTED_EXTENSIONS = {
    ".aac",
    ".avi",
    ".flac",
    ".m4a",
    ".m4v",
    ".mkv",
    ".mov",
    ".mp3",
    ".mp4",
    ".ogg",
    ".wav",
    ".webm",
}


class SessionVideoService:
    def __init__(
        self,
        *,
        store: SQLiteStore = sqlite_store,
        subtitle_service: VideoSubtitleService | None = None,
    ) -> None:
        self.store = store
        self.subtitle_service = subtitle_service or VideoSubtitleService()

    def init_schema(self) -> None:
        self.store.init_schema()
        self.store.execute(
            """
            CREATE TABLE IF NOT EXISTS lesson_videos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                video_id TEXT NOT NULL UNIQUE,
                session_id TEXT NOT NULL,
                course_id TEXT,
                lesson_id TEXT,
                subject TEXT,
                file_name TEXT NOT NULL,
                file_path TEXT NOT NULL,
                file_size INTEGER NOT NULL,
                media_type TEXT NOT NULL,
                status TEXT NOT NULL,
                wav_path TEXT,
                srt_path TEXT,
                text TEXT,
                segment_count INTEGER NOT NULL DEFAULT 0,
                error_message TEXT,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                metadata_json TEXT,
                segments_json TEXT
            )
            """
        )
        self.store.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_lesson_videos_session_created
            ON lesson_videos(session_id, created_at, id)
            """
        )
        self.store.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_lesson_videos_lesson_created
            ON lesson_videos(course_id, lesson_id, created_at, id)
            """
        )

    def allocate_upload_path(self, *, session_id: str, file_name: str) -> tuple[str, str, Path]:
        video_id = uuid.uuid4().hex
        safe_name = _sanitize_filename(file_name)
        target_dir = settings.VIDEO_SAVE_DIR / session_id
        target_dir.mkdir(parents=True, exist_ok=True)
        return video_id, safe_name, target_dir / f"{video_id}_{safe_name}"

    def create_video(
        self,
        *,
        video_id: str,
        session: RealtimeSession,
        file_name: str,
        file_path: Path,
        file_size: int,
        media_type: str,
        metadata: dict[str, Any] | None = None,
    ) -> LessonVideo:
        if file_size <= 0:
            raise ValueError("uploaded video is empty")
        if file_size > settings.VIDEO_MAX_UPLOAD_BYTES:
            raise ValueError("uploaded video exceeds size limit")

        now = int(time.time())
        self.store.execute(
            """
            INSERT INTO lesson_videos (
                video_id, session_id, course_id, lesson_id, subject,
                file_name, file_path, file_size, media_type, status,
                created_at, updated_at, metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                video_id,
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
                _encode_json(metadata),
            ),
        )
        video = self.get_video(video_id)
        if video is None:
            raise RuntimeError("failed to create lesson video")
        return video

    def list_session_videos(self, session_id: str) -> list[LessonVideo]:
        rows = self.store.query_all(
            """
            SELECT *
            FROM lesson_videos
            WHERE session_id = ?
            ORDER BY created_at DESC, id DESC
            """,
            (session_id,),
        )
        return [_row_to_video(row) for row in rows]

    def list_lesson_videos(self, *, course_id: str, lesson_id: str) -> list[LessonVideo]:
        rows = self.store.query_all(
            """
            SELECT *
            FROM lesson_videos
            WHERE course_id = ? AND lesson_id = ?
            ORDER BY created_at DESC, id DESC
            """,
            (course_id, lesson_id),
        )
        return [_row_to_video(row) for row in rows]

    def get_video(self, video_id: str) -> LessonVideo | None:
        rows = self.store.query_all(
            """
            SELECT *
            FROM lesson_videos
            WHERE video_id = ?
            LIMIT 1
            """,
            (video_id,),
        )
        return _row_to_video(rows[0]) if rows else None

    def process_video(self, video_id: str) -> None:
        video = self.get_video(video_id)
        if video is None:
            logger.warning("Skip video subtitle processing because video %s was not found", video_id)
            return

        try:
            self._process_video(video)
        except Exception as exc:
            logger.exception("Video subtitle processing failed for %s: %s", video_id, exc)
            self._update_video(
                video_id,
                status="failed",
                error_message=str(exc),
            )

    def to_dict(self, video: LessonVideo) -> dict[str, Any]:
        payload = asdict(video)
        payload["metadata"] = dict(video.metadata)
        payload["segments"] = list(video.segments)
        return payload

    def _process_video(self, video: LessonVideo) -> None:
        file_path = Path(video.file_path)
        if not file_path.exists():
            raise FileNotFoundError(file_path)

        self._update_video(video.video_id, status="processing", error_message=None)
        output_dir = settings.VIDEO_SUBTITLE_DIR / video.video_id
        output_dir.mkdir(parents=True, exist_ok=True)
        srt_path = output_dir / f"{Path(video.file_name).stem}.srt"

        result = self.subtitle_service.file_to_srt(
            file_path,
            output_dir=output_dir,
            srt_path=srt_path,
        )
        segments = [segment.to_dict() for segment in result.segments]
        self._update_video(
            video.video_id,
            status="done",
            wav_path=result.wav_path,
            srt_path=result.srt_path,
            text=result.text,
            segment_count=len(segments),
            error_message=None,
            segments_json=_encode_json(segments),
            metadata={"raw_result_count": len(result.raw_result)},
        )

    def _update_video(self, video_id: str, **changes: Any) -> None:
        metadata = changes.pop("metadata", None)
        if metadata is not None:
            existing = self.get_video(video_id)
            merged = dict(existing.metadata if existing is not None else {})
            merged.update(metadata)
            changes["metadata_json"] = _encode_json(merged)

        changes["updated_at"] = int(time.time())
        assignments = ", ".join(f"{key} = ?" for key in changes)
        values = list(changes.values())
        values.append(video_id)
        self.store.execute(
            f"""
            UPDATE lesson_videos
            SET {assignments}
            WHERE video_id = ?
            """,
            values,
        )


session_video_service = SessionVideoService()


def validate_video_file_name(file_name: str) -> None:
    extension = Path(file_name or "").suffix.lower()
    if extension not in _SUPPORTED_EXTENSIONS:
        supported = ", ".join(sorted(_SUPPORTED_EXTENSIONS))
        raise ValueError(f"unsupported video file type; supported extensions: {supported}")


def _row_to_video(row: Mapping[str, Any]) -> LessonVideo:
    return LessonVideo(
        id=int(row["id"]),
        video_id=str(row["video_id"]),
        session_id=str(row["session_id"]),
        course_id=_optional_str(row.get("course_id")),
        lesson_id=_optional_str(row.get("lesson_id")),
        subject=_optional_str(row.get("subject")),
        file_name=str(row["file_name"]),
        file_path=str(row["file_path"]),
        file_size=int(row["file_size"]),
        media_type=str(row["media_type"]),
        status=str(row["status"]),
        wav_path=_optional_str(row.get("wav_path")),
        srt_path=_optional_str(row.get("srt_path")),
        text=_optional_str(row.get("text")),
        segment_count=int(row.get("segment_count") or 0),
        error_message=_optional_str(row.get("error_message")),
        created_at=int(row["created_at"]),
        updated_at=int(row["updated_at"]),
        metadata=_decode_dict(row.get("metadata_json")),
        segments=tuple(_decode_segments(row.get("segments_json"))),
    )


def _sanitize_filename(file_name: str) -> str:
    name = Path(file_name or "recording.webm").name.strip() or "recording.webm"
    cleaned = re.sub(r"[^\w.\-\u4e00-\u9fff]+", "_", name)
    cleaned = re.sub(r"_+", "_", cleaned).strip("._")
    return cleaned or "recording.webm"


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _encode_json(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, default=str)


def _decode_dict(value: Any) -> dict[str, Any]:
    if not value:
        return {}
    try:
        payload = json.loads(str(value))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _decode_segments(value: Any) -> list[dict[str, Any]]:
    if not value:
        return []
    try:
        payload = json.loads(str(value))
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, list):
        return []
    return [dict(item) for item in payload if isinstance(item, Mapping)]
