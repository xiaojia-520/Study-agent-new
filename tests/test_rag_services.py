import unittest

from src.application.rag.indexing_service import RagIndexingService
from src.application.rag.query_service import RagQueryService
from src.core.knowledge.document_models import ChunkingOptions, TranscriptRecord
from src.core.knowledge.llamaindex_builder import build_llama_documents


class FakeDocument:
    def __init__(self, *, text, doc_id, metadata):
        self.text = text
        self.doc_id = doc_id
        self.metadata = metadata


class FakeNode:
    def __init__(self, text, metadata, *, doc_id=""):
        self.text = text
        self.metadata = metadata
        self.doc_id = doc_id or metadata.get("doc_id", "")

    def get_text(self):
        return self.text


class FakeNodeWithScore:
    def __init__(self, node, score):
        self.node = node
        self.score = score


class FakeRetriever:
    def __init__(self, results):
        self.results = results
        self.queries = []

    def retrieve(self, query):
        self.queries.append(query)
        return list(self.results)


class FakeQueryEngine:
    def __init__(self, response):
        self.response = response
        self.queries = []

    def query(self, query):
        self.queries.append(query)
        return self.response


class FakeResponse:
    def __init__(self, response, source_nodes, metadata=None):
        self.response = response
        self.source_nodes = source_nodes
        self.metadata = metadata or {}


class FakeIndexStore:
    def __init__(self):
        self.created_documents = None
        self.create_index_calls = []
        self.retriever = None
        self.query_engine = None

    def create_index(self, documents, **kwargs):
        self.created_documents = list(documents)
        self.create_index_calls.append(kwargs)
        return {"index": "fake", "document_count": len(documents)}

    def as_retriever(self, **kwargs):
        self.last_retriever_kwargs = kwargs
        return self.retriever

    def as_query_engine(self, **kwargs):
        self.last_query_engine_kwargs = kwargs
        return self.query_engine


class RagServicesTests(unittest.TestCase):
    def test_build_llama_documents_with_custom_document_class(self) -> None:
        record = self._record(chunk_id=1, text="content")
        chunks = RagIndexingService(
            index_store=FakeIndexStore(),
            chunk_options=ChunkingOptions(max_chars=100, overlap_records=0, min_chunk_chars=1),
            document_builder=lambda chunks: build_llama_documents(chunks, document_cls=FakeDocument),
        ).build_chunks([record])

        documents = build_llama_documents(chunks, document_cls=FakeDocument)

        self.assertEqual(len(documents), 1)
        self.assertEqual(documents[0].text, "content")
        self.assertEqual(documents[0].doc_id, "session-a:1-1:0")
        self.assertEqual(documents[0].metadata["session_id"], "session-a")

    def test_rag_indexing_service_indexes_records(self) -> None:
        index_store = FakeIndexStore()
        service = RagIndexingService(
            index_store=index_store,
            chunk_options=ChunkingOptions(max_chars=100, overlap_records=0, min_chunk_chars=1),
            document_builder=lambda chunks: build_llama_documents(chunks, document_cls=FakeDocument),
        )

        summary = service.index_records(
            [
                self._record(chunk_id=1, text="alpha"),
                self._record(chunk_id=2, text="beta"),
            ]
        )

        self.assertEqual(summary.record_count, 2)
        self.assertEqual(summary.chunk_count, 1)
        self.assertEqual(summary.document_count, 1)
        self.assertEqual(summary.session_ids, ("session-a",))
        self.assertEqual(index_store.created_documents[0].text, "alpha\nbeta")

    def test_rag_query_service_search_maps_results(self) -> None:
        index_store = FakeIndexStore()
        index_store.retriever = FakeRetriever(
            [
                FakeNodeWithScore(
                    FakeNode(
                        "retrieved text",
                        {
                            "doc_id": "doc-1",
                            "session_id": "session-a",
                            "subject": "math",
                            "source_type": "realtime",
                        },
                    ),
                    0.91,
                )
            ]
        )
        service = RagQueryService(index_store=index_store)

        results = service.search("  what is this  ", top_k=3)

        self.assertEqual(index_store.last_retriever_kwargs["top_k"], 3)
        self.assertEqual(results[0].doc_id, "doc-1")
        self.assertEqual(results[0].content, "retrieved text")
        self.assertAlmostEqual(results[0].score, 0.91)
        self.assertEqual(results[0].session_id, "session-a")

    def test_rag_query_service_query_with_llm_extracts_answer_and_sources(self) -> None:
        index_store = FakeIndexStore()
        index_store.query_engine = FakeQueryEngine(
            FakeResponse(
                response="This is the answer",
                source_nodes=[
                    FakeNodeWithScore(
                        FakeNode(
                            "source text",
                            {
                                "doc_id": "doc-9",
                                "session_id": "session-b",
                            },
                        ),
                        0.77,
                    )
                ],
                metadata={"mode": "rag"},
            )
        )
        service = RagQueryService(index_store=index_store)

        result = service.query("question", llm=object(), top_k=4)

        self.assertEqual(index_store.last_query_engine_kwargs["top_k"], 4)
        self.assertEqual(result.answer, "This is the answer")
        self.assertEqual(result.results[0].doc_id, "doc-9")
        self.assertEqual(result.metadata["mode"], "rag")

    def _record(self, *, chunk_id: int, text: str) -> TranscriptRecord:
        return TranscriptRecord(
            session_id="session-a",
            chunk_id=chunk_id,
            subject="math",
            source_type="realtime",
            text=text,
            clean_text=text,
            created_at=100 + chunk_id,
        )


if __name__ == "__main__":
    unittest.main()
