from __future__ import annotations

from typing import Any

from src.application.lesson_copilot.types import CopilotRunResult, CopilotStep
from src.domain.lesson_note import LessonNote


def lesson_note_to_dict(note: LessonNote) -> dict[str, Any]:
    return {
        "id": note.id,
        "note_id": note.note_id,
        "course_id": note.course_id,
        "lesson_id": note.lesson_id,
        "session_id": note.session_id,
        "status": note.status.value,
        "title": note.title,
        "summary": note.summary,
        "markdown": note.markdown,
        "note": dict(note.note),
        "source_record_count": note.source_record_count,
        "source_hash": note.source_hash,
        "model_name": note.model_name,
        "error_message": note.error_message,
        "created_at": note.created_at,
        "updated_at": note.updated_at,
        "metadata": dict(note.metadata),
    }


def lesson_copilot_step_to_dict(step: CopilotStep) -> dict[str, Any]:
    return {
        "action": step.action,
        "thought": step.thought,
        "tool_name": step.tool_name,
        "arguments": dict(step.arguments or {}),
        "tool_ok": step.tool_ok,
        "tool_result": _compact_tool_result(step.tool_result),
        "error": step.error,
        "final_answer": step.final_answer,
    }


def lesson_copilot_result_to_dict(result: CopilotRunResult) -> dict[str, Any]:
    return {
        "answer": result.answer,
        "steps": [lesson_copilot_step_to_dict(step) for step in result.steps],
        "metadata": dict(result.metadata),
    }


def _compact_tool_result(value: Any) -> Any:
    if not isinstance(value, dict):
        return value
    payload: dict[str, Any] = {}
    for key in (
        "note_id",
        "status",
        "title",
        "summary",
        "overview",
        "count",
        "query",
        "answer",
        "course_id",
        "lesson_id",
        "session_id",
        "error_message",
    ):
        if key in value and value[key] is not None:
            payload[key] = value[key]
    for key in ("note", "items", "questions", "results", "citations", "key_points", "review_items", "important_terms"):
        item = value.get(key)
        if isinstance(item, list):
            payload[f"{key}_count"] = len(item)
            payload[key] = item[:3]
        elif isinstance(item, dict) and key == "note":
            overview = item.get("overview")
            if overview is not None:
                payload.setdefault("overview", overview)
    return payload or value


def video_response_item(video) -> dict[str, Any]:
    from dataclasses import asdict

    item = asdict(video)
    item["metadata"] = dict(video.metadata)
    item["segments"] = list(video.segments)
    item["video_url"] = f"/sessions/videos/{video.video_id}/file"
    item["srt_url"] = f"/sessions/videos/{video.video_id}/srt" if video.srt_path else None
    return item


def query_result_response_item(result, classify_source_kind) -> dict[str, object]:
    metadata = dict(getattr(result, "metadata", {}) or {})
    return {
        "doc_id": result.doc_id,
        "content": result.content,
        "score": result.score,
        "session_id": result.session_id,
        "subject": result.subject,
        "source_type": result.source_type,
        "source_kind": classify_source_kind(result.source_type, metadata),
        "metadata": metadata,
    }


def query_citation_response_item(citation, classify_source_kind) -> dict[str, object]:
    metadata = dict(getattr(citation, "metadata", {}) or {})
    return {
        "index": citation.index,
        "doc_id": citation.doc_id,
        "snippet": citation.snippet,
        "score": citation.score,
        "session_id": citation.session_id,
        "subject": citation.subject,
        "source_type": citation.source_type,
        "source_kind": classify_source_kind(citation.source_type, metadata),
        "course_id": citation.course_id,
        "lesson_id": citation.lesson_id,
        "metadata": metadata,
    }


def group_query_result_items(items: list[dict[str, object]]) -> dict[str, list[dict[str, object]]]:
    grouped: dict[str, list[dict[str, object]]] = {
        "speech": [],
        "ocr": [],
        "vlm": [],
        "documents": [],
        "other": [],
    }
    for item in items:
        source_kind = str(item.get("source_kind") or "other").strip().lower()
        if source_kind not in grouped:
            source_kind = "other"
        grouped[source_kind].append(item)
    return grouped
