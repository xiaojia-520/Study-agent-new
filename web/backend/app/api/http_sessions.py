from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.core.asr.realtime_models import resolve_realtime_asr_model
from web.backend.app.services.session_manager import session_manager

router = APIRouter(prefix="/sessions", tags=["sessions"])


class CreateSessionRequest(BaseModel):
    subject: Optional[str] = None
    client_id: Optional[str] = None
    sample_rate: int = 16000
    channels: int = 1
    model_name: Optional[str] = None


@router.post("")
async def create_session(payload: CreateSessionRequest):
    try:
        resolved_model_name = resolve_realtime_asr_model(payload.model_name)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    session = session_manager.create_session(
        subject=payload.subject,
        client_id=payload.client_id,
        sample_rate=payload.sample_rate,
        channels=payload.channels,
        model_name=resolved_model_name.key,
    )
    return {
        "session_id": session.session_id,
        "status": session.status.value,
        "subject": session.subject,
        "client_id": session.client_id,
        "sample_rate": session.sample_rate,
        "channels": session.channels,
        "model_name": session.model_name,
        "created_at": session.created_at,
    }


@router.get("")
async def list_sessions():
    sessions = session_manager.list_sessions()
    return {
        "items": [
            {
                "session_id": session.session_id,
                "status": session.status.value,
                "subject": session.subject,
                "client_id": session.client_id,
                "sample_rate": session.sample_rate,
                "channels": session.channels,
                "model_name": session.model_name,
                "active_connections": session.active_connections,
                "created_at": session.created_at,
                "updated_at": session.updated_at,
                "last_error": session.last_error,
            }
            for session in sessions
        ]
    }
