from __future__ import annotations

from dataclasses import asdict
from typing import Any


class LessonCopilotAdapter:
    def __init__(self) -> None:
        from src.application.chat.memory_service import chat_memory_service
        from src.application.documents.asset_service import lesson_asset_service
        from src.application.lesson_notes.runtime import lesson_note_service, lesson_note_to_dict
        from src.application.review.lesson_quiz_service import session_lesson_quiz_service
        from src.application.review.lesson_summary_service import session_lesson_summary_service
        from src.application.rag.session_query_service import ClassroomContextMode, QueryScope, session_rag_query_service
        from src.application.transcripts.refinement_service import session_transcript_refine_service
        from src.application.video.video_service import session_video_service
        from src.application.transcripts.service import transcript_service

        self.chat_memory_service = chat_memory_service
        self.lesson_asset_service = lesson_asset_service
        self.lesson_note_service = lesson_note_service
        self.lesson_note_to_dict = lesson_note_to_dict
        self.session_lesson_quiz_service = session_lesson_quiz_service
        self.session_lesson_summary_service = session_lesson_summary_service
        self.session_rag_query_service = session_rag_query_service
        self.session_transcript_refine_service = session_transcript_refine_service
        self.session_video_service = session_video_service
        self.transcript_service = transcript_service
        self.ClassroomContextMode = ClassroomContextMode
        self.QueryScope = QueryScope

    def get_latest_note(self, course_id: str, lesson_id: str):
        note = self.lesson_note_service.get_latest_note(course_id=course_id, lesson_id=lesson_id)
        if note is None:
            return None
        return self.lesson_note_to_dict(note)

    def generate_note(
        self,
        course_id: str,
        lesson_id: str,
        *,
        focus: str | None = None,
        max_items: int | None = None,
        force: bool = False,
    ):
        note = self.lesson_note_service.generate_note(
            course_id=course_id,
            lesson_id=lesson_id,
            focus=focus,
            max_items=max_items,
            force=force,
        )
        return self.lesson_note_to_dict(note)

    def delete_lesson_note(self, course_id: str, lesson_id: str, *, note_id: str | None = None) -> dict[str, Any]:
        if note_id:
            deleted = self.lesson_note_service.delete_note(note_id)
        else:
            deleted = self.lesson_note_service.delete_latest_note(course_id=course_id, lesson_id=lesson_id)
        if deleted is None:
            return {
                "deleted": False,
                "course_id": course_id,
                "lesson_id": lesson_id,
                "note_id": note_id,
                "error_message": "lesson note not found",
            }
        return {
            "deleted": True,
            "note_id": deleted.note_id,
            "course_id": deleted.course_id,
            "lesson_id": deleted.lesson_id,
            "title": deleted.title,
            "status": deleted.status.value,
        }

    def get_lesson_transcripts(self, course_id: str, lesson_id: str, *, limit: int = 12) -> dict[str, Any]:
        items = self.transcript_service.list_lesson_transcripts(course_id=course_id, lesson_id=lesson_id)
        return {
            "count": len(items),
            "items": [self._compact_transcript_item(item) for item in items[: max(1, int(limit))]],
            "source_type_counts": self._count_by_source_type(items),
        }

    def get_refined_lesson_transcripts(self, course_id: str, lesson_id: str, *, limit: int = 12) -> dict[str, Any]:
        items = self.session_transcript_refine_service.list_lesson_refined_transcripts(
            course_id=course_id,
            lesson_id=lesson_id,
        )
        compact = []
        for item in items[: max(1, int(limit))]:
            compact.append(
                {
                    "id": item.id,
                    "source_record_id": item.source_record_id,
                    "session_id": item.session_id,
                    "chunk_id": item.chunk_id,
                    "refined_text": item.refined_text,
                    "original_text": item.original_text,
                    "model_name": item.model_name,
                }
            )
        return {"count": len(items), "items": compact}

    def get_lesson_videos(self, course_id: str, lesson_id: str, *, limit: int = 6) -> dict[str, Any]:
        items = self.session_video_service.list_lesson_videos(course_id=course_id, lesson_id=lesson_id)
        compact = []
        for item in items[: max(1, int(limit))]:
            compact.append(
                {
                    "video_id": item.video_id,
                    "status": item.status,
                    "file_name": item.file_name,
                    "segment_count": item.segment_count,
                    "text": self._trim_text(item.text, 220),
                    "created_at": item.created_at,
                }
            )
        return {"count": len(items), "items": compact}

    def get_session_assets(self, session_id: str, *, limit: int = 6) -> dict[str, Any]:
        normalized_session_id = self._require_session_id(session_id)
        items = self.lesson_asset_service.list_session_assets(normalized_session_id)
        compact = []
        for item in items[: max(1, int(limit))]:
            compact.append(
                {
                    "asset_id": item.asset_id,
                    "status": item.status,
                    "file_name": item.file_name,
                    "media_type": item.media_type,
                    "record_count": item.record_count,
                    "created_at": item.created_at,
                }
            )
        return {"count": len(items), "items": compact}

    def search_available_assets(self, *, query: str | None = None, limit: int = 6) -> dict[str, Any]:
        all_items = [item for item in self.lesson_asset_service.list_assets(limit=100) if item.status == "done"]
        terms = [term for term in str(query or "").lower().split() if term]
        scored_items = []
        for item in all_items:
            haystack = " ".join(
                str(value or "")
                for value in (
                    item.file_name,
                    item.subject,
                    item.metadata.get("original_file_name"),
                    item.metadata.get("source_file_name"),
                )
            ).lower()
            score = sum(1 for term in terms if term in haystack) if terms else 0
            if terms and score <= 0:
                continue
            scored_items.append((score, item))
        scored_items.sort(key=lambda pair: (pair[0], pair[1].updated_at), reverse=True)
        selected = [item for _, item in scored_items[: max(1, int(limit))]]
        return {
            "query": query,
            "count": len(selected),
            "total_available_count": len(all_items),
            "items": [
                {
                    "asset_id": item.asset_id,
                    "status": item.status,
                    "file_name": item.file_name,
                    "subject": item.subject,
                    "media_type": item.media_type,
                    "record_count": item.record_count,
                    "library_asset": bool(item.metadata.get("library_asset")),
                    "created_at": item.created_at,
                    "updated_at": item.updated_at,
                }
                for item in selected
            ],
        }

    def get_lesson_messages(self, course_id: str, lesson_id: str, *, limit: int = 10) -> dict[str, Any]:
        items = self.chat_memory_service.list_lesson_messages(
            course_id=course_id,
            lesson_id=lesson_id,
            limit=max(1, int(limit)),
        )
        compact = []
        for item in items:
            compact.append(
                {
                    "id": item.id,
                    "role": item.role,
                    "content": self._trim_text(item.content, 220),
                    "created_at": item.created_at,
                }
            )
        return {"count": len(items), "items": compact}

    def generate_quiz(
        self,
        session_id: str,
        *,
        focus: str | None = None,
        question_count: int | None = None,
    ) -> dict[str, Any]:
        normalized_session_id = self._require_session_id(session_id)
        quiz = self.session_lesson_quiz_service.generate_quiz(
            session_id=normalized_session_id,
            focus=focus,
            question_count=question_count,
        )
        return {
            "session_id": quiz.session_id,
            "course_id": quiz.course_id,
            "lesson_id": quiz.lesson_id,
            "subject": quiz.subject,
            "questions": [asdict(item) for item in quiz.questions],
            "metadata": dict(quiz.metadata),
        }

    def generate_summary(
        self,
        session_id: str,
        *,
        focus: str | None = None,
        max_items: int | None = None,
    ) -> dict[str, Any]:
        normalized_session_id = self._require_session_id(session_id)
        summary = self.session_lesson_summary_service.generate_summary(
            session_id=normalized_session_id,
            focus=focus,
            max_items=max_items,
        )
        return {
            "session_id": summary.session_id,
            "course_id": summary.course_id,
            "lesson_id": summary.lesson_id,
            "subject": summary.subject,
            "summary": summary.summary,
            "key_points": list(summary.key_points),
            "review_items": list(summary.review_items),
            "important_terms": [asdict(item) for item in summary.important_terms],
            "metadata": dict(summary.metadata),
        }

    def query_lesson_knowledge(
        self,
        session_id: str,
        *,
        query: str,
        scope: str = "current_lesson",
        top_k: int = 5,
        with_llm: bool = False,
        asset_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        normalized_session_id = self._require_session_id(session_id)
        answer = self.session_rag_query_service.query_session(
            session_id=normalized_session_id,
            query_text=query,
            scope=self.QueryScope(scope),
            top_k=max(1, int(top_k)),
            with_llm=bool(with_llm),
            include_rag_context=False,
            classroom_context_mode=self.ClassroomContextMode.LESSON,
            asset_ids=asset_ids,
        )
        return {
            "query": answer.query,
            "answer": answer.answer,
            "results": [
                {
                    "doc_id": item.doc_id,
                    "content": self._trim_text(item.content, 220),
                    "score": item.score,
                    "source_type": item.source_type,
                    "session_id": item.session_id,
                    "metadata": dict(item.metadata),
                }
                for item in answer.results[:5]
            ],
            "citations": [
                {
                    "index": item.index,
                    "doc_id": item.doc_id,
                    "snippet": item.snippet,
                    "score": item.score,
                    "source_type": item.source_type,
                }
                for item in answer.citations[:5]
            ],
            "metadata": dict(answer.metadata),
        }

    @staticmethod
    def _require_session_id(session_id: str | None) -> str:
        normalized = (session_id or "").strip()
        if not normalized:
            raise ValueError("session_id is required for this tool")
        return normalized

    @staticmethod
    def _compact_transcript_item(item: dict[str, Any]) -> dict[str, Any]:
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        return {
            "id": item.get("id"),
            "session_id": item.get("session_id"),
            "chunk_id": item.get("chunk_id"),
            "source_type": item.get("source_type"),
            "text": LessonCopilotAdapter._trim_text(item.get("clean_text") or item.get("text"), 220),
            "start_ms": item.get("start_ms"),
            "end_ms": item.get("end_ms"),
            "parser": metadata.get("parser"),
        }

    @staticmethod
    def _trim_text(value: Any, limit: int) -> str:
        text = " ".join(str(value or "").split()).strip()
        if len(text) <= limit:
            return text
        return text[: limit - 3].rstrip() + "..."

    @staticmethod
    def _count_by_source_type(items: list[dict[str, Any]]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in items:
            source_type = str(item.get("source_type") or "unknown").strip() or "unknown"
            counts[source_type] = counts.get(source_type, 0) + 1
        return counts
