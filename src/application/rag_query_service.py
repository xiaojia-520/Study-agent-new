from __future__ import annotations

from typing import Any

from src.core.knowledge.document_models import KnowledgeAnswer, SearchResult
from src.infrastructure.storage.qdrant_index_store import QdrantIndexStore


class RagQueryService:
    def __init__(self, *, index_store: Any | None = None) -> None:
        self.index_store = index_store or QdrantIndexStore()

    def search(
        self,
        query_text: str,
        *,
        top_k: int = 5,
        embed_model: Any = None,
        filters: Any = None,
    ) -> list[SearchResult]:
        clean_query = self._normalize_query(query_text)
        retriever = self.index_store.as_retriever(
            top_k=top_k,
            embed_model=embed_model,
            filters=filters,
        )
        nodes = retriever.retrieve(clean_query)
        return [self._to_search_result(node_with_score) for node_with_score in nodes]

    def query(
        self,
        query_text: str,
        *,
        top_k: int = 5,
        embed_model: Any = None,
        llm: Any = None,
        filters: Any = None,
    ) -> KnowledgeAnswer:
        clean_query = self._normalize_query(query_text)
        if llm is None:
            return KnowledgeAnswer(
                query=clean_query,
                answer=None,
                results=self.search(
                    clean_query,
                    top_k=top_k,
                    embed_model=embed_model,
                    filters=filters,
                ),
            )

        query_engine = self.index_store.as_query_engine(
            top_k=top_k,
            embed_model=embed_model,
            llm=llm,
            filters=filters,
        )
        response = query_engine.query(clean_query)
        return KnowledgeAnswer(
            query=clean_query,
            answer=self._extract_response_text(response),
            results=self._extract_results_from_response(response),
            metadata=self._extract_response_metadata(response),
        )

    @staticmethod
    def _normalize_query(query_text: str) -> str:
        clean_query = (query_text or "").strip()
        if not clean_query:
            raise ValueError("query_text is required")
        return clean_query

    def _extract_results_from_response(self, response: Any) -> list[SearchResult]:
        source_nodes = getattr(response, "source_nodes", None) or []
        return [self._to_search_result(node_with_score) for node_with_score in source_nodes]

    @staticmethod
    def _extract_response_text(response: Any) -> str:
        if response is None:
            return ""
        if hasattr(response, "response"):
            return str(getattr(response, "response") or "")
        return str(response)

    @staticmethod
    def _extract_response_metadata(response: Any) -> dict[str, object]:
        metadata = getattr(response, "metadata", None)
        if isinstance(metadata, dict):
            return dict(metadata)
        return {}

    @staticmethod
    def _to_search_result(node_with_score: Any) -> SearchResult:
        score = getattr(node_with_score, "score", None)
        node = getattr(node_with_score, "node", node_with_score)
        metadata = RagQueryService._extract_node_metadata(node)
        text = RagQueryService._extract_node_text(node)
        doc_id = (
            metadata.get("doc_id")
            or getattr(node, "doc_id", None)
            or getattr(node, "node_id", None)
            or getattr(node, "id_", None)
            or ""
        )
        return SearchResult(
            doc_id=str(doc_id),
            content=text,
            score=float(score) if score is not None else None,
            session_id=_optional_metadata_str(metadata, "session_id"),
            subject=_optional_metadata_str(metadata, "subject"),
            source_type=_optional_metadata_str(metadata, "source_type"),
            metadata=metadata,
        )

    @staticmethod
    def _extract_node_text(node: Any) -> str:
        if node is None:
            return ""
        if hasattr(node, "get_text"):
            return str(node.get_text() or "")
        if hasattr(node, "text"):
            return str(getattr(node, "text") or "")
        return str(node)

    @staticmethod
    def _extract_node_metadata(node: Any) -> dict[str, object]:
        metadata = getattr(node, "metadata", None)
        if isinstance(metadata, dict):
            return dict(metadata)
        return {}


def _optional_metadata_str(metadata: dict[str, object], key: str) -> str | None:
    value = metadata.get(key)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


rag_query_service = RagQueryService()
