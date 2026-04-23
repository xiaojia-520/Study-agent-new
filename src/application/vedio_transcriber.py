from __future__ import annotations

from pathlib import Path

from src.application.video_subtitle_service import VideoSubtitleResult, VideoSubtitleService


class VideoTranscriber(VideoSubtitleService):
    """Backward-compatible application facade for video-to-subtitle work."""

    def start(self, path: str | Path, *, output_dir: str | Path = "./tmp_wav") -> VideoSubtitleResult:
        return self.file_to_srt(path, output_dir=output_dir)


class VedioTranscriber(VideoTranscriber):
    """Compatibility alias for the original misspelled class name."""


__all__ = ["VideoSubtitleResult", "VideoSubtitleService", "VideoTranscriber", "VedioTranscriber"]
