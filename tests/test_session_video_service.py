from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

from src.infrastructure.storage.sqlite_store import SQLiteStore
from web.backend.app.domain.session import RealtimeSession
from web.backend.app.services.session_video_service import SessionVideoService


@dataclass(frozen=True)
class _FakeSegment:
    start_ms: int
    end_ms: int
    text: str

    def to_dict(self):
        return {
            "start_ms": self.start_ms,
            "end_ms": self.end_ms,
            "text": self.text,
        }


class _FakeSubtitleService:
    def file_to_srt(self, input_path, *, output_dir, srt_path, **_kwargs):
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        Path(srt_path).write_text("1\n00:00:00,000 --> 00:00:01,000\nhello\n", encoding="utf-8")
        wav_path = Path(output_dir) / "audio.wav"
        wav_path.write_bytes(b"fake")
        return SimpleNamespace(
            input_path=str(input_path),
            wav_path=str(wav_path),
            srt_path=str(srt_path),
            text="hello",
            segments=(_FakeSegment(0, 1000, "hello"),),
            raw_result=({"text": "hello"},),
        )


def test_session_video_service_processes_and_persists_segments(tmp_path, monkeypatch):
    from config.settings import settings

    monkeypatch.setattr(settings, "VIDEO_SUBTITLE_DIR", tmp_path / "subtitles")
    service = SessionVideoService(
        store=SQLiteStore(tmp_path / "study.sqlite3"),
        subtitle_service=_FakeSubtitleService(),
    )
    service.init_schema()

    video_path = tmp_path / "lesson.webm"
    video_path.write_bytes(b"fake video")
    session = RealtimeSession(
        session_id="session-1",
        course_id="course-1",
        lesson_id="lesson-1",
        subject="demo",
    )
    video = service.create_video(
        video_id="video-1",
        session=session,
        file_name="lesson.webm",
        file_path=video_path,
        file_size=video_path.stat().st_size,
        media_type="video/webm",
    )

    service.process_video(video.video_id)

    processed = service.get_video(video.video_id)
    assert processed is not None
    assert processed.status == "done"
    assert processed.segment_count == 1
    assert processed.segments == ({"start_ms": 0, "end_ms": 1000, "text": "hello"},)
    assert processed.srt_path is not None
    assert Path(processed.srt_path).exists()


def test_session_video_service_lists_lesson_videos(tmp_path):
    service = SessionVideoService(
        store=SQLiteStore(tmp_path / "study.sqlite3"),
        subtitle_service=_FakeSubtitleService(),
    )
    service.init_schema()

    first_path = tmp_path / "first.webm"
    second_path = tmp_path / "second.webm"
    first_path.write_bytes(b"first")
    second_path.write_bytes(b"second")
    session = RealtimeSession(
        session_id="session-1",
        course_id="course-1",
        lesson_id="lesson-1",
        subject="demo",
    )

    first = service.create_video(
        video_id="video-1",
        session=session,
        file_name="first.webm",
        file_path=first_path,
        file_size=first_path.stat().st_size,
        media_type="video/webm",
    )
    second = service.create_video(
        video_id="video-2",
        session=session,
        file_name="second.webm",
        file_path=second_path,
        file_size=second_path.stat().st_size,
        media_type="video/webm",
    )

    videos = service.list_lesson_videos(course_id="course-1", lesson_id="lesson-1")

    assert [video.video_id for video in videos] == [second.video_id, first.video_id]
