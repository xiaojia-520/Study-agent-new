from __future__ import annotations

import threading
from enum import Enum
from typing import Any, Mapping

from config.prompts import NO_CONTEXT_ANSWER, build_direct_llm_answer_prompt, build_rag_cited_answer_prompt
from src.application.rag.runtime import close_shared_rag_runtime, get_shared_rag_runtime
from src.core.knowledge.document_models import AnswerCitation, KnowledgeAnswer, SearchResult, TranscriptRecord
from src.core.knowledge.query_filters import MetadataFilterClause, MetadataFilterSpec
from src.domain.session import RealtimeSession
from web.backend.app.services.chat_memory_service import ChatMemoryService, ChatMemoryTurn, chat_memory_service
from src.application.runtime.session_manager import session_manager
from web.backend.app.services.transcript_service import transcript_service


def _build_runtime():
    return get_shared_rag_runtime()


class QueryScope(str, Enum):
    AUTO = "auto"
    CURRENT_LESSON = "current_lesson"
    COURSE_ALL = "course_all"
    COURSE_HISTORY = "course_history"
    GLOBAL = "global"


class ClassroomContextMode(str, Enum):
    SESSION = "session"
    LESSON = "lesson"


_SCOPE_LABELS: dict[QueryScope, str] = {
    QueryScope.AUTO: "auto",
    QueryScope.CURRENT_LESSON: "current lesson",
    QueryScope.COURSE_ALL: "whole course",
    QueryScope.COURSE_HISTORY: "course history",
    QueryScope.GLOBAL: "global knowledge base",
}

_GLOBAL_SCOPE_TERMS = (
    "全库",
    "知识库",
    "其他课程",
    "别的课",
    "别门课",
    "全部课程",
    "所有课程",
    "global",
    "other course",
    "other courses",
    "knowledge base",
)

_COURSE_HISTORY_TERMS = (
    "之前",
    "以前",
    "上次",
    "历史",
    "有没有讲过",
    "讲过没有",
    "提过没有",
    "之前讲过",
    "以前讲过",
    "之前提过",
    "history",
    "previous",
    "earlier",
    "have we covered",
    "covered before",
    "mentioned before",
)

_COURSE_ALL_TERMS = (
    "整门课",
    "整个课程",
    "本课程",
    "这门课里",
    "这门课中",
    "课程里",
    "course overall",
    "whole course",
    "entire course",
    "throughout the course",
)

_CURRENT_LESSON_TERMS = (
    "刚才",
    "当前",
    "这节课",
    "这一节",
    "本节",
    "这里",
    "眼下",
    "目前",
    "current lesson",
    "just now",
    "this lesson",
    "right now",
)

_RECENT_TIMELINE_TERMS = (
    "刚才",
    "刚刚",
    "前面",
    "上一段",
    "上一页",
    "前几条",
    "最近",
    "最后",
    "最后一段",
    "最后几句",
    "末尾",
    "just now",
    "earlier",
    "previous lines",
    "previous part",
    "recently",
    "latest",
    "last part",
    "last few lines",
)


