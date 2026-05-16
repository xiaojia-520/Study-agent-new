from config.settings import settings
from src.application.rag.ingestion_service import KnowledgeIngestionService
from src.application.rag.runtime import get_shared_rag_runtime
from src.application.rag.realtime_indexer import realtime_rag_indexer
from src.application.transcripts.service import transcript_service


knowledge_ingestion_service = KnowledgeIngestionService(
    transcript_writer=transcript_service,
    realtime_indexer=realtime_rag_indexer,
    runtime_factory=get_shared_rag_runtime,
    rag_indexing_enabled=settings.RAG_REALTIME_INDEXING_ENABLED,
)
