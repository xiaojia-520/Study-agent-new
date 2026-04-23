from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping, Sequence

import ffmpeg
import numpy as np


def indata_to_mono_float32(indata: np.ndarray) -> np.ndarray:
    audio = np.asarray(indata, dtype=np.float32)

    if audio.ndim == 1:
        return audio

    if audio.ndim == 2:
        if audio.shape[1] == 1:
            return audio[:, 0]
        return audio.mean(axis=1)

    return audio.reshape(-1)


def ms_to_srt_time(ms: int | float | None) -> str:
    """Convert milliseconds to SRT timestamp format: HH:MM:SS,mmm."""
    resolved_ms = max(0, int(ms or 0))
    hours = resolved_ms // 3_600_000
    resolved_ms %= 3_600_000
    minutes = resolved_ms // 60_000
    resolved_ms %= 60_000
    seconds = resolved_ms // 1000
    resolved_ms %= 1000
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{resolved_ms:03d}"


def normalize_subtitle_segment(segment: Mapping[str, Any]) -> dict[str, Any]:
    text = str(segment.get("text") or "").strip()
    start_ms = int(segment.get("start_ms", segment.get("start", 0)) or 0)
    end_ms = int(segment.get("end_ms", segment.get("end", start_ms + 500)) or start_ms + 500)
    if end_ms <= start_ms:
        end_ms = start_ms + 500
    return {
        "start_ms": max(0, start_ms),
        "end_ms": max(0, end_ms),
        "text": text,
    }


def subtitle_segments_to_srt(segments: Sequence[Mapping[str, Any]]) -> str:
    lines: list[str] = []
    index = 1
    for raw_segment in segments:
        segment = normalize_subtitle_segment(raw_segment)
        if not segment["text"]:
            continue

        lines.append(str(index))
        lines.append(f"{ms_to_srt_time(segment['start_ms'])} --> {ms_to_srt_time(segment['end_ms'])}")
        lines.append(segment["text"])
        lines.append("")
        index += 1
    return "\n".join(lines).rstrip() + ("\n" if lines else "")


def write_srt_segments(segments: Sequence[Mapping[str, Any]], srt_path: str | Path) -> str:
    target = Path(srt_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(subtitle_segments_to_srt(segments), encoding="utf-8")
    return str(target)


def res_to_srt(res: Sequence[Mapping[str, Any]], srt_path: str | Path) -> str:
    """Backward-compatible wrapper for writing pre-segmented subtitle records."""
    return write_srt_segments(res, srt_path)


def mux_srt_soft(video_path: str | Path, srt_path: str | Path, out_path: str | Path | None = None) -> str:
    """
    Add SRT as a soft subtitle track.

    The video/audio streams are copied without re-encoding, so this is fast and
    the subtitle track can be toggled in compatible players.
    """
    source_video = str(video_path)
    source_srt = str(srt_path)
    if out_path is None:
        base, ext = os.path.splitext(source_video)
        out_path = f"{base}_subbed{ext}"
    target = str(out_path)

    video_input = ffmpeg.input(source_video)
    subtitle_input = ffmpeg.input(source_srt)

    ext = os.path.splitext(target)[1].lower()
    subtitle_codec = "mov_text" if ext in {".mp4", ".m4v"} else "srt"

    (
        ffmpeg.output(
            video_input.video,
            video_input.audio,
            subtitle_input,
            target,
            c="copy",
            c_s=subtitle_codec,
            metadata_s_s_0="language=chi",
        )
        .overwrite_output()
        .run(quiet=True)
    )
    return target


def _escape_for_subtitles_filter(path: str | Path) -> str:
    normalized = os.path.abspath(str(path)).replace("\\", "/")
    return normalized.replace(":", "\\:")


def burn_srt_hard(
    video_path: str | Path,
    srt_path: str | Path,
    out_path: str | Path | None = None,
    crf: int = 20,
) -> str:
    """
    Burn SRT subtitles into the video frames.

    This re-encodes video and is slower than mux_srt_soft, but the subtitles are
    visible in every player.
    """
    source_video = str(video_path)
    if out_path is None:
        base, _ = os.path.splitext(source_video)
        out_path = f"{base}_burn.mp4"
    target = str(out_path)

    video_input = ffmpeg.input(source_video)
    video_stream = video_input.video.filter("subtitles", _escape_for_subtitles_filter(srt_path))

    (
        ffmpeg.output(
            video_stream,
            video_input.audio,
            target,
            vcodec="libx264",
            crf=crf,
            acodec="aac",
            audio_bitrate="192k",
        )
        .overwrite_output()
        .run(quiet=True)
    )
    return target
