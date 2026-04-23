from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import threading
from typing import Any

from config.settings import settings
from src.application.rag.indexing_service import RagIndexingService
from src.application.rag.query_service import RagQueryService
from src.core.knowledge.document_models import ChunkingOptions
from src.core.knowledge.llamaindex_builder import build_default_embed_model
from src.infrastructure.storage.qdrant_index_store import QdrantIndexStore, QdrantIndexStoreConfig


@dataclass(slots=True)
class RagRuntimeConfig:
    transcript_root: Path
    qdrant_url: str
    qdrant_collection: str
    qdrant_prefer_local: bool
    qdrant_local_path: Path
    qdrant_timeout: int
    embed_model_name: Path
    chunk_options: ChunkingOptions
    top_k: int
    llm_enabled: bool
    llm_provider: str
    llm_model: str
    llm_api_key: str
    llm_api_base: str
    llm_temperature: float
    llm_max_tokens: int | None
    llm_timeout: float

    @classmethod
    def from_settings(cls) -> "RagRuntimeConfig":
        return cls(
            transcript_root=settings.RAG_TRANSCRIPT_ROOT,
            qdrant_url=settings.QDRANT_URL,
            qdrant_collection=settings.RAG_QDRANT_COLLECTION,
            qdrant_prefer_local=settings.RAG_QDRANT_PREFER_LOCAL,
            qdrant_local_path=settings.RAG_QDRANT_LOCAL_PATH,
            qdrant_timeout=settings.RAG_QDRANT_TIMEOUT,
            embed_model_name=settings.RAG_EMBED_MODEL_NAME,
            chunk_options=ChunkingOptions(
                max_chars=settings.RAG_CHUNK_MAX_CHARS,
                overlap_records=settings.RAG_CHUNK_OVERLAP_RECORDS,
                min_chunk_chars=settings.RAG_CHUNK_MIN_CHARS,
                split_long_record=settings.RAG_SPLIT_LONG_RECORD,
            ),
            top_k=settings.RAG_TOP_K,
            llm_enabled=settings.RAG_ENABLE_LLM,
            llm_provider=settings.RAG_LLM_PROVIDER,
            llm_model=settings.RAG_LLM_MODEL,
            llm_api_key=settings.RAG_LLM_API_KEY,
            llm_api_base=settings.RAG_LLM_API_BASE,
            llm_temperature=settings.RAG_LLM_TEMPERATURE,
            llm_max_tokens=settings.RAG_LLM_MAX_TOKENS,
            llm_timeout=settings.RAG_LLM_TIMEOUT,
        )


@dataclass(slots=True)
class RagRuntime:
    config: RagRuntimeConfig
    index_store: QdrantIndexStore
    embed_model: Any
    llm: Any | None
    indexing_service: RagIndexingService
    query_service: RagQueryService


_shared_runtime: RagRuntime | None = None
_shared_runtime_signature: tuple[object, ...] | None = None
_shared_runtime_lock = threading.RLock()


def build_rag_runtime(config: RagRuntimeConfig | None = None) -> RagRuntime:
    runtime_config = config or RagRuntimeConfig.from_settings()
    embed_model = build_default_embed_model(runtime_config.embed_model_name)
    vector_dim = _infer_embed_model_dim(embed_model)
    index_store = QdrantIndexStore(
        QdrantIndexStoreConfig(
            url=runtime_config.qdrant_url,
            collection_name=runtime_config.qdrant_collection,
            vector_dim=vector_dim,
            local_path=runtime_config.qdrant_local_path,
            prefer_local=runtime_config.qdrant_prefer_local,
            timeout=runtime_config.qdrant_timeout,
        )
    )
    llm = build_default_llm(runtime_config)
    indexing_service = RagIndexingService(
        index_store=index_store,
        chunk_options=runtime_config.chunk_options,
        transcript_root=runtime_config.transcript_root,
    )
    query_service = RagQueryService(index_store=index_store)
    return RagRuntime(
        config=runtime_config,
        index_store=index_store,
        embed_model=embed_model,
        llm=llm,
        indexing_service=indexing_service,
        query_service=query_service,
    )


