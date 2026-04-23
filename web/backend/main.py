from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.infrastructure.logger import get_logger
from src.infrastructure.model_hub import model_hub
from web.backend.app.api.http_sessions import router as session_router
from web.backend.app.api.ws_audio import router as ws_audio_router
from web.backend.app.services.chat_memory_service import chat_memory_service
from web.backend.app.services.lesson_asset_service import lesson_asset_service
from web.backend.app.services.session_lesson_quiz_service import session_lesson_quiz_service
from web.backend.app.services.realtime_rag_indexer import realtime_rag_indexer
from web.backend.app.services.session_lesson_summary_service import session_lesson_summary_service
from web.backend.app.services.session_rag_query_service import session_rag_query_service
from web.backend.app.services.session_transcript_refine_service import session_transcript_refine_service
from web.backend.app.services.session_video_service import session_video_service

app = FastAPI(title="Study Agent Backend")
logger = get_logger("WebBackend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(session_router)
app.include_router(ws_audio_router)


@app.on_event("startup")
async def warmup_models():
    logger.info("Backend startup: initializing SQLite storage")
    chat_memory_service.init_schema()
    lesson_asset_service.init_schema()
    session_video_service.init_schema()
    logger.info("Backend startup warmup: loading ASR model")
    model_hub.load_asr_model()
    logger.info("Backend startup warmup: loading FunASR offline model")
    model_hub.load_funasr_model()
    logger.info("Backend startup warmup complete")


@app.on_event("shutdown")
async def shutdown_runtime():
    realtime_rag_indexer.close()
    session_lesson_quiz_service.close()
    session_rag_query_service.close()
    session_lesson_summary_service.close()
    session_transcript_refine_service.close()
    logger.info("Realtime RAG indexer stopped")


@app.get("/")
async def root():
    return {"status": "ok"}
