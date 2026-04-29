from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from src.core.knowledge.document_models import ChunkingOptions, TranscriptChunk, TranscriptRecord

_SENTENCE_BOUNDARY_RE = re.compile(r"(?<=[。！？!?；;])")


@dataclass(slots=True)
class _RecordSegment:
    record: TranscriptRecord
    text: str
    segment_index: int
    segment_count: int


def load_transcript_records(file_path: Path) -> list[TranscriptRecord]:
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(path)
    if not path.is_file():
        raise ValueError(f"expected a file path, got directory: {path}")

    records: list[TranscriptRecord] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid json at {path}:{line_number}") from exc
            if not isinstance(payload, dict):
                raise ValueError(f"record at {path}:{line_number} must be a JSON object")
            try:
                records.append(TranscriptRecord.from_dict(payload))
            except ValueError as exc:
                raise ValueError(f"invalid transcript record at {path}:{line_number}: {exc}") from exc
    return _sort_records(records)


def load_records_from_dir(root_dir: Path) -> list[TranscriptRecord]:
    path = Path(root_dir)
    if not path.exists():
        raise FileNotFoundError(path)
    if not path.is_dir():
        raise ValueError(f"expected a directory path, got file: {path}")

    records: list[TranscriptRecord] = []
    for file_path in sorted(path.rglob("*.jsonl")):
        records.extend(load_transcript_records(file_path))
    return _sort_records(records)


def group_records_by_session(records: Sequence[TranscriptRecord]) -> dict[str, list[TranscriptRecord]]:
    grouped: dict[str, list[TranscriptRecord]] = defaultdict(list)
    for record in _sort_records(records):
        grouped[record.session_id].append(record)
    return dict(grouped)


def build_chunks(
    records: Sequence[TranscriptRecord],
    options: ChunkingOptions | None = None,
) -> list[TranscriptChunk]:
    chunks: list[TranscriptChunk] = []
    for session_records in group_records_by_session(records).values():
        chunks.extend(build_chunks_for_session(session_records, options))
    return chunks


def build_chunks_for_session(
    records: Sequence[TranscriptRecord],
    options: ChunkingOptions | None = None,
) -> list[TranscriptChunk]:
    if not records:
        return []

    opts = options or ChunkingOptions()
    ordered_records = _sort_records(records)
    session_ids = {record.session_id for record in ordered_records}
    if len(session_ids) != 1:
        raise ValueError("build_chunks_for_session expects records from exactly one session")

    segments: list[_RecordSegment] = []
    for record in ordered_records:
        segments.extend(_split_record(record, opts))

    if not segments:
        return []

    chunk_segments: list[list[_RecordSegment]] = []
    current: list[_RecordSegment] = []

    for segment in segments:
        projected = _projected_length(current, segment.text, opts.separator)
        if current and projected > opts.max_chars:
            chunk_segments.append(list(current))
            current = _tail_overlap_segments(current, opts.overlap_records)
            current = _trim_prefix_records_until_fit(
                current=current,
                next_text=segment.text,
                separator=opts.separator,
                max_chars=opts.max_chars,
            )
        current.append(segment)

    if current:
        chunk_segments.append(list(current))

    return [
        _build_chunk_from_segments(group, chunk_index=index, separator=opts.separator)
        for index, group in enumerate(chunk_segments)
    ]


def _sort_records(records: Iterable[TranscriptRecord]) -> list[TranscriptRecord]:
    return sorted(
        records,
        key=lambda record: (record.session_id, record.created_at, record.chunk_id, record.record_id),
    )


def _split_record(record: TranscriptRecord, options: ChunkingOptions) -> list[_RecordSegment]:
    text = record.content.strip()
    if not text:
        return []

    parts = [text]
    if options.split_long_record and len(text) > options.max_chars:
        parts = _split_text(text, max_chars=options.max_chars, min_chunk_chars=options.min_chunk_chars)

    return [
        _RecordSegment(
            record=record,
            text=part,
            segment_index=index,
            segment_count=len(parts),
        )
        for index, part in enumerate(parts)
        if part
    ]


def _split_text(text: str, *, max_chars: int, min_chunk_chars: int) -> list[str]:
    normalized = text.strip()
    if not normalized:
        return []
    if len(normalized) <= max_chars:
        return [normalized]

    sentence_units: list[str] = []
    for block in normalized.splitlines():
        block = block.strip()
        if not block:
            continue
        sentence_units.extend(part.strip() for part in _SENTENCE_BOUNDARY_RE.split(block) if part.strip())

    if not sentence_units:
        sentence_units = [normalized]

    bounded_units: list[str] = []
    for unit in sentence_units:
        if len(unit) <= max_chars:
            bounded_units.append(unit)
        else:
            bounded_units.extend(_hard_split(unit, max_chars))

    merged = _merge_units(bounded_units, max_chars=max_chars)
    if len(merged) >= 2 and min_chunk_chars > 0 and len(merged[-1]) < min_chunk_chars:
        if len(merged[-2]) + len(merged[-1]) <= max_chars:
            merged[-2] = merged[-2] + merged[-1]
            merged.pop()
    return merged


def _hard_split(text: str, max_chars: int) -> list[str]:
    return [text[index:index + max_chars] for index in range(0, len(text), max_chars)]


