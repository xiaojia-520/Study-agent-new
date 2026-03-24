from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from config.settings import settings


@dataclass(slots=True)
class QdrantIndexStoreConfig:
    url: str = settings.QDRANT_URL
    collection_name: str = settings.RAG_QDRANT_COLLECTION
    vector_dim: int = settings.VECTOR_DIM
    create_if_not_exist: bool = settings.QDRANT_CREATE_IF_NOT_EXIST
    local_path: Path = settings.RAG_QDRANT_LOCAL_PATH
    prefer_local: bool = settings.RAG_QDRANT_PREFER_LOCAL
    timeout: int = settings.RAG_QDRANT_TIMEOUT


class QdrantIndexStore:
    def __init__(
        self,
        config: QdrantIndexStoreConfig | None = None,
        *,
        client: Any = None,
    ) -> None:
        self.config = config or QdrantIndexStoreConfig()
        self._client = client

    def get_client(self) -> Any:
        if self._client is None:
            qdrant_client_cls, _, _ = self._load_qdrant_modules()
            if self.config.prefer_local:
                self.config.local_path.mkdir(parents=True, exist_ok=True)
                self._client = qdrant_client_cls(
                    path=str(self.config.local_path),
                    check_compatibility=False,
                )
            else:
                self._client = qdrant_client_cls(
                    url=self.config.url,
                    timeout=self.config.timeout,
                    check_compatibility=False,
                )
        return self._client

    def ensure_collection(
        self,
        *,
        vector_dim: int | None = None,
        recreate_if_mismatch: bool = False,
    ) -> Any:
        client = self.get_client()
        _, distance_cls, vector_params_cls = self._load_qdrant_modules()
        resolved_dim = int(vector_dim or self.config.vector_dim)

        if client.collection_exists(collection_name=self.config.collection_name):
            actual_dim = self._get_collection_vector_dim(client)
            if actual_dim is not None and actual_dim != resolved_dim:
                if not recreate_if_mismatch:
                    raise ValueError(
                        f"collection {self.config.collection_name} dimension mismatch: "
                        f"expected {resolved_dim}, got {actual_dim}"
                    )
                client.delete_collection(collection_name=self.config.collection_name)
            else:
                return client

        if not client.collection_exists(collection_name=self.config.collection_name):
            if not self.config.create_if_not_exist:
                raise ValueError(f"collection {self.config.collection_name} does not exist")

            client.create_collection(
                collection_name=self.config.collection_name,
                vectors_config=vector_params_cls(
                    size=resolved_dim,
                    distance=distance_cls.COSINE,
                ),
            )
            return client
        return client

    def build_vector_store(
        self,
        *,
        vector_dim: int | None = None,
        recreate_if_mismatch: bool = False,
    ) -> Any:
        _, _, _, qdrant_vector_store_cls = self._load_llamaindex_modules()
        self.ensure_collection(vector_dim=vector_dim, recreate_if_mismatch=recreate_if_mismatch)
        return qdrant_vector_store_cls(
            client=self.get_client(),
            collection_name=self.config.collection_name,
        )

    def build_storage_context(
        self,
        *,
        vector_dim: int | None = None,
        recreate_if_mismatch: bool = False,
    ) -> Any:
        storage_context_cls, _, _, _ = self._load_llamaindex_modules()
        return storage_context_cls.from_defaults(
            vector_store=self.build_vector_store(
                vector_dim=vector_dim,
                recreate_if_mismatch=recreate_if_mismatch,
            )
        )

    def create_index(
        self,
        documents: Sequence[Any],
        *,
        embed_model: Any = None,
        transformations: Sequence[Any] | None = None,
        show_progress: bool = False,
        recreate_if_mismatch: bool = False,
    ) -> Any:
        _, vector_store_index_cls, _, _ = self._load_llamaindex_modules()
        vector_dim = self._infer_vector_dim(embed_model)
        kwargs: dict[str, Any] = {
            "storage_context": self.build_storage_context(
                vector_dim=vector_dim,
                recreate_if_mismatch=recreate_if_mismatch,
            ),
            "show_progress": show_progress,
        }
        if embed_model is not None:
            kwargs["embed_model"] = embed_model
        if transformations is not None:
            kwargs["transformations"] = list(transformations)
        return vector_store_index_cls.from_documents(list(documents), **kwargs)

    def load_index(self, *, embed_model: Any = None) -> Any:
        _, vector_store_index_cls, _, _ = self._load_llamaindex_modules()
        kwargs: dict[str, Any] = {"vector_store": self.build_vector_store()}
        if embed_model is not None:
            kwargs["embed_model"] = embed_model
        return vector_store_index_cls.from_vector_store(**kwargs)

    def as_retriever(
        self,
        *,
        top_k: int = 5,
        embed_model: Any = None,
        filters: Any = None,
    ) -> Any:
        index = self.load_index(embed_model=embed_model)
        kwargs: dict[str, Any] = {"similarity_top_k": top_k}
        if filters is not None:
            kwargs["filters"] = filters
        return index.as_retriever(**kwargs)

    def as_query_engine(
        self,
        *,
        top_k: int = 5,
        embed_model: Any = None,
        llm: Any = None,
        filters: Any = None,
    ) -> Any:
        index = self.load_index(embed_model=embed_model)
        kwargs: dict[str, Any] = {"similarity_top_k": top_k}
        if llm is not None:
            kwargs["llm"] = llm
        if filters is not None:
            kwargs["filters"] = filters
        return index.as_query_engine(**kwargs)

    def reset_collection(self) -> None:
        client = self.get_client()
        if client.collection_exists(collection_name=self.config.collection_name):
            client.delete_collection(collection_name=self.config.collection_name)

    def close(self) -> None:
        client = self._client
        if client is None:
            return
        close = getattr(client, "close", None)
        if callable(close):
            close()
        self._client = None

    @staticmethod
    def _load_qdrant_modules() -> tuple[type[Any], type[Any], type[Any]]:
        try:
            from qdrant_client import QdrantClient
            from qdrant_client.http.models import Distance, VectorParams
        except ImportError as exc:
            raise ImportError(
                "qdrant-client is required for QdrantIndexStore. Install qdrant-client."
            ) from exc
        return QdrantClient, Distance, VectorParams

    @staticmethod
    def _load_llamaindex_modules() -> tuple[type[Any], type[Any], Any, type[Any]]:
        try:
            from llama_index.core import StorageContext, VectorStoreIndex
            from llama_index.vector_stores.qdrant import QdrantVectorStore
        except ImportError as exc:
            raise ImportError(
                "llama-index core and qdrant vector store support are required. "
                "Install llama-index-core and llama-index-vector-stores-qdrant."
            ) from exc
        return StorageContext, VectorStoreIndex, None, QdrantVectorStore

    def _get_collection_vector_dim(self, client: Any) -> int | None:
        collection_info = client.get_collection(collection_name=self.config.collection_name)
        vectors = collection_info.config.params.vectors
        if hasattr(vectors, "size"):
            return int(vectors.size)
        if isinstance(vectors, dict):
            first_value = next(iter(vectors.values()), None)
            if first_value is not None and hasattr(first_value, "size"):
                return int(first_value.size)
        return None

    def _infer_vector_dim(self, embed_model: Any) -> int:
        if embed_model is not None:
            getter = getattr(embed_model, "get_vector_dimension", None)
            if callable(getter):
                return int(getter())
            model_name = getattr(embed_model, "model_name", None)
            if model_name:
                try:
                    from sentence_transformers import SentenceTransformer
                except ImportError:
                    pass
                else:
                    model = SentenceTransformer(str(model_name))
                    dimension = model.get_sentence_embedding_dimension()
                    if dimension is not None:
                        return int(dimension)
        return int(self.config.vector_dim)