class SessionRagQueryService:
    def __init__(
        self,
        *,
        runtime_factory=None,
        runtime_closer=None,
        session_getter=session_manager.get_session,
        transcript_loader=transcript_service.list_session_transcripts,
        lesson_transcript_loader=transcript_service.list_lesson_transcripts,
        recent_transcript_limit: int = 3,
        recent_classroom_context_limit: int = 30,
        recent_lesson_window_limit: int = 8,
        memory_service: ChatMemoryService | None = None,
        memory_turn_limit: int = 6,
        memory_search_turn_limit: int = 2,
    ) -> None:
        self.runtime_factory = runtime_factory or _build_runtime
        self.runtime_closer = runtime_closer or close_shared_rag_runtime
        self.session_getter = session_getter
        self.transcript_loader = transcript_loader
        self.lesson_transcript_loader = lesson_transcript_loader
        self.recent_transcript_limit = max(0, int(recent_transcript_limit))
        self.recent_classroom_context_limit = max(0, int(recent_classroom_context_limit))
        self.recent_lesson_window_limit = max(0, int(recent_lesson_window_limit))
        self.memory_service = memory_service
        self.memory_turn_limit = max(0, int(memory_turn_limit))
        self.memory_search_turn_limit = max(0, int(memory_search_turn_limit))
        self._runtime = None
        self._lock = threading.RLock()

    def query_session(
        self,
        *,
        session_id: str,
        query_text: str,
        scope: QueryScope | str = QueryScope.CURRENT_LESSON,
        top_k: int | None = None,
        with_llm: bool = False,
        include_rag_context: bool = False,
        classroom_context_mode: ClassroomContextMode | str = ClassroomContextMode.SESSION,
    ) -> KnowledgeAnswer:
        session = self.session_getter(session_id)
        if session is None:
            raise KeyError(session_id)

        runtime = self._get_runtime()
        requested_scope = QueryScope(scope)
        resolved_scope, scope_source = self.resolve_scope(
            query_text=query_text,
            requested_scope=requested_scope,
        )
        resolved_top_k = int(top_k or runtime.config.top_k)
        if resolved_top_k <= 0:
            raise ValueError("top_k must be greater than 0")
        resolved_context_mode = ClassroomContextMode(classroom_context_mode)

        llm = None
        if with_llm:
            llm = runtime.llm
            if llm is None:
                raise ValueError("LLM is not enabled. Set RAG_ENABLE_LLM=true and configure a provider first.")

        clean_query = self._clean_query_text(query_text)
        conversation_history = self._get_memory_snapshot(session)
        search_query = self._build_memory_augmented_query(clean_query, conversation_history)
        filters = self.build_scope_filters(session, resolved_scope)
        results: list[SearchResult] = []
        citations: list[AnswerCitation] = []

        metadata = self._build_base_metadata(
            session=session,
            requested_scope=requested_scope,
            resolved_scope=resolved_scope,
            scope_source=scope_source,
            top_k=resolved_top_k,
            with_llm=with_llm,
            include_rag_context=include_rag_context,
            citation_count=len(citations),
        )
        metadata["memory_turn_count"] = len(conversation_history)
        metadata["memory_scope"] = "lesson"
        metadata["classroom_context_mode"] = resolved_context_mode.value
        if search_query != clean_query:
            metadata["memory_augmented_query"] = search_query

        if not with_llm:
            results = runtime.query_service.search(
                search_query,
                top_k=resolved_top_k,
                embed_model=runtime.embed_model,
                filters=filters,
            )
            citations = self._build_citations(results)
            metadata["answer_strategy"] = "retrieval_only"
            metadata["answer_prompt_version"] = "retrieval-only-v1"
            metadata["citation_count"] = len(citations)
            answer = KnowledgeAnswer(
                query=clean_query,
                answer=None,
                results=results,
                citations=citations,
                metadata=metadata,
            )
            self._remember_turn(session, clean_query, answer)
            return answer

        recent_transcripts: list[str] = []
        recent_classroom_context: list[str] = []
        if include_rag_context:
            results = runtime.query_service.search(
                search_query,
                top_k=resolved_top_k,
                embed_model=runtime.embed_model,
                filters=filters,
            )
            citations = self._build_citations(results)
            recent_transcripts = self._load_recent_transcript_texts(
                session,
                session_id=session_id,
                context_mode=resolved_context_mode,
            )
            metadata["recent_transcript_count"] = len(recent_transcripts)
            metadata["answer_prompt_version"] = "cited-answer-v3"
        else:
            results, recent_classroom_context, direct_context_metadata = self._build_direct_classroom_context(
                runtime=runtime,
                session=session,
                session_id=session_id,
                query_text=clean_query,
                search_query=search_query,
                filters=filters,
                top_k=resolved_top_k,
                context_mode=resolved_context_mode,
            )
            metadata.update(direct_context_metadata)
            metadata["recent_classroom_context_count"] = len(recent_classroom_context)
            metadata["answer_prompt_version"] = "direct-answer-v3"

        if include_rag_context and not citations and not recent_transcripts and not conversation_history:
            metadata["answer_strategy"] = "no_context"
            metadata["llm_used"] = False
            answer = KnowledgeAnswer(
                query=clean_query,
                answer=NO_CONTEXT_ANSWER,
                results=results,
                citations=citations,
                metadata=metadata,
            )
            self._remember_turn(session, clean_query, answer)
            return answer

        try:
            answer_text = self._synthesize_answer(
                llm=llm,
                query_text=clean_query,
                subject=getattr(session, "subject", None),
                scope=resolved_scope,
                citations=citations,
                recent_transcripts=recent_transcripts,
                recent_classroom_context=recent_classroom_context,
                conversation_history=conversation_history,
                include_rag_context=include_rag_context,
            )
        except Exception as exc:
            raise ValueError(f"LLM synthesis failed: {exc}") from exc

        metadata["answer_strategy"] = "llm_rag_synthesized" if include_rag_context else "llm_direct"
        metadata["llm_used"] = True
        answer = KnowledgeAnswer(
            query=clean_query,
            answer=answer_text,
            results=results,
            citations=citations,
            metadata=metadata,
        )
        self._remember_turn(session, clean_query, answer)
        return answer

    def resolve_scope(
        self,
        *,
        query_text: str,
        requested_scope: QueryScope | str,
    ) -> tuple[QueryScope, str]:
        resolved_requested_scope = QueryScope(requested_scope)
        if resolved_requested_scope is not QueryScope.AUTO:
            return resolved_requested_scope, "explicit"
        return self.infer_scope(query_text), "rule"

    def infer_scope(self, query_text: str) -> QueryScope:
        normalized = self._normalize_query_text(query_text)
        if self._contains_any(normalized, _GLOBAL_SCOPE_TERMS):
            return QueryScope.GLOBAL
        if self._contains_any(normalized, _COURSE_HISTORY_TERMS):
            return QueryScope.COURSE_HISTORY
        if self._contains_any(normalized, _COURSE_ALL_TERMS):
            return QueryScope.COURSE_ALL
        if self._contains_any(normalized, _CURRENT_LESSON_TERMS):
            return QueryScope.CURRENT_LESSON
        return QueryScope.CURRENT_LESSON

    def build_scope_filters(
        self,
        session: RealtimeSession,
        scope: QueryScope | str,
    ) -> MetadataFilterSpec | None:
        resolved_scope = QueryScope(scope)
        if resolved_scope is QueryScope.AUTO:
            raise ValueError("scope 'auto' must be resolved before building metadata filters")
        if resolved_scope is QueryScope.GLOBAL:
            return None
        if resolved_scope is QueryScope.CURRENT_LESSON:
            return MetadataFilterSpec(
                clauses=(
                    MetadataFilterClause("lesson_id", session.lesson_id),
                )
            )
        if resolved_scope is QueryScope.COURSE_ALL:
            return MetadataFilterSpec(
                clauses=(
                    MetadataFilterClause("course_id", session.course_id),
                )
            )
        return MetadataFilterSpec(
            clauses=(
                MetadataFilterClause("course_id", session.course_id),
                MetadataFilterClause("lesson_id", session.lesson_id, operator="ne"),
            )
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

    @staticmethod
    def _clean_query_text(query_text: str) -> str:
        clean_query = (query_text or "").strip()
        if not clean_query:
            raise ValueError("query_text is required")
        return clean_query

    @staticmethod
    def _normalize_query_text(query_text: str) -> str:
        return " ".join((query_text or "").strip().lower().split())

    @staticmethod
    def _contains_any(text: str, phrases: tuple[str, ...]) -> bool:
        return any(phrase in text for phrase in phrases)

    @staticmethod
    def _build_citations(results: list[SearchResult]) -> list[AnswerCitation]:
        citations: list[AnswerCitation] = []
        for index, result in enumerate(results, start=1):
            metadata = dict(result.metadata)
            citations.append(
                AnswerCitation(
                    index=index,
                    doc_id=result.doc_id,
                    snippet=SessionRagQueryService._build_snippet(result.content),
                    score=result.score,
                    session_id=result.session_id,
                    subject=result.subject,
                    source_type=result.source_type,
                    course_id=_metadata_str(metadata, "course_id"),
                    lesson_id=_metadata_str(metadata, "lesson_id"),
                    metadata=metadata,
                )
            )
        return citations

    @staticmethod
    def _build_snippet(text: str, limit: int = 320) -> str:
        normalized = " ".join((text or "").split())
        if len(normalized) <= limit:
            return normalized
        return normalized[: limit - 3].rstrip() + "..."

    def _build_base_metadata(
        self,
        *,
        session: RealtimeSession,
        requested_scope: QueryScope,
        resolved_scope: QueryScope,
        scope_source: str,
        top_k: int,
        with_llm: bool,
        include_rag_context: bool,
        citation_count: int,
    ) -> dict[str, Any]:
        return {
            "requested_scope": requested_scope.value,
            "scope": resolved_scope.value,
            "scope_source": scope_source,
            "scope_label": _SCOPE_LABELS[resolved_scope],
            "session_id": session.session_id,
            "course_id": session.course_id,
            "lesson_id": session.lesson_id,
            "top_k": top_k,
            "with_llm": with_llm,
            "llm_requested": with_llm,
            "llm_used": False,
            "llm_fallback": False,
            "include_rag_context": include_rag_context,
            "citation_count": citation_count,
            "recent_transcript_count": 0,
            "retrieved_classroom_context_count": 0,
            "recent_lesson_window_count": 0,
            "memory_turn_count": 0,
            "memory_scope": "lesson",
            "answer_prompt_version": "direct-answer-v1",
        }

    def _synthesize_answer(
        self,
        *,
        llm: Any,
        query_text: str,
        subject: str | None,
        scope: QueryScope,
        citations: list[AnswerCitation],
        recent_transcripts: list[str],
        recent_classroom_context: list[str],
        conversation_history: list[ChatMemoryTurn],
        include_rag_context: bool,
    ) -> str:
        if include_rag_context:
            prompt = build_rag_cited_answer_prompt(
                question=query_text,
                scope_label=_SCOPE_LABELS[scope],
                citations=citations,
                recent_transcripts=recent_transcripts,
                conversation_history=[(turn.user, turn.assistant) for turn in conversation_history],
            )
        else:
            prompt = build_direct_llm_answer_prompt(
                question=query_text,
                subject=subject,
                recent_classroom_context=recent_classroom_context,
                conversation_history=[(turn.user, turn.assistant) for turn in conversation_history],
            )
        response = llm.complete(prompt)
        answer_text = getattr(response, "text", None)
        if answer_text is None:
            answer_text = str(response)
        normalized = str(answer_text).strip()
        if not normalized:
            raise ValueError("LLM returned an empty answer")
        return normalized

    def _get_memory_snapshot(self, session: RealtimeSession) -> list[ChatMemoryTurn]:
        if self.memory_service is None or self.memory_turn_limit <= 0:
            return []
        lesson_loader = getattr(self.memory_service, "list_recent_lesson_turns", None)
        if callable(lesson_loader):
            return lesson_loader(
                course_id=session.course_id,
                lesson_id=session.lesson_id,
                limit=self.memory_turn_limit,
            )
        return self.memory_service.list_recent_turns(session.session_id, limit=self.memory_turn_limit)

    def _remember_turn(self, session: RealtimeSession, query_text: str, answer: KnowledgeAnswer) -> None:
        if self.memory_service is None or self.memory_turn_limit <= 0:
            return
        assistant_text = self._build_memory_assistant_text(answer)
        self.memory_service.append_turn(
            session=session,
            user_text=query_text,
            assistant_text=assistant_text,
            answer_metadata=dict(answer.metadata),
        )

    @staticmethod
    def _build_memory_assistant_text(answer: KnowledgeAnswer) -> str | None:
        if answer.answer and answer.answer.strip():
            return answer.answer

        snippets = [
            SessionRagQueryService._build_snippet(result.content, limit=180)
            for result in answer.results[:2]
            if result.content.strip()
        ]
        if not snippets:
            return None
        return "Retrieved context: " + " | ".join(snippets)

    def _build_memory_augmented_query(
        self,
        query_text: str,
        conversation_history: list[ChatMemoryTurn],
    ) -> str:
        if self.memory_search_turn_limit <= 0 or not conversation_history:
            return query_text

        selected_turns = conversation_history[-self.memory_search_turn_limit :]
        blocks: list[str] = []
        for turn in selected_turns:
            user = " ".join(turn.user.strip().split())
            assistant = " ".join((turn.assistant or "").strip().split())
            if user:
                blocks.append(f"Previous question: {user}")
            if assistant:
                blocks.append(f"Previous answer: {assistant}")
        blocks.append(f"Current question:\n{query_text}")
        return "\n".join(blocks)

    def _load_recent_transcript_texts(
        self,
        session: RealtimeSession,
        *,
        session_id: str,
        context_mode: ClassroomContextMode = ClassroomContextMode.SESSION,
    ) -> list[str]:
        if self.recent_transcript_limit <= 0:
            return []

        items = self._load_transcript_items(session, session_id=session_id, context_mode=context_mode)
        texts: list[str] = []
        for item in items:
            text = self._extract_transcript_text(item)
            if text:
                texts.append(text)
        return texts[-self.recent_transcript_limit:]

    def _load_recent_classroom_context(
        self,
        session: RealtimeSession,
        *,
        session_id: str,
    ) -> list[str]:
        if self.recent_classroom_context_limit <= 0:
            return []

        items = self._load_transcript_items(
            session,
            session_id=session_id,
            context_mode=ClassroomContextMode.SESSION,
        )
        blocks: list[str] = []
        for index, item in enumerate(items[-self.recent_classroom_context_limit :], start=1):
            block = self._format_classroom_context_item(index, item)
            if block:
                blocks.append(block)
        return blocks

    def _build_direct_classroom_context(
        self,
        *,
        runtime: Any,
        session: RealtimeSession,
        session_id: str,
        query_text: str,
        search_query: str,
        filters: MetadataFilterSpec | None,
        top_k: int,
        context_mode: ClassroomContextMode,
    ) -> tuple[list[SearchResult], list[str], dict[str, Any]]:
        if context_mode is ClassroomContextMode.SESSION:
            return [], self._load_recent_classroom_context(session, session_id=session_id), {}

        results = runtime.query_service.search(
            search_query,
            top_k=top_k,
            embed_model=runtime.embed_model,
            filters=filters,
        )

        blocks: list[str] = []
        for index, result in enumerate(results, start=1):
            block = self._format_search_result_context_item(index, result)
            if block:
                blocks.append(block)

        recent_window_count = 0
        if self._should_include_recent_lesson_window(query_text):
            lesson_items = self._load_lesson_transcript_items(session)
            recent_items = lesson_items[-self.recent_lesson_window_limit :] if self.recent_lesson_window_limit > 0 else []
            recent_window_count = len(recent_items)
            start_index = len(blocks) + 1
            for index, item in enumerate(recent_items, start=start_index):
                block = self._format_classroom_context_item(index, item)
                if block:
                    blocks.append(block)

        metadata = {
            "retrieved_classroom_context_count": len(results),
            "recent_lesson_window_count": recent_window_count,
        }
        return results, blocks, metadata

    def _load_transcript_items(
        self,
        session: RealtimeSession,
        *,
        session_id: str,
        context_mode: ClassroomContextMode,
    ) -> list[object]:
        if context_mode is ClassroomContextMode.LESSON:
            return self._load_lesson_transcript_items(session)
        return self.transcript_loader(session, session_id)

    def _load_lesson_transcript_items(self, session: RealtimeSession) -> list[object]:
        if not session.course_id or not session.lesson_id:
            return []
        return self.lesson_transcript_loader(
            course_id=session.course_id,
            lesson_id=session.lesson_id,
        )

    @staticmethod
    def _should_include_recent_lesson_window(query_text: str) -> bool:
        normalized = SessionRagQueryService._normalize_query_text(query_text)
        return SessionRagQueryService._contains_any(normalized, _RECENT_TIMELINE_TERMS)

    @staticmethod
    def _format_classroom_context_item(index: int, item: object) -> str:
        subject = "-"
        source_type = "-"
        text = ""
        start_ms = None
        metadata: Mapping[str, Any] | dict[str, Any] = {}

        if isinstance(item, TranscriptRecord):
            subject = item.subject or "-"
            source_type = item.source_type or "-"
            text = item.content
            start_ms = item.start_ms
            metadata = item.metadata
        elif isinstance(item, Mapping):
            subject = str(item.get("subject") or "-").strip() or "-"
            source_type = str(item.get("source_type") or "-").strip() or "-"
            text = str(item.get("clean_text") or item.get("text") or "")
            start_ms = item.get("start_ms")
            raw_metadata = item.get("metadata")
            if isinstance(raw_metadata, Mapping):
                metadata = raw_metadata

        clean_text = " ".join(text.strip().split())
        if not clean_text:
            return ""

        tags = [f"type={source_type}", f"subject={subject}"]
        parser = str(metadata.get("parser") or "").strip()
        region = str(metadata.get("region") or "").strip()
        if parser:
            tags.append(f"parser={parser}")
        if region:
            tags.append(f"region={region}")
        timeline_ms = SessionRagQueryService._safe_optional_int(start_ms)
        if timeline_ms is not None:
            tags.append(f"t={SessionRagQueryService._format_mmss(timeline_ms)}")

        snippet = SessionRagQueryService._build_snippet(clean_text, limit=220)
        return f"C{index}. [{'; '.join(tags)}] {snippet}"

    @staticmethod
    def _format_search_result_context_item(index: int, result: SearchResult) -> str:
        metadata = dict(result.metadata or {})
        subject = (result.subject or "-").strip() if isinstance(result.subject, str) else str(result.subject or "-")
        source_type = (result.source_type or "-").strip() if isinstance(result.source_type, str) else str(result.source_type or "-")
        clean_text = " ".join((result.content or "").strip().split())
        if not clean_text:
            return ""

        tags = [f"type={source_type}", f"subject={subject}", "context=retrieved"]
        parser = str(metadata.get("parser") or "").strip()
        region = str(metadata.get("region") or "").strip()
        if parser:
            tags.append(f"parser={parser}")
        if region:
            tags.append(f"region={region}")
        score = getattr(result, "score", None)
        if isinstance(score, (int, float)):
            tags.append(f"score={float(score):.3f}")

        snippet = SessionRagQueryService._build_snippet(clean_text, limit=220)
        return f"C{index}. [{'; '.join(tags)}] {snippet}"

    @staticmethod
    def _format_mmss(milliseconds: int) -> str:
        total_seconds = max(0, int(milliseconds) // 1000)
        minutes, seconds = divmod(total_seconds, 60)
        hours, minutes = divmod(minutes, 60)
        if hours > 0:
            return f"{hours}:{minutes:02d}:{seconds:02d}"
        return f"{minutes:02d}:{seconds:02d}"

    @staticmethod
    def _safe_optional_int(value: object) -> int | None:
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _extract_transcript_text(item: object) -> str:
        if isinstance(item, TranscriptRecord):
            text = item.content
        elif isinstance(item, Mapping):
            try:
                text = TranscriptRecord.from_dict(item).content
            except ValueError:
                text = str(item.get("clean_text") or item.get("text") or "")
        else:
            text = ""
        return " ".join(text.strip().split())


def _metadata_str(metadata: dict[str, object], key: str) -> str | None:
    value = metadata.get(key)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


session_rag_query_service = SessionRagQueryService(memory_service=chat_memory_service)