def get_shared_rag_runtime(config: RagRuntimeConfig | None = None) -> RagRuntime:
    runtime_config = config or RagRuntimeConfig.from_settings()
    runtime_signature = _build_runtime_signature(runtime_config)

    global _shared_runtime, _shared_runtime_signature
    with _shared_runtime_lock:
        if _shared_runtime is not None and _shared_runtime_signature == runtime_signature:
            return _shared_runtime

        if _shared_runtime is not None:
            _shared_runtime.index_store.close()

        _shared_runtime = build_rag_runtime(runtime_config)
        _shared_runtime_signature = runtime_signature
        return _shared_runtime


def close_shared_rag_runtime() -> None:
    global _shared_runtime, _shared_runtime_signature

    with _shared_runtime_lock:
        runtime = _shared_runtime
        _shared_runtime = None
        _shared_runtime_signature = None

    if runtime is not None:
        runtime.index_store.close()


def build_default_llm(config: RagRuntimeConfig | None = None) -> Any | None:
    runtime_config = config or RagRuntimeConfig.from_settings()
    if not runtime_config.llm_enabled:
        return None

    provider = (runtime_config.llm_provider or "").strip().lower()
    if provider not in {"openai", "deepseek"}:
        raise ValueError(f"unsupported RAG_LLM_PROVIDER: {runtime_config.llm_provider}")
    if not runtime_config.llm_api_key:
        raise ValueError("RAG_LLM_API_KEY is required when RAG_ENABLE_LLM=true")

    try:
        from llama_index.llms.openai import OpenAI
    except ImportError as exc:
        raise ImportError(
            "llama-index-llms-openai is required for OpenAI-compatible LLM support."
        ) from exc

    if provider == "deepseek":
        _register_openai_compatible_models(
            models={
                "deepseek-chat": 64000,
                "deepseek-reasoner": 64000,
            }
        )

    kwargs: dict[str, Any] = {
        "model": runtime_config.llm_model,
        "temperature": runtime_config.llm_temperature,
        "api_key": runtime_config.llm_api_key,
        "timeout": runtime_config.llm_timeout,
    }
    if runtime_config.llm_api_base:
        kwargs["api_base"] = runtime_config.llm_api_base
    if runtime_config.llm_max_tokens is not None:
        kwargs["max_tokens"] = runtime_config.llm_max_tokens
    return OpenAI(**kwargs)


def _infer_embed_model_dim(embed_model: Any) -> int:
    getter = getattr(embed_model, "get_vector_dimension", None)
    if callable(getter):
        return int(getter())
    return int(settings.VECTOR_DIM)


def _build_runtime_signature(config: RagRuntimeConfig) -> tuple[object, ...]:
    chunk = config.chunk_options
    return (
        str(config.transcript_root),
        config.qdrant_url,
        config.qdrant_collection,
        config.qdrant_prefer_local,
        str(config.qdrant_local_path),
        config.qdrant_timeout,
        str(config.embed_model_name),
        chunk.max_chars,
        chunk.overlap_records,
        chunk.min_chunk_chars,
        chunk.split_long_record,
        chunk.separator,
        config.top_k,
        config.llm_enabled,
        config.llm_provider,
        config.llm_model,
        config.llm_api_base,
        config.llm_temperature,
        config.llm_max_tokens,
        config.llm_timeout,
    )


def _register_openai_compatible_models(models: dict[str, int]) -> None:
    try:
        from llama_index.llms.openai import utils as openai_utils
    except ImportError:
        return

    for model_name, context_window in models.items():
        openai_utils.ALL_AVAILABLE_MODELS.setdefault(model_name, context_window)
        openai_utils.CHAT_MODELS.setdefault(model_name, context_window)
