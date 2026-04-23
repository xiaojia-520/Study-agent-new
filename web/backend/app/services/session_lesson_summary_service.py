from __future__ import annotations

import json
import threading
from typing import Any, Mapping, Sequence

from config.prompts import (
    build_lesson_summary_chunk_prompt,
    build_lesson_summary_merge_prompt,
)
from src.application.rag.runtime import close_shared_rag_runtime, get_shared_rag_runtime
from web.backend.app.domain.lesson_summary import LessonConcept, LessonSummary
from web.backend.app.domain.session import RealtimeSession
from web.backend.app.services.session_manager import session_manager
from web.backend.app.services.transcript_service import transcript_service


def _build_runtime():
    return get_shared_rag_runtime()


class SessionLessonSummaryService:
    def __init__(
        self,
        *,
        runtime_factory=None,
        runtime_closer=None,
        session_getter=session_manager.get_session,
        transcript_loader=transcript_service.list_session_transcripts,
        chunk_char_limit: int = 4000,
        max_items_default: int = 6,
    ) -> None:
        self.runtime_factory = runtime_factory or _build_runtime
        self.runtime_closer = runtime_closer or close_shared_rag_runtime
        self.session_getter = session_getter
        self.transcript_loader = transcript_loader
        self.chunk_char_limit = max(1, int(chunk_char_limit))
        self.max_items_default = max(1, int(max_items_default))
        self._runtime = None
        self._lock = threading.RLock()

    def generate_summary(
        self,
        *,
        session_id: str,
        focus: str | None = None,
        max_items: int | None = None,
    ) -> LessonSummary:
        session = self.session_getter(session_id)
        transcript_items = self.transcript_loader(session, session_id)
        if not transcript_items:
            raise KeyError(session_id)

        runtime = self._get_runtime()
        llm = getattr(runtime, "llm", None)
        if llm is None:
            raise ValueError("LLM is not enabled. Set RAG_ENABLE_LLM=true and configure a provider first.")

        resolved_max_items = max(1, int(max_items or self.max_items_default))
        transcript_chunks = self._build_transcript_chunks(transcript_items)
        chunk_payloads: list[dict[str, object]] = []
        for index, chunk in enumerate(transcript_chunks, start=1):
            prompt = build_lesson_summary_chunk_prompt(
                transcript_chunk=chunk,
                chunk_index=index,
                chunk_count=len(transcript_chunks),
                max_items=resolved_max_items,
                focus=focus,
            )
            response_text = self._complete_text(llm, prompt)
            chunk_payloads.append(
                self._normalize_summary_payload(
                    self._parse_json_payload(response_text),
                    fallback_summary=response_text,
                    max_items=resolved_max_items,
                )
            )

        if len(chunk_payloads) == 1:
            final_payload = chunk_payloads[0]
        else:
            merge_prompt = build_lesson_summary_merge_prompt(
                chunk_summaries_json=json.dumps(chunk_payloads, ensure_ascii=False, indent=2),
                max_items=resolved_max_items,
                focus=focus,
            )
            merged_text = self._complete_text(llm, merge_prompt)
            final_payload = self._normalize_summary_payload(
                self._parse_json_payload(merged_text),
                fallback_summary=merged_text,
                max_items=resolved_max_items,
            )

        context = self._resolve_summary_context(session_id, session, transcript_items)
        metadata = {
            "focus": (focus or "").strip() or None,
            "record_count": len(transcript_items),
            "chunk_count": len(transcript_chunks),
            "transcript_char_count": sum(len(chunk) for chunk in transcript_chunks),
            "llm_used": True,
            "max_items": resolved_max_items,
            "output_format": "structured_json",
            "source_type": "session_transcript",
        }
        return LessonSummary(
            session_id=session_id,
            course_id=context["course_id"],
            lesson_id=context["lesson_id"],
            subject=context["subject"],
            summary=str(final_payload["summary"]),
            key_points=list(final_payload["key_points"]),
            review_items=list(final_payload["review_items"]),
            important_terms=[
                LessonConcept(term=item["term"], definition=item["definition"])
                for item in final_payload["important_terms"]
            ],
            metadata=metadata,
        )

    def close(self) -> None:
        if callable(self.runtime_closer):
            self.runtime_closer()
        elif self._runtime is not None:
            self._runtime.index_store.close()
        self._runtime = None

    def _get_runtime(self):
        runtime = self._runtime
        if runtime is not None:
            return runtime

        with self._lock:
            runtime = self._runtime
            if runtime is None:
                runtime = self.runtime_factory()
                self._runtime = runtime
        return runtime

    def _build_transcript_chunks(self, transcript_items: Sequence[Mapping[str, Any]]) -> list[str]:
        chunks: list[str] = []
        current_lines: list[str] = []
        current_size = 0

        for item in transcript_items:
            text = self._clean_transcript_text(item)
            if not text:
                continue

            projected = current_size + len(text) + (1 if current_lines else 0)
            if current_lines and projected > self.chunk_char_limit:
                chunks.append("\n".join(current_lines))
                current_lines = [text]
                current_size = len(text)
                continue

            current_lines.append(text)
            current_size = projected

        if current_lines:
            chunks.append("\n".join(current_lines))
        if not chunks:
            raise ValueError("No usable transcript text was found for summary generation.")
        return chunks

    @staticmethod
    def _clean_transcript_text(item: Mapping[str, Any]) -> str:
        return " ".join(str(item.get("clean_text") or item.get("text") or "").strip().split())

    @staticmethod
    def _resolve_summary_context(
        session_id: str,
        session: RealtimeSession | None,
        transcript_items: Sequence[Mapping[str, Any]],
    ) -> dict[str, str]:
        def _pick(field_name: str, fallback: str) -> str:
            if session is not None:
                value = getattr(session, field_name, None)
                if isinstance(value, str) and value.strip():
                    return value.strip()
            for item in transcript_items:
                value = item.get(field_name)
                if isinstance(value, str) and value.strip():
                    return value.strip()
            return fallback

        return {
            "course_id": _pick("course_id", "unknown-course"),
            "lesson_id": _pick("lesson_id", session_id),
            "subject": _pick("subject", "untitled"),
        }

    @staticmethod
    def _complete_text(llm: Any, prompt: str) -> str:
        response = llm.complete(prompt)
        text = getattr(response, "text", None)
        if text is None:
            text = str(response)
        normalized = str(text).strip()
        if not normalized:
            raise ValueError("LLM returned an empty summary response")
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
    def _normalize_summary_payload(
        payload: Mapping[str, object] | None,
        *,
        fallback_summary: str,
        max_items: int,
    ) -> dict[str, object]:
        data = dict(payload or {})
        summary = SessionLessonSummaryService._as_text(data.get("summary")) or fallback_summary.strip()
        key_points = SessionLessonSummaryService._normalize_text_list(data.get("key_points"), limit=max_items)
        review_items = SessionLessonSummaryService._normalize_text_list(data.get("review_items"), limit=max_items)
        important_terms = SessionLessonSummaryService._normalize_terms(data.get("important_terms"), limit=max_items)
        return {
            "summary": summary,
            "key_points": key_points,
            "review_items": review_items,
            "important_terms": important_terms,
        }

    @staticmethod
    def _normalize_text_list(value: object, *, limit: int) -> list[str]:
        if not isinstance(value, list):
            return []

        normalized: list[str] = []
        seen: set[str] = set()
        for item in value:
            text = SessionLessonSummaryService._as_text(item)
            if text is None:
                continue
            key = text.casefold()
            if key in seen:
                continue
            seen.add(key)
            normalized.append(text)
            if len(normalized) >= limit:
                break
        return normalized

    @staticmethod
    def _normalize_terms(value: object, *, limit: int) -> list[dict[str, str]]:
        if not isinstance(value, list):
            return []

        normalized: list[dict[str, str]] = []
        seen: set[str] = set()
        for item in value:
            term = None
            definition = None
            if isinstance(item, Mapping):
                term = SessionLessonSummaryService._as_text(item.get("term"))
                definition = SessionLessonSummaryService._as_text(item.get("definition"))
            elif isinstance(item, str) and ":" in item:
                left, right = item.split(":", 1)
                term = SessionLessonSummaryService._as_text(left)
                definition = SessionLessonSummaryService._as_text(right)
            if term is None or definition is None:
                continue
            key = term.casefold()
            if key in seen:
                continue
            seen.add(key)
            normalized.append({"term": term, "definition": definition})
            if len(normalized) >= limit:
                break
        return normalized

    @staticmethod
    def _as_text(value: object) -> str | None:
        if value is None:
            return None
        text = " ".join(str(value).strip().split())
        return text or None


session_lesson_summary_service = SessionLessonSummaryService()
