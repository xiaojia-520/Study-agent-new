from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Mapping, Optional


SourceType = Literal["realtime", "video"]
_VALID_SOURCE_TYPES = {"realtime", "video"}


def _require_str(value: Any, field_name: str) -> str:
    text = _optional_str(value)
    if text is None:
        raise ValueError(f"{field_name} is required")
    return text


def _optional_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _require_int(value: Any, field_name: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be an integer") from exc


def _optional_int(value: Any, field_name: str) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be an integer when provided") from exc


def _normalize_source_type(value: Any) -> SourceType:
    source_type = _require_str(value, "source_type").lower()
    if source_type not in _VALID_SOURCE_TYPES:
        supported = ", ".join(sorted(_VALID_SOURCE_TYPES))
        raise ValueError(f"source_type must be one of: {supported}")
    return source_type


@dataclass(slots=True)
class TranscriptRecord:
    session_id: str
    chunk_id: int
    subject: str
    source_type: SourceType
    text: str
    clean_text: str
    created_at: int
    source_file: Optional[str] = None
    start_ms: Optional[int] = None
    end_ms: Optional[int] = None

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "TranscriptRecord":
        session_id = _require_str(payload.get("session_id"), "session_id")
        chunk_id = _require_int(payload.get("chunk_id"), "chunk_id")
        subject = _optional_str(payload.get("subject")) or "untitled"
        source_type = _normalize_source_type(payload.get("source_type"))
        text = _optional_str(payload.get("text")) or ""
        clean_text = _optional_str(payload.get("clean_text")) or text
        if not clean_text:
            raise ValueError("text or clean_text is required")

        return cls(
            session_id=session_id,
            chunk_id=chunk_id,
            subject=subject,
            source_type=source_type,
            text=text or clean_text,
            clean_text=clean_text,
            created_at=_require_int(payload.get("created_at"), "created_at"),
            source_file=_optional_str(payload.get("source_file")),
            start_ms=_optional_int(payload.get("start_ms"), "start_ms"),
            end_ms=_optional_int(payload.get("end_ms"), "end_ms"),
        )

    @property
    def record_id(self) -> str:
        return f"{self.session_id}:{self.chunk_id}"

    @property
    def content(self) -> str:
        return self.clean_text or self.text


@dataclass(slots=True)
class TranscriptChunk:
    doc_id: str
    session_id: str
    subject: str
    source_type: SourceType
    content: str
    created_at: int
    first_chunk_id: int
    last_chunk_id: int
    record_count: int
    source_file: Optional[str] = None
    start_ms: Optional[int] = None
    end_ms: Optional[int] = None
    metadata: dict[str, object] = field(default_factory=dict)

    def to_metadata(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "doc_id": self.doc_id,
            "session_id": self.session_id,
            "subject": self.subject,
            "source_type": self.source_type,
            "created_at": self.created_at,
            "first_chunk_id": self.first_chunk_id,
            "last_chunk_id": self.last_chunk_id,
            "record_count": self.record_count,
        }
        if self.source_file is not None:
            payload["source_file"] = self.source_file
        if self.start_ms is not None:
            payload["start_ms"] = self.start_ms
        if self.end_ms is not None:
            payload["end_ms"] = self.end_ms
        payload.update(self.metadata)
        return payload


@dataclass(slots=True)
class SearchResult:
    doc_id: str
    content: str
    score: Optional[float] = None
    session_id: Optional[str] = None
    subject: Optional[str] = None
    source_type: Optional[str] = None
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class KnowledgeAnswer:
    query: str
    answer: Optional[str]
    results: list[SearchResult] = field(default_factory=list)
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class ChunkingOptions:
    max_chars: int = 500
    overlap_records: int = 1
    min_chunk_chars: int = 80
    split_long_record: bool = True
    separator: str = "\n"

    def __post_init__(self) -> None:
        if self.max_chars <= 0:
            raise ValueError("max_chars must be greater than 0")
        if self.overlap_records < 0:
            raise ValueError("overlap_records must be >= 0")
        if self.min_chunk_chars < 0:
            raise ValueError("min_chunk_chars must be >= 0")
        if self.separator is None:
            raise ValueError("separator must not be None")
