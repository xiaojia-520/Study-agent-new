from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from web.backend.app.api.http_sessions import router as session_router
from web.backend.app.api.ws_audio import router as ws_audio_router

app = FastAPI(title="Study Agent Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(session_router)
app.include_router(ws_audio_router)


@app.get("/")
async def root():
    return {"status": "ok"}
