from __future__ import annotations

import hashlib
import json
import logging
import re
import time
import uuid
from dataclasses import dataclass
from typing import Any, Mapping, Protocol, Sequence

from config.prompts import build_lesson_note_markdown_prompt
from src.domain.lesson_note import LessonNote, LessonNoteStatus

logger = logging.getLogger(__name__)


class LessonNoteRepository(Protocol):
    def create_note(
        self,
        *,
        note_id: str,
        course_id: str,
        lesson_id: str,
        status: LessonNoteStatus,
        session_id: str | None = None,
        title: str | None = None,
        summary: str | None = None,
        markdown: str | None = None,
        note: Mapping[str, Any] | None = None,
        source_record_count: int = 0,
        source_hash: str | None = None,
        model_name: str | None = None,
        error_message: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> LessonNote: ...

    def update_note(self, note_id: str, **changes: Any) -> None: ...

    def get_note(self, note_id: str) -> LessonNote | None: ...

    def get_latest_note(self, *, course_id: str, lesson_id: str) -> LessonNote | None: ...


class LessonTranscriptLoader(Protocol):
    def __call__(
        self,
        *,
        course_id: str,
        lesson_id: str,
        prefer_final: bool = True,
    ) -> Sequence[Mapping[str, Any]]: ...


@dataclass(frozen=True, slots=True)
class LessonNoteGenerationPlan:
    note: LessonNote
    should_generate: bool


class LessonNoteService:
    def __init__(
        self,
        *,
        repository: LessonNoteRepository,
        transcript_loader: LessonTranscriptLoader,
        runtime_factory,
        runtime_closer=None,
        chunk_char_limit: int = 6000,
        max_items_default: int = 12,
    ) -> None:
        self.repository = repository
        self.transcript_loader = transcript_loader
        self.runtime_factory = runtime_factory
        self.runtime_closer = runtime_closer
        self.chunk_char_limit = max(1, int(chunk_char_limit))
        self.max_items_default = max(1, int(max_items_default))
        self._runtime = None

    def request_generation(
        self,
        *,
        course_id: str,
        lesson_id: str,
        session_id: str | None = None,
        focus: str | None = None,
        max_items: int | None = None,
        force: bool = False,
    ) -> LessonNoteGenerationPlan:
        course_id = _required_text(course_id, "course_id")
        lesson_id = _required_text(lesson_id, "lesson_id")
        transcript_items = self._load_lesson_transcripts(course_id=course_id, lesson_id=lesson_id)
        speech_items = self._filter_speech_transcripts(transcript_items)
        source_hash = self._source_hash(speech_items)

        latest = self.repository.get_latest_note(course_id=course_id, lesson_id=lesson_id)
        if latest is not None and latest.source_hash == source_hash and not force:
            if latest.status in {LessonNoteStatus.DONE, LessonNoteStatus.GENERATING}:
                return LessonNoteGenerationPlan(note=latest, should_generate=False)

        resolved_max_items = max(1, int(max_items or self.max_items_default))
        note = self.repository.create_note(
            note_id=uuid.uuid4().hex,
            course_id=course_id,
            lesson_id=lesson_id,
            session_id=_optional_text(session_id),
            status=LessonNoteStatus.GENERATING,
            source_record_count=len(speech_items),
            source_hash=source_hash,
            metadata={
                "focus": _optional_text(focus),
                "max_items": resolved_max_items,
                "requested_at": int(time.time()),
            },
        )
        return LessonNoteGenerationPlan(note=note, should_generate=True)

    def generate_note(
        self,
        *,
        course_id: str,
        lesson_id: str,
        session_id: str | None = None,
        focus: str | None = None,
        max_items: int | None = None,
        force: bool = False,
    ) -> LessonNote:
        plan = self.request_generation(
            course_id=course_id,
            lesson_id=lesson_id,
            session_id=session_id,
            focus=focus,
            max_items=max_items,
            force=force,
        )
        if not plan.should_generate:
            return plan.note
        return self.generate_pending_note(plan.note.note_id, focus=focus, max_items=max_items)

    def generate_pending_note(
        self,
        note_id: str,
        *,
        focus: str | None = None,
        max_items: int | None = None,
        raise_errors: bool = True,
    ) -> LessonNote:
        try:
            return self._generate_pending_note(note_id, focus=focus, max_items=max_items)
        except Exception as exc:
            logger.exception("Lesson note generation failed for %s: %s", note_id, exc)
            existing = self.repository.get_note(note_id)
            if existing is not None:
                self.repository.update_note(
                    note_id,
                    status=LessonNoteStatus.FAILED,
                    error_message=str(exc),
                    metadata={"failed_at": int(time.time())},
                )
                failed = self.repository.get_note(note_id)
                if not raise_errors and failed is not None:
                    return failed
            if raise_errors:
                raise
            raise

    def get_note(self, note_id: str) -> LessonNote | None:
        return self.repository.get_note(note_id)

    def get_latest_note(self, *, course_id: str, lesson_id: str) -> LessonNote | None:
        return self.repository.get_latest_note(
            course_id=_required_text(course_id, "course_id"),
            lesson_id=_required_text(lesson_id, "lesson_id"),
        )

    def close(self) -> None:
        if callable(self.runtime_closer):
            self.runtime_closer()
        elif self._runtime is not None:
            index_store = getattr(self._runtime, "index_store", None)
            close = getattr(index_store, "close", None)
            if callable(close):
                close()
        self._runtime = None

    def _generate_pending_note(
        self,
        note_id: str,
        *,
        focus: str | None = None,
        max_items: int | None = None,
    ) -> LessonNote:
        note = self.repository.get_note(note_id)
        if note is None:
            raise KeyError(note_id)

        transcript_items = self._load_lesson_transcripts(course_id=note.course_id, lesson_id=note.lesson_id)
        speech_items = self._filter_speech_transcripts(transcript_items)
        source_hash = self._source_hash(speech_items)
        resolved_max_items = max(
            1,
            int(max_items or note.metadata.get("max_items") or self.max_items_default),
        )
        resolved_focus = _optional_text(focus) or _optional_text(note.metadata.get("focus"))

        runtime = self._get_runtime()
        llm = getattr(runtime, "llm", None)
        if llm is None:
            raise ValueError("LLM is not enabled. Set RAG_ENABLE_LLM=true and configure a provider first.")

        transcript_text = self._build_speech_transcript_text(speech_items)
        prompt = build_lesson_note_markdown_prompt(
            course_id=note.course_id,
            lesson_id=note.lesson_id,
            transcript_text=transcript_text,
            focus=resolved_focus,
        )
        response_text = self._complete_text(llm, prompt)
        markdown = _strip_markdown_code_fence(response_text)
        title, summary = _extract_markdown_title_summary(markdown)
        final_payload = {
            "title": title,
            "overview": summary,
            "key_points": [],
            "concepts": [],
            "examples": [],
            "timeline": [],
            "review_items": [],
            "questions": [],
        }
        metadata = {
            "focus": resolved_focus,
            "max_items": resolved_max_items,
            "record_count": len(speech_items),
            "chunk_count": 1,
            "transcript_char_count": len(transcript_text),
            "source_type_counts": _source_type_counts(speech_items),
            "llm_used": True,
            "output_format": "markdown_direct_speech_only",
            "generation_mode": "single_pass_markdown",
            "generated_at": int(time.time()),
        }
        self.repository.update_note(
            note.note_id,
            status=LessonNoteStatus.DONE,
            title=title,
            summary=summary,
            markdown=markdown,
            note=final_payload,
            source_record_count=len(speech_items),
            source_hash=source_hash,
            model_name=self._resolve_model_name(llm),
            error_message=None,
            metadata=metadata,
        )
        updated = self.repository.get_note(note.note_id)
        if updated is None:
            raise RuntimeError("generated lesson note disappeared")
        return updated

    def _load_lesson_transcripts(self, *, course_id: str, lesson_id: str) -> Sequence[Mapping[str, Any]]:
        transcript_items = list(
            self.transcript_loader(
                course_id=course_id,
                lesson_id=lesson_id,
                prefer_final=True,
            )
        )
        if not transcript_items:
            raise KeyError(f"{course_id}/{lesson_id}")
        if not any(_clean_text(item) for item in transcript_items):
            raise ValueError("No usable lesson context was found for note generation.")
        return transcript_items

    def _filter_speech_transcripts(self, transcript_items: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
        speech_items: list[Mapping[str, Any]] = []
        for item in transcript_items:
            text = _clean_text(item)
            if not text:
                continue
            source_type = (str(item.get("source_type") or "").strip().lower()) or "unknown"
            if source_type not in {"realtime", "video"}:
                continue
            speech_items.append(item)

        if not speech_items:
            raise ValueError("No usable speech transcript was found for note generation.")
        return list(speech_items)

    def _build_speech_transcript_text(self, transcript_items: Sequence[Mapping[str, Any]]) -> str:
        lines: list[str] = []
        for item in transcript_items:
            text = _clean_text(item)
            if not text:
                continue
            time_label = _record_time_label(item)
            if time_label:
                lines.append(f"[{time_label}] {text}")
            else:
                chunk_id = item.get("chunk_id") or "-"
                lines.append(f"[chunk {chunk_id}] {text}")
        if not lines:
            raise ValueError("No usable speech transcript was found for note generation.")
        return "\n".join(lines)

    def _source_hash(self, transcript_items: Sequence[Mapping[str, Any]]) -> str:
        payload = []
        for item in transcript_items:
            payload.append(
                {
                    "id": item.get("id"),
                    "session_id": item.get("session_id"),
                    "chunk_id": item.get("chunk_id"),
                    "source_type": item.get("source_type"),
                    "source_file": item.get("source_file"),
                    "start_ms": item.get("start_ms"),
                    "end_ms": item.get("end_ms"),
                    "text": _clean_text(item),
                    "metadata": _hashable_metadata(item.get("metadata")),
                }
            )
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _get_runtime(self):
        if self._runtime is None:
            self._runtime = self.runtime_factory()
        return self._runtime

    @staticmethod
    def _complete_text(llm: Any, prompt: str) -> str:
        response = llm.complete(prompt)
        text = getattr(response, "text", None)
        if text is None:
            text = str(response)
        normalized = str(text).strip()
        if not normalized:
            raise ValueError("LLM returned an empty note response")
        return normalized

    @staticmethod
    def _parse_json_payload(text: str) -> Mapping[str, object] | None:
        candidates = [text.strip()]
        stripped = text.strip()
        if stripped.startswith("```"):
            lines = stripped.splitlines()
            if len(lines) >= 3:
                candidates.append("\n".join(lines[1:-1]).strip())

        start = stripped.find("{")
        end = stripped.rfind("}")
        if start != -1 and end != -1 and end > start:
            candidates.append(stripped[start:end + 1])

        for candidate in candidates:
            if not candidate:
                continue
            try:
                payload = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                return payload
        return None

    @staticmethod
    def _normalize_note_payload(
        payload: Mapping[str, object] | None,
        *,
        fallback_overview: str,
        max_items: int,
    ) -> dict[str, Any]:
        data = dict(payload or {})
        overview = _as_text(data.get("overview")) or _as_text(data.get("summary")) or fallback_overview.strip()
        title = _as_text(data.get("title")) or _derive_title(overview)
        return {
            "title": title,
            "overview": overview,
            "key_points": _normalize_text_list(data.get("key_points"), limit=max_items),
            "concepts": _normalize_concepts(data.get("concepts"), limit=max_items),
            "examples": _normalize_text_list(data.get("examples"), limit=max_items),
            "timeline": _normalize_timeline(data.get("timeline"), limit=max_items),
            "review_items": _normalize_text_list(data.get("review_items"), limit=max_items),
            "questions": _normalize_text_list(data.get("questions"), limit=max_items),
        }

    @staticmethod
    def _build_markdown(payload: Mapping[str, Any]) -> str:
        lines = [f"# {payload.get('title') or 'Lesson note'}", ""]
        overview = _as_text(payload.get("overview"))
        if overview:
            lines.extend(["## Overview", "", overview, ""])
        _append_text_list(lines, "Key Points", payload.get("key_points"))
        _append_concepts(lines, payload.get("concepts"))
        _append_text_list(lines, "Examples", payload.get("examples"))
        _append_timeline(lines, payload.get("timeline"))
        _append_text_list(lines, "Review Items", payload.get("review_items"))
        _append_text_list(lines, "Self-check Questions", payload.get("questions"))
        return "\n".join(lines).strip() + "\n"

    @staticmethod
    def _resolve_model_name(llm: Any) -> str | None:
        for attr in ("model_name", "model", "name"):
            value = getattr(llm, attr, None)
            text = _optional_text(value)
            if text:
                return text
        return None


def _required_text(value: str, field_name: str) -> str:
    text = _optional_text(value)
    if not text:
        raise ValueError(f"{field_name} is required")
    return text


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).strip().split())
    return text or None


