from __future__ import annotations

import json
from dataclasses import asdict

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from src.application.container import ApplicationServices
from src.core.asr.realtime_models import resolve_realtime_asr_model
from web.backend.app.dependencies import get_backend_services
from web.backend.app.execution import run_blocking
from web.backend.app.schemas import CreateSessionRequest

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.post("")
async def create_session(
    payload: CreateSessionRequest,
    services: ApplicationServices = Depends(get_backend_services),
):
    try:
        resolved_model_name = resolve_realtime_asr_model(payload.model_name)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    session = services.session_manager.create_session(
        course_id=payload.course_id,
        lesson_id=payload.lesson_id,
        subject=payload.subject,
        client_id=payload.client_id,
        sample_rate=payload.sample_rate,
        channels=payload.channels,
        model_name=resolved_model_name.key,
    )
    return {
        "session_id": session.session_id,
        "course_id": session.course_id,
        "lesson_id": session.lesson_id,
        "status": session.status.value,
        "subject": session.subject,
        "client_id": session.client_id,
        "sample_rate": session.sample_rate,
        "channels": session.channels,
        "model_name": session.model_name,
        "created_at": session.created_at,
    }


@router.get("")
async def list_sessions(services: ApplicationServices = Depends(get_backend_services)):
    sessions = services.session_manager.list_sessions()
    return {
        "items": [
            {
                "session_id": session.session_id,
                "course_id": session.course_id,
                "lesson_id": session.lesson_id,
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


@router.get("/{session_id}/transcripts")
async def get_session_transcripts(
    session_id: str,
    services: ApplicationServices = Depends(get_backend_services),
):
    session = services.session_manager.get_session(session_id)
    items = services.transcript.list_session_transcripts(session, session_id)
    return {
        "session_id": session_id,
        "count": len(items),
        "items": items,
    }


@router.get("/{session_id}/messages")
async def get_session_messages(
    session_id: str,
    services: ApplicationServices = Depends(get_backend_services),
):
    items = services.chat_memory.list_session_messages(session_id)
    return {
        "session_id": session_id,
        "count": len(items),
        "items": [asdict(item) for item in items],
    }


@router.post("/{session_id}/vision-frame")
async def upload_session_vision_frame(
    session_id: str,
    file: UploadFile = File(...),
    regions: str = Form(...),
    timestamp_ms: int | None = Form(default=None),
    captured_at_ms: int | None = Form(default=None),
    services: ApplicationServices = Depends(get_backend_services),
):
    session = services.session_manager.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"session not found: {session_id}")

    media_type = file.content_type or ""
    if media_type and not media_type.startswith("image/"):
        raise HTTPException(status_code=422, detail="vision frame must be an image")

    try:
        region_payload = json.loads(regions)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail="regions must be valid JSON") from exc
    if not isinstance(region_payload, dict):
        raise HTTPException(status_code=422, detail="regions must be a JSON object")

    try:
        image_bytes = await file.read()
        return await run_blocking(
            services.session_vision.process_frame,
            session=session,
            image_bytes=image_bytes,
            regions=region_payload,
            timestamp_ms=timestamp_ms,
            captured_at_ms=captured_at_ms,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        await file.close()
