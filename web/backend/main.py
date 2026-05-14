from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config.settings import settings
from src.core.asr.realtime_models import resolve_realtime_asr_model
from src.infrastructure.logger import get_logger
from src.infrastructure.model_hub import model_hub
from web.backend.app.api.lesson_copilot import router as lesson_copilot_router
from web.backend.app.api.lesson_notes import router as lesson_note_router
from web.backend.app.api.http_sessions import router as session_router
from web.backend.app.api.ws_audio import router as ws_audio_router
from web.backend.app.services.chat_memory_service import chat_memory_service
from web.backend.app.services.lesson_asset_service import lesson_asset_service
from web.backend.app.services.lesson_copilot_service import lesson_copilot_service
from web.backend.app.services.lesson_note_service import lesson_note_repository, lesson_note_service
from web.backend.app.services.session_lesson_quiz_service import session_lesson_quiz_service
from web.backend.app.services.realtime_rag_indexer import realtime_rag_indexer
from web.backend.app.services.session_lesson_summary_service import session_lesson_summary_service
from web.backend.app.services.session_rag_query_service import session_rag_query_service
from web.backend.app.services.session_transcript_refine_service import session_transcript_refine_service
from web.backend.app.services.session_video_service import session_video_service
from web.backend.app.services.transcript_service import transcript_service
from src.application.runtime.session_manager import session_manager

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
app.include_router(lesson_note_router)
app.include_router(lesson_copilot_router)


@app.on_event("startup")
async def warmup_models():
    logger.info("Backend startup: initializing SQLite storage")
    chat_memory_service.init_schema()
    transcript_service.init_schema()
    lesson_asset_service.init_schema()
    session_video_service.init_schema()
    lesson_note_repository.init_schema()
    session_manager.ping()
    logger.info("Backend startup: session backend is ready")
    warmup_model = resolve_realtime_asr_model(settings.ASR_DEFAULT_MODEL_KEY)
    logger.info("Backend startup warmup: loading ASR model %s", warmup_model.key)
    model_hub.load_asr_model(model_name=warmup_model.resolved_model_name)
    if settings.ASR_WARMUP_OFFLINE_MODEL:
        logger.info("Backend startup warmup: loading FunASR offline model")
        model_hub.load_funasr_model()
    else:
        logger.info("Backend startup warmup: skipping FunASR offline model")
    logger.info("Backend startup warmup complete")


@app.on_event("shutdown")
async def shutdown_runtime():
    realtime_rag_indexer.close()
    lesson_copilot_service.close()
    session_lesson_quiz_service.close()
    session_rag_query_service.close()
    session_lesson_summary_service.close()
    session_transcript_refine_service.close()
    lesson_note_service.close()
    logger.info("Realtime RAG indexer stopped")


@app.get("/")
async def root():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "web.backend.main:app",
        host=settings.WEB_HOST,
        port=settings.WEB_PORT,
        reload=True,
    )
