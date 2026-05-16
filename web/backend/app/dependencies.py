from __future__ import annotations

from typing import Callable

from config.settings import settings
from src.application.container import ApplicationServices, get_application_services
from src.core.asr.realtime_models import resolve_realtime_asr_model
from src.infrastructure.model_hub import model_hub
from src.infrastructure.storage.runtime import close_database_store
from web.backend.app.tasks import background_task_queue


def get_backend_services() -> ApplicationServices:
    return get_application_services()


async def startup_backend_runtime(logger) -> None:
    services = get_backend_services()
    logger.info("Backend startup: initializing database storage")
    services.chat_memory.init_schema()
    services.transcript.init_schema()
    services.lesson_asset.init_schema()
    services.session_video.init_schema()
    services.lesson_note_repository.init_schema()
    services.session_manager.ping()
    background_task_queue.start()
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


async def shutdown_backend_runtime(logger) -> None:
    services = get_backend_services()
    _close_all(
        services.realtime_rag_indexer.close,
        services.lesson_copilot.close,
        services.lesson_quiz.close,
        services.session_rag_query.close,
        services.lesson_summary.close,
        services.transcript_refine.close,
        services.lesson_note.close,
        background_task_queue.close,
        close_database_store,
    )
    logger.info("Backend runtime stopped")


def _close_all(*closers: Callable[[], None]) -> None:
    for close in closers:
        close()
