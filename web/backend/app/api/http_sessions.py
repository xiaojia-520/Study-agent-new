from __future__ import annotations

from fastapi import APIRouter

from web.backend.app.api.assets import router as assets_router
from web.backend.app.api.history import router as history_router
from web.backend.app.api.learning import router as learning_router
from web.backend.app.api.sessions import router as sessions_router
from web.backend.app.api.videos import router as videos_router

router = APIRouter()
# Register static history routes before dynamic session_id routes so
# `/sessions/history/*` is not swallowed by `/sessions/{session_id}/*`.
router.include_router(history_router)
router.include_router(sessions_router)
router.include_router(assets_router)
router.include_router(videos_router)
router.include_router(learning_router)