def _clean_text(item: Mapping[str, Any]) -> str:
    return " ".join(str(item.get("clean_text") or item.get("text") or "").strip().split())


def _format_context_line(item: Mapping[str, Any], text: str) -> str:
    source = _optional_text(item.get("source_type")) or "unknown"
    chunk_id = item.get("chunk_id") or "-"
    time_label = _record_time_label(item)
    prefix = f"[source={source} chunk={chunk_id}"
    if time_label:
        prefix += f" time={time_label}"
    prefix += "]"
    return f"{prefix} {text}"


def _record_time_label(item: Mapping[str, Any]) -> str | None:
    start_ms = _optional_int(item.get("start_ms"))
    if start_ms is None:
        metadata = item.get("metadata")
        if isinstance(metadata, Mapping):
            start_ms = _optional_int(metadata.get("timeline_ms") or metadata.get("frame_timestamp_ms"))
    if start_ms is None:
        return None
    total_seconds = max(0, start_ms // 1000)
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    if hours:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _hashable_metadata(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    keys = (
        "parser",
        "transcript_role",
        "video_id",
        "asset_id",
        "region",
        "page_no",
        "timeline_ms",
        "frame_timestamp_ms",
    )
    return {key: value.get(key) for key in keys if key in value}


def _source_type_counts(transcript_items: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in transcript_items:
        source_type = _optional_text(item.get("source_type")) or "unknown"
        counts[source_type] = counts.get(source_type, 0) + 1
    return counts


def _as_text(value: object) -> str | None:
    return _optional_text(value)


def _derive_title(overview: str) -> str:
    text = _optional_text(overview) or "Lesson note"
    if len(text) <= 40:
        return text
    return text[:40].rstrip() + "..."


def _strip_markdown_code_fence(text: str) -> str:
    stripped = str(text or "").strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    if len(lines) < 3:
        return stripped
    first_line = lines[0].strip().lower()
    if first_line in {"```", "```md", "```markdown"} and lines[-1].strip() == "```":
        return "\n".join(lines[1:-1]).strip()
    return stripped


def _extract_markdown_title_summary(markdown: str) -> tuple[str, str]:
    stripped = str(markdown or "").strip()
    if not stripped:
        return "课后笔记", ""

    lines = [line.rstrip() for line in stripped.splitlines()]

    title = ""
    for line in lines:
        candidate = line.strip()
        if candidate.startswith("#"):
            title = candidate.lstrip("#").strip()
            break

    if not title:
        for line in lines:
            candidate = line.strip()
            if candidate and not candidate.startswith(("```", "-", "*", ">")):
                title = re.sub(r"^[\d.\-+\s]+", "", candidate).strip() or candidate
                break

    paragraphs: list[str] = []
    current: list[str] = []
    inside_code_block = False
    for line in lines:
        raw = line.strip()
        if raw.startswith("```"):
            inside_code_block = not inside_code_block
            continue
        if inside_code_block:
            continue
        if raw.startswith("#"):
            if current:
                paragraphs.append(" ".join(current).strip())
                current = []
            continue
        if not raw:
            if current:
                paragraphs.append(" ".join(current).strip())
                current = []
            continue
        if raw.startswith(("-", "*", ">")):
            if current:
                paragraphs.append(" ".join(current).strip())
                current = []
            continue
        current.append(raw)

    if current:
        paragraphs.append(" ".join(current).strip())

    summary = next((item for item in paragraphs if item), "")
    return _optional_text(title) or "课后笔记", summary


def _normalize_text_list(value: object, *, limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    normalized: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = _as_text(item)
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(text)
        if len(normalized) >= limit:
            break
    return normalized


def _normalize_concepts(value: object, *, limit: int) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    normalized: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in value:
        term = None
        explanation = None
        if isinstance(item, Mapping):
            term = _as_text(item.get("term"))
            explanation = _as_text(item.get("explanation") or item.get("definition"))
        elif isinstance(item, str) and ":" in item:
            left, right = item.split(":", 1)
            term = _as_text(left)
            explanation = _as_text(right)
        if not term or not explanation:
            continue
        key = term.casefold()
        if key in seen:
            continue
        seen.add(key)
        normalized.append({"term": term, "explanation": explanation})
        if len(normalized) >= limit:
            break
    return normalized


def _normalize_timeline(value: object, *, limit: int) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    normalized: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, Mapping):
            continue
        time_label = _as_text(item.get("time") or item.get("timestamp"))
        content = _as_text(item.get("content") or item.get("text"))
        if not content:
            continue
        key = f"{time_label or ''}|{content}".casefold()
        if key in seen:
            continue
        seen.add(key)
        normalized.append({"time": time_label or "", "content": content})
        if len(normalized) >= limit:
            break
    return normalized


def _append_text_list(lines: list[str], title: str, value: object) -> None:
    items = value if isinstance(value, list) else []
    normalized = [_as_text(item) for item in items]
    normalized = [item for item in normalized if item]
    if not normalized:
        return
    lines.extend([f"## {title}", ""])
    lines.extend(f"- {item}" for item in normalized)
    lines.append("")


def _append_concepts(lines: list[str], value: object) -> None:
    items = value if isinstance(value, list) else []
    concepts = [item for item in items if isinstance(item, Mapping)]
    if not concepts:
        return
    lines.extend(["## Concepts", ""])
    for item in concepts:
        term = _as_text(item.get("term"))
        explanation = _as_text(item.get("explanation"))
        if term and explanation:
            lines.append(f"- **{term}**: {explanation}")
    lines.append("")


def _append_timeline(lines: list[str], value: object) -> None:
    items = value if isinstance(value, list) else []
    timeline = [item for item in items if isinstance(item, Mapping)]
    if not timeline:
        return
    lines.extend(["## Timeline", ""])
    for item in timeline:
        time_label = _as_text(item.get("time"))
        content = _as_text(item.get("content"))
        if not content:
            continue
        if time_label:
            lines.append(f"- `{time_label}` {content}")
        else:
            lines.append(f"- {content}")
    lines.append("")
