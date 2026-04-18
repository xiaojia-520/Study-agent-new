from __future__ import annotations

import threading
from enum import Enum

from src.core.knowledge.document_models import KnowledgeAnswer
from src.core.knowledge.query_filters import MetadataFilterClause, MetadataFilterSpec
from web.backend.app.domain.session import RealtimeSession
from web.backend.app.services.session_manager import session_manager


def _build_runtime():
    from src.application.rag_runtime import build_rag_runtime

    return build_rag_runtime()


class QueryScope(str, Enum):
    AUTO = "auto"
    CURRENT_LESSON = "current_lesson"
    COURSE_ALL = "course_all"
    COURSE_HISTORY = "course_history"
    GLOBAL = "global"


_GLOBAL_SCOPE_TERMS = (
    "全库",
    "知识库",
    "其他课程",
    "别的课",
    "别门课",
    "别的课程",
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


class SessionRagQueryService:
    def __init__(
        self,
        *,
        runtime_factory=None,
        session_getter=session_manager.get_session,
    ) -> None:
        self.runtime_factory = runtime_factory or _build_runtime
        self.session_getter = session_getter
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

        llm = None
        if with_llm:
            llm = runtime.llm
            if llm is None:
                raise ValueError("LLM is not enabled. Set RAG_ENABLE_LLM=true and configure a provider first.")

        answer = runtime.query_service.query(
            query_text,
            top_k=resolved_top_k,
            embed_model=runtime.embed_model,
            llm=llm,
            filters=self.build_scope_filters(session, resolved_scope),
        )
        metadata = dict(answer.metadata)
        metadata.update(
            {
                "requested_scope": requested_scope.value,
                "scope": resolved_scope.value,
                "scope_source": scope_source,
                "session_id": session.session_id,
                "course_id": session.course_id,
                "lesson_id": session.lesson_id,
                "top_k": resolved_top_k,
                "with_llm": with_llm,
            }
        )
        return KnowledgeAnswer(
            query=answer.query,
            answer=answer.answer,
            results=answer.results,
            metadata=metadata,
        )

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
        runtime = self._runtime
        if runtime is not None:
            runtime.index_store.close()
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
    def _normalize_query_text(query_text: str) -> str:
        return " ".join((query_text or "").strip().lower().split())

    @staticmethod
    def _contains_any(text: str, phrases: tuple[str, ...]) -> bool:
        return any(phrase in text for phrase in phrases)


session_rag_query_service = SessionRagQueryService()
