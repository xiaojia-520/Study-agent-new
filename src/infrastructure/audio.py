import numpy as np
import os
from typing import List, Dict, Any

def indata_to_mono_float32(indata: np.ndarray) -> np.ndarray:
    audio = np.asarray(indata, dtype=np.float32)

    if audio.ndim == 1:
        return audio

    if audio.ndim == 2:
        if audio.shape[1] == 1:
            return audio[:, 0]
        return audio.mean(axis=1)

    return audio.reshape(-1)

def ms_to_srt_time(ms: int) -> str:
    """毫秒 -> SRT 时间格式 HH:MM:SS,mmm"""
    if ms < 0:
        ms = 0
    h = ms // 3600000
    ms %= 3600000
    m = ms // 60000
    ms %= 60000
    s = ms // 1000
    ms %= 1000
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def res_to_srt(res: List[Dict[str, Any]], srt_path: str) -> str:
    """
    FunASR res -> .srt
    期望 res 类似: [{'text':..., 'start':ms, 'end':ms, ...}, ...]
    """
    lines = []
    idx = 1
    for seg in res:
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        start_ms = int(seg.get("start", 0))
        end_ms = int(seg.get("end", start_ms + 500))

        start_ts = ms_to_srt_time(start_ms)
        end_ts = ms_to_srt_time(end_ms)

        lines.append(str(idx))
        lines.append(f"{start_ts} --> {end_ts}")
        lines.append(text)
        lines.append("")  # 空行分隔
        idx += 1

    os.makedirs(os.path.dirname(srt_path) or ".", exist_ok=True)
    with open(srt_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    return srt_path

import os
import ffmpeg


def mux_srt_soft(video_path: str, srt_path: str, out_path: str = None) -> str:
    """
    把 srt 作为“软字幕轨”封装进视频：
    - 不重编码视频/音频（快）
    - 播放器可开关字幕
    """
    if out_path is None:
        base, ext = os.path.splitext(video_path)
        out_path = f"{base}_subbed{ext}"

    v_in = ffmpeg.input(video_path)
    s_in = ffmpeg.input(srt_path)

    # mp4 用 mov_text 更兼容；mkv 可用 srt（但 mov_text 在 mkv 也能工作）
    ext = os.path.splitext(out_path)[1].lower()
    sub_codec = "mov_text" if ext in [".mp4", ".m4v"] else "srt"

    (
        ffmpeg
        .output(
            v_in.video,
            v_in.audio,
            s_in,
            out_path,
            c="copy",
            c_s=sub_codec,
            metadata_s_s_0="language=chi",  # 可改 eng 等
        )
        .overwrite_output()
        .run(quiet=True)
    )
    return out_path

import os
import ffmpeg


def _escape_for_subtitles_filter(path: str) -> str:
    # ffmpeg subtitles filter 在 Windows 上对 : \ 之类敏感，需要转义
    # 经验规则：反斜杠换成 /，冒号转义
    p = os.path.abspath(path).replace("\\", "/")
    p = p.replace(":", "\\:")
    return p


def burn_srt_hard(video_path: str, srt_path: str, out_path: str = None, crf: int = 20) -> str:
    """
    把字幕烧录到画面（硬字幕）
    - 会重编码视频
    - out_path 默认 *_burn.mp4
    """
    if out_path is None:
        base, _ = os.path.splitext(video_path)
        out_path = f"{base}_burn.mp4"

    srt_escaped = _escape_for_subtitles_filter(srt_path)

    inp = ffmpeg.input(video_path)
    vid = inp.video.filter("subtitles", srt_escaped)

    (
        ffmpeg
        .output(
            vid,
            inp.audio,
            out_path,
            vcodec="libx264",
            crf=crf,
            acodec="aac",
            audio_bitrate="192k",
        )
        .overwrite_output()
        .run(quiet=True)
    )
    return out_path

