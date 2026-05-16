from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config.settings import settings
from src.infrastructure.logger import get_logger
from web.backend.app.api.lesson_copilot import router as lesson_copilot_router
from web.backend.app.api.lesson_notes import router as lesson_note_router
from web.backend.app.api.http_sessions import router as session_router
from web.backend.app.api.ws_audio import router as ws_audio_router
from web.backend.app.dependencies import shutdown_backend_runtime, startup_backend_runtime

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
    await startup_backend_runtime(logger)


@app.on_event("shutdown")
async def shutdown_runtime():
    await shutdown_backend_runtime(logger)


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
