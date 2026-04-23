from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import ffmpeg

from src.infrastructure.audio import write_srt_segments
from src.infrastructure.model_hub import model_hub


_HARD_BREAK_CHARS = set("。！？!?；;")
_SOFT_BREAK_CHARS = set("，,、：:")
_SPACE_RE = re.compile(r"\s+")


@dataclass(frozen=True, slots=True)
class SubtitleSegment:
    start_ms: int
    end_ms: int
    text: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class VideoSubtitleResult:
    input_path: str
    wav_path: str
    srt_path: str
    text: str
    segments: tuple[SubtitleSegment, ...]
    raw_result: tuple[Mapping[str, Any], ...]


@dataclass(frozen=True, slots=True)
class _TimestampUnit:
    start_ms: int
    end_ms: int
    text: str


class VideoSubtitleService:
    """Convert an audio/video file into SRT subtitles using FunASR timestamps."""

    def __init__(self, *, funasr_model: Any | None = None) -> None:
        self._funasr_model = funasr_model

    @property
    def funasr_model(self) -> Any:
        if self._funasr_model is None:
            self._funasr_model = model_hub.load_funasr_model()
        return self._funasr_model

    def prepare_funasr_wav(
        self,
        input_path: str | Path,
        *,
        output_dir: str | Path = "./tmp_wav",
        sample_rate: int = 16000,
    ) -> Path:
        source = Path(input_path)
        if not source.exists():
            raise FileNotFoundError(source)

        target_dir = Path(output_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        wav_path = target_dir / f"{source.stem}_16k_mono.wav"

        probe = ffmpeg.probe(str(source))
        streams = probe.get("streams", [])
        has_video = any(stream.get("codec_type") == "video" for stream in streams)
        has_audio = any(stream.get("codec_type") == "audio" for stream in streams)
        if not has_audio:
            raise ValueError(f"file has no audio stream: {source}")

        output_kwargs: dict[str, Any] = {
            "format": "wav",
            "acodec": "pcm_s16le",
            "ac": 1,
            "ar": sample_rate,
        }
        if has_video:
            output_kwargs["map"] = "0:a:0"

        (
            ffmpeg.input(str(source))
            .output(str(wav_path), **output_kwargs)
            .overwrite_output()
            .run(quiet=True)
        )
        return wav_path

    def transcribe_audio(
        self,
        audio_path: str | Path,
        *,
        batch_size_s: int = 300,
        max_single_segment_time: int = 30_000,
    ) -> list[Mapping[str, Any]]:
        result = self.funasr_model.generate(
            input=str(audio_path),
            batch_size_s=batch_size_s,
            vad_kwargs={"max_single_segment_time": max_single_segment_time},
        )
        return [dict(item) for item in result or [] if isinstance(item, Mapping)]

    def transcribe_to_segments(
        self,
        audio_path: str | Path,
        *,
        max_chars: int = 22,
        max_duration_ms: int = 5_000,
        min_chars_for_soft_break: int = 8,
    ) -> tuple[SubtitleSegment, ...]:
        raw_result = self.transcribe_audio(audio_path)
        return funasr_result_to_segments(
            raw_result,
            max_chars=max_chars,
            max_duration_ms=max_duration_ms,
            min_chars_for_soft_break=min_chars_for_soft_break,
        )

    def file_to_srt(
        self,
        input_path: str | Path,
        *,
        output_dir: str | Path = "./tmp_wav",
        srt_path: str | Path | None = None,
        max_chars: int = 22,
        max_duration_ms: int = 5_000,
        min_chars_for_soft_break: int = 8,
    ) -> VideoSubtitleResult:
        source = Path(input_path)
        wav_path = self.prepare_funasr_wav(source, output_dir=output_dir)
        raw_result = self.transcribe_audio(wav_path)
        segments = funasr_result_to_segments(
            raw_result,
            max_chars=max_chars,
            max_duration_ms=max_duration_ms,
            min_chars_for_soft_break=min_chars_for_soft_break,
        )
        if srt_path is None:
            srt_path = Path(output_dir) / f"{source.stem}.srt"
        write_srt_segments([segment.to_dict() for segment in segments], srt_path)
        return VideoSubtitleResult(
            input_path=str(source),
            wav_path=str(wav_path),
            srt_path=str(srt_path),
            text="".join(str(item.get("text") or "") for item in raw_result).strip(),
            segments=segments,
            raw_result=tuple(raw_result),
        )


def funasr_result_to_segments(
    result: Mapping[str, Any] | Sequence[Mapping[str, Any]],
    *,
    max_chars: int = 22,
    max_duration_ms: int = 5_000,
    min_chars_for_soft_break: int = 8,
) -> tuple[SubtitleSegment, ...]:
    items: Sequence[Mapping[str, Any]]
    if isinstance(result, Mapping):
        items = (result,)
    else:
        items = result

    segments: list[SubtitleSegment] = []
    for item in items:
        direct_segments = _segments_from_sentence_like_fields(item)
        if direct_segments:
            segments.extend(direct_segments)
            continue

        units = _timestamp_units_from_item(item)
        if not units:
            continue
        segments.extend(
            _merge_timestamp_units(
                units,
                max_chars=max_chars,
                max_duration_ms=max_duration_ms,
                min_chars_for_soft_break=min_chars_for_soft_break,
            )
        )

    return tuple(_renormalize_segments(segments))


def _segments_from_sentence_like_fields(item: Mapping[str, Any]) -> list[SubtitleSegment]:
    for key in ("sentence_info", "stamp_sents"):
        value = item.get(key)
        if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
            continue

        segments: list[SubtitleSegment] = []
        for entry in value:
            if not isinstance(entry, Mapping):
                continue
            text = _normalize_subtitle_text(str(entry.get("text") or ""))
            if not text:
                continue
            start_ms = _safe_int(entry.get("start", entry.get("start_ms")), 0)
            end_ms = _safe_int(entry.get("end", entry.get("end_ms")), start_ms + 500)
            segments.append(SubtitleSegment(start_ms=max(0, start_ms), end_ms=max(end_ms, start_ms + 200), text=text))
        if segments:
            return segments
    return []


def _timestamp_units_from_item(item: Mapping[str, Any]) -> list[_TimestampUnit]:
    timestamp = item.get("timestamp")
    if not isinstance(timestamp, Sequence) or isinstance(timestamp, (str, bytes)):
        return []

    pairs: list[tuple[int, int]] = []
    for value in timestamp:
        if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or len(value) < 2:
            continue
        start_ms = _safe_int(value[0], 0)
        end_ms = _safe_int(value[1], start_ms + 200)
        pairs.append((max(0, start_ms), max(end_ms, start_ms + 50)))

    if not pairs:
        return []

    tokens = _tokens_for_timestamp_count(str(item.get("text") or ""), len(pairs))
    units: list[_TimestampUnit] = []
    for token, (start_ms, end_ms) in zip(tokens, pairs):
        if token:
            units.append(_TimestampUnit(start_ms=start_ms, end_ms=end_ms, text=token))
    return units


def _tokens_for_timestamp_count(text: str, count: int) -> list[str]:
    normalized = text.strip()
    if count <= 0 or not normalized:
        return []

    split_tokens = [token for token in normalized.split() if token]
    if len(split_tokens) == count:
        return split_tokens

    compact = _SPACE_RE.sub("", normalized)
    if len(compact) == count:
        return list(compact)

    if len(split_tokens) > 1 and len(split_tokens) < count:
        # Preserve word-level English tokens when possible; the extra timestamps
        # are usually punctuation or tokenizer details and can be ignored.
        return split_tokens

    if len(compact) <= count:
        return list(compact)

    return _split_text_evenly(compact, count)


def _split_text_evenly(text: str, count: int) -> list[str]:
    if count <= 0:
        return []
    length = len(text)
    tokens: list[str] = []
    for index in range(count):
        start = round(index * length / count)
        end = round((index + 1) * length / count)
        token = text[start:end]
        if token:
            tokens.append(token)
    return tokens


def _merge_timestamp_units(
    units: Sequence[_TimestampUnit],
    *,
    max_chars: int,
    max_duration_ms: int,
    min_chars_for_soft_break: int,
) -> list[SubtitleSegment]:
    segments: list[SubtitleSegment] = []
    current: list[_TimestampUnit] = []

    def flush() -> None:
        if not current:
            return
        text = _normalize_subtitle_text(_join_tokens([unit.text for unit in current]))
        if text:
            start_ms = current[0].start_ms
            end_ms = max(current[-1].end_ms, start_ms + 200)
            segments.append(SubtitleSegment(start_ms=start_ms, end_ms=end_ms, text=text))
        current.clear()

    for unit in units:
        current.append(unit)
        text = _normalize_subtitle_text(_join_tokens([item.text for item in current]))
        duration_ms = current[-1].end_ms - current[0].start_ms
        last_char = unit.text[-1] if unit.text else ""

        hard_break = last_char in _HARD_BREAK_CHARS
        soft_break = last_char in _SOFT_BREAK_CHARS and len(text) >= min_chars_for_soft_break
        too_long = len(text) >= max_chars or duration_ms >= max_duration_ms
        if hard_break or soft_break or too_long:
            flush()

    flush()
    return segments


def _renormalize_segments(segments: Sequence[SubtitleSegment]) -> list[SubtitleSegment]:
    normalized: list[SubtitleSegment] = []
    previous_end = 0
    for segment in segments:
        text = _normalize_subtitle_text(segment.text)
        if not text:
            continue
        start_ms = max(0, int(segment.start_ms))
        end_ms = max(int(segment.end_ms), start_ms + 200)
        if normalized and start_ms < previous_end:
            start_ms = previous_end
            end_ms = max(end_ms, start_ms + 200)
        normalized.append(SubtitleSegment(start_ms=start_ms, end_ms=end_ms, text=text))
        previous_end = end_ms
    return normalized


def _normalize_subtitle_text(text: str) -> str:
    return _SPACE_RE.sub(" ", text).strip()


def _join_tokens(tokens: Sequence[str]) -> str:
    output = ""
    previous = ""
    for token in tokens:
        if not token:
            continue
        if output and _needs_space(previous, token):
            output += " "
        output += token
        previous = token
    return output


def _needs_space(left: str, right: str) -> bool:
    if not left or not right:
        return False
    return _is_ascii_word_char(left[-1]) and _is_ascii_word_char(right[0])


def _is_ascii_word_char(value: str) -> bool:
    return value.isascii() and (value.isalnum() or value in {"'", "_"})


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
