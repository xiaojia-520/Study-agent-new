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
from src.application.rag.runtime import get_shared_rag_runtime
from src.application.video.subtitle_service import VideoSubtitleService
from src.core.knowledge.document_models import TranscriptRecord
from src.core.knowledge.query_filters import MetadataFilterClause, MetadataFilterSpec
from src.infrastructure.storage.sqlite_store import SQLiteStore, sqlite_store
from web.backend.app.domain.session import RealtimeSession
from web.backend.app.domain.video import LessonVideo
from web.backend.app.services.transcript_service import TranscriptService, transcript_service

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
        transcript_writer: TranscriptService | None = None,
        rag_runtime_factory=get_shared_rag_runtime,
        rag_indexing_enabled: bool = settings.RAG_REALTIME_INDEXING_ENABLED,
    ) -> None:
        self.store = store
        self.subtitle_service = subtitle_service or VideoSubtitleService()
        self.transcript_writer = transcript_writer or (
            transcript_service if store is sqlite_store else TranscriptService(store=store)
        )
        self.rag_runtime_factory = rag_runtime_factory
        self.rag_indexing_enabled = rag_indexing_enabled

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
        video_metadata = dict(metadata or {})
        video_metadata.setdefault("session_created_at", session.created_at or now)
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
                _encode_json(video_metadata),
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
        final_record_count = self._persist_final_transcript_records(
            video=video,
            segments=segments,
            srt_path=result.srt_path,
        )
        self._update_video(
            video.video_id,
            status="done",
            wav_path=result.wav_path,
            srt_path=result.srt_path,
            text=result.text,
            segment_count=len(segments),
            error_message=None,
            segments_json=_encode_json(segments),
            metadata={
                "raw_result_count": len(result.raw_result),
                "final_transcript_record_count": final_record_count,
            },
        )
        if final_record_count > 0:
            self._rebuild_session_rag_index(video.session_id)

    def _persist_final_transcript_records(
        self,
        *,
        video: LessonVideo,
        segments: list[dict[str, Any]],
        srt_path: str,
    ) -> int:
        if not segments:
            return 0

        delete_existing = getattr(self.transcript_writer, "delete_final_video_transcripts", None)
        if callable(delete_existing):
            delete_existing(session_id=video.session_id, video_id=video.video_id)

        next_chunk_id = self.transcript_writer.next_chunk_id(video.session_id)
        recording_started_at_ms = _metadata_int(video.metadata, "recording_started_at_ms")
        recording_started_at = _timeline_origin_seconds(video)
        records: list[dict[str, Any]] = []

        for segment_index, segment in enumerate(segments):
            text = _normalize_text(segment.get("text"))
            if not text:
                continue

            start_ms = max(0, _safe_int(segment.get("start_ms"), 0))
            end_ms = max(start_ms + 200, _safe_int(segment.get("end_ms"), start_ms + 200))
            created_at = recording_started_at + start_ms // 1000
            record = {
                "session_id": video.session_id,
                "storage_id": f"offline-asr-{video.video_id}",
                "course_id": video.course_id,
                "lesson_id": video.lesson_id,
                "chunk_id": next_chunk_id + len(records),
                "subject": video.subject or "classroom audio",
                "source_type": "video",
                "source_file": video.file_name,
                "start_ms": start_ms,
                "end_ms": end_ms,
                "text": text,
                "clean_text": text,
                "created_at": created_at,
                "metadata": {
                    "parser": "offline_funasr",
                    "transcript_role": "final",
                    "video_id": video.video_id,
                    "segment_index": segment_index,
                    "srt_path": srt_path,
                    "timeline_ms": start_ms,
                    "segment_start_ms": start_ms,
                    "segment_end_ms": end_ms,
                    "recording_started_at_ms": recording_started_at_ms,
                    "recording_started_at": recording_started_at,
                },
            }
            self.transcript_writer.append_transcript_record(record)
            records.append(record)

        return len(records)

    def _rebuild_session_rag_index(self, session_id: str) -> None:
        if not self.rag_indexing_enabled:
            return

        list_records = getattr(self.transcript_writer, "list_session_transcripts", None)
        if not callable(list_records):
            return

        try:
            payloads = list_records(None, session_id, prefer_final=True)
            records = [
                TranscriptRecord.from_dict(payload)
                for payload in payloads
                if _normalize_text(payload.get("clean_text") or payload.get("text"))
            ]
            if not records:
                return

            runtime = self.rag_runtime_factory()
            runtime.index_store.delete_by_metadata(
                MetadataFilterSpec(
                    clauses=(MetadataFilterClause("session_id", session_id),),
                )
            )
            runtime.indexing_service.index_records(
                records,
                embed_model=runtime.embed_model,
            )
            logger.info("Rebuilt final RAG index for session %s with %s records", session_id, len(records))
        except Exception as exc:
            logger.exception("Failed to rebuild final RAG index for session %s: %s", session_id, exc)

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


def _metadata_int(metadata: Mapping[str, Any], key: str) -> int | None:
    return _optional_int(metadata.get(key))


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any, default: int) -> int:
    parsed = _optional_int(value)
    return default if parsed is None else parsed


def _normalize_text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _timeline_origin_seconds(video: LessonVideo) -> int:
    recording_started_at_ms = _metadata_int(video.metadata, "recording_started_at_ms")
    if recording_started_at_ms is not None and recording_started_at_ms > 0:
        return recording_started_at_ms // 1000

    session_created_at = _metadata_int(video.metadata, "session_created_at")
    if session_created_at is not None and session_created_at > 0:
        return session_created_at

    return int(video.created_at or time.time())


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