def _merge_units(units: Sequence[str], *, max_chars: int) -> list[str]:
    merged: list[str] = []
    current = ""
    for unit in units:
        if not current:
            current = unit
            continue
        if len(current) + len(unit) <= max_chars:
            current += unit
            continue
        merged.append(current)
        current = unit
    if current:
        merged.append(current)
    return merged


def _tail_overlap_segments(segments: Sequence[_RecordSegment], overlap_records: int) -> list[_RecordSegment]:
    if overlap_records <= 0:
        return []

    selected: list[_RecordSegment] = []
    seen_record_ids: list[str] = []
    seen_lookup: set[str] = set()

    for segment in reversed(segments):
        selected.append(segment)
        record_id = segment.record.record_id
        if record_id not in seen_lookup:
            seen_lookup.add(record_id)
            seen_record_ids.append(record_id)
            if len(seen_record_ids) >= overlap_records:
                break

    selected.reverse()
    return selected


def _trim_prefix_records_until_fit(
    *,
    current: Sequence[_RecordSegment],
    next_text: str,
    separator: str,
    max_chars: int,
) -> list[_RecordSegment]:
    trimmed = list(current)
    while trimmed and _projected_length(trimmed, next_text, separator) > max_chars:
        trimmed = _drop_first_record(trimmed)
    return trimmed


def _drop_first_record(segments: Sequence[_RecordSegment]) -> list[_RecordSegment]:
    if not segments:
        return []
    first_record_id = segments[0].record.record_id
    index = 0
    while index < len(segments) and segments[index].record.record_id == first_record_id:
        index += 1
    return list(segments[index:])


def _projected_length(current: Sequence[_RecordSegment], next_text: str, separator: str) -> int:
    current_length = _joined_length((segment.text for segment in current), separator)
    if not current:
        return len(next_text)
    return current_length + len(separator) + len(next_text)


def _joined_length(parts: Iterable[str], separator: str) -> int:
    values = list(parts)
    if not values:
        return 0
    return sum(len(value) for value in values) + (len(values) - 1) * len(separator)


def _build_chunk_from_segments(
    segments: Sequence[_RecordSegment],
    *,
    chunk_index: int,
    separator: str,
) -> TranscriptChunk:
    unique_records: list[TranscriptRecord] = []
    seen_record_ids: set[str] = set()
    for segment in segments:
        record = segment.record
        if record.record_id in seen_record_ids:
            continue
        seen_record_ids.add(record.record_id)
        unique_records.append(record)

    if not unique_records:
        raise ValueError("cannot build a chunk from empty segments")

    first_record = unique_records[0]
    last_record = unique_records[-1]
    storage_id = _single_shared_value(record.storage_id for record in unique_records)
    course_id = _single_shared_value(record.course_id for record in unique_records)
    lesson_id = _single_shared_value(record.lesson_id for record in unique_records)
    source_file = _single_shared_value(record.source_file for record in unique_records)
    shared_metadata = _shared_metadata(record.metadata for record in unique_records)
    first_page_no = _first_non_none(_metadata_int(record.metadata, "page_no") for record in unique_records)
    last_page_no = _last_non_none(_metadata_int(record.metadata, "page_no") for record in unique_records)

    return TranscriptChunk(
        doc_id=f"{first_record.session_id}:{first_record.chunk_id}-{last_record.chunk_id}:{chunk_index}",
        session_id=first_record.session_id,
        subject=first_record.subject,
        source_type=first_record.source_type,
        content=separator.join(segment.text for segment in segments),
        created_at=first_record.created_at,
        first_chunk_id=first_record.chunk_id,
        last_chunk_id=last_record.chunk_id,
        record_count=len(unique_records),
        storage_id=storage_id,
        course_id=course_id,
        lesson_id=lesson_id,
        source_file=source_file,
        start_ms=_first_non_none(record.start_ms for record in unique_records),
        end_ms=_last_non_none(record.end_ms for record in unique_records),
        metadata={
            "record_ids": [record.record_id for record in unique_records],
            "segment_count": len(segments),
            **shared_metadata,
            **({"first_page_no": first_page_no} if first_page_no is not None else {}),
            **({"last_page_no": last_page_no} if last_page_no is not None else {}),
        },
    )


def _single_shared_value(values: Iterable[str | None]) -> str | None:
    materialized = list(values)
    if not materialized:
        return None
    first = materialized[0]
    if all(value == first for value in materialized):
        return first
    return None


def _shared_metadata(values: Iterable[dict[str, object]]) -> dict[str, object]:
    materialized = list(values)
    if not materialized:
        return {}
    keys = set(materialized[0].keys())
    for item in materialized[1:]:
        keys &= set(item.keys())
    return {
        key: materialized[0][key]
        for key in keys
        if all(item.get(key) == materialized[0][key] for item in materialized)
    }


def _metadata_int(metadata: dict[str, object], key: str) -> int | None:
    value = metadata.get(key)
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _first_non_none(values: Iterable[int | None]) -> int | None:
    for value in values:
        if value is not None:
            return value
    return None


def _last_non_none(values: Iterable[int | None]) -> int | None:
    materialized = list(values)
    for value in reversed(materialized):
        if value is not None:
            return value
    return None
