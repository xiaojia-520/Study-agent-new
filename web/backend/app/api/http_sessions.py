from __future__ import annotations

from dataclasses import asdict
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.core.asr.realtime_models import resolve_realtime_asr_model
from web.backend.app.services.session_rag_query_service import QueryScope, session_rag_query_service
from web.backend.app.services.session_manager import session_manager
from web.backend.app.services.transcript_service import transcript_service

router = APIRouter(prefix="/sessions", tags=["sessions"])


class CreateSessionRequest(BaseModel):
    course_id: Optional[str] = None
    lesson_id: Optional[str] = None
    subject: Optional[str] = None
    client_id: Optional[str] = None
    sample_rate: int = 16000
    channels: int = 1
    model_name: Optional[str] = None


class SessionQueryRequest(BaseModel):
    query: str
    scope: QueryScope = QueryScope.AUTO
    top_k: Optional[int] = None
    with_llm: bool = False


@router.post("")
async def create_session(payload: CreateSessionRequest):
    try:
        resolved_model_name = resolve_realtime_asr_model(payload.model_name)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    session = session_manager.create_session(
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
async def list_sessions():
    sessions = session_manager.list_sessions()
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
async def get_session_transcripts(session_id: str):
    session = session_manager.get_session(session_id)
    items = transcript_service.list_session_transcripts(session, session_id)
    return {
        "session_id": session_id,
        "count": len(items),
        "items": items,
    }


@router.post("/{session_id}/query")
async def query_session(session_id: str, payload: SessionQueryRequest):
    try:
        answer = session_rag_query_service.query_session(
            session_id=session_id,
            query_text=payload.query,
            scope=payload.scope,
            top_k=payload.top_k,
            with_llm=payload.with_llm,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"session not found: {session_id}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ImportError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    metadata = dict(answer.metadata)
    return {
        "query": answer.query,
        "answer": answer.answer,
        "results": [asdict(result) for result in answer.results],
        "metadata": metadata,
        "scope": metadata.get("scope"),
        "session_id": metadata.get("session_id"),
        "course_id": metadata.get("course_id"),
        "lesson_id": metadata.get("lesson_id"),
    }
