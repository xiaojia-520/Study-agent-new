from __future__ import annotations

from dataclasses import asdict
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from src.core.asr.realtime_models import resolve_realtime_asr_model
from web.backend.app.services.chat_memory_service import chat_memory_service
from web.backend.app.services.session_lesson_quiz_service import session_lesson_quiz_service
from web.backend.app.services.session_lesson_summary_service import session_lesson_summary_service
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


class SessionSummaryRequest(BaseModel):
    focus: Optional[str] = None
    max_items: Optional[int] = None


class SessionQuizRequest(BaseModel):
    focus: Optional[str] = None
    question_count: Optional[int] = None


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


@router.get("/history")
async def list_lesson_history(limit: int = Query(default=50, ge=1, le=200)):
    items = chat_memory_service.list_lesson_summaries(limit=limit)
    return {
        "count": len(items),
        "items": [asdict(item) for item in items],
    }


@router.get("/history/messages")
async def get_lesson_messages(
    course_id: str = Query(..., min_length=1),
    lesson_id: str = Query(..., min_length=1),
    limit: int | None = Query(default=None, ge=1, le=500),
):
    items = chat_memory_service.list_lesson_messages(
        course_id=course_id,
        lesson_id=lesson_id,
        limit=limit,
    )
    return {
        "course_id": course_id,
        "lesson_id": lesson_id,
        "count": len(items),
        "items": [asdict(item) for item in items],
    }


@router.get("/history/transcripts")
async def get_lesson_transcripts(
    course_id: str = Query(..., min_length=1),
    lesson_id: str = Query(..., min_length=1),
):
    items = transcript_service.list_lesson_transcripts(course_id=course_id, lesson_id=lesson_id)
    return {
        "course_id": course_id,
        "lesson_id": lesson_id,
        "count": len(items),
        "items": items,
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


@router.get("/{session_id}/messages")
async def get_session_messages(session_id: str):
    items = chat_memory_service.list_session_messages(session_id)
    return {
        "session_id": session_id,
        "count": len(items),
        "items": [asdict(item) for item in items],
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
        "citations": [asdict(citation) for citation in answer.citations],
        "metadata": metadata,
        "scope": metadata.get("scope"),
        "session_id": metadata.get("session_id"),
        "course_id": metadata.get("course_id"),
        "lesson_id": metadata.get("lesson_id"),
    }


@router.post("/{session_id}/summary")
async def summarize_session(session_id: str, payload: SessionSummaryRequest):
    try:
        summary = session_lesson_summary_service.generate_summary(
            session_id=session_id,
            focus=payload.focus,
            max_items=payload.max_items,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"session transcript not found: {session_id}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ImportError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return {
        "session_id": summary.session_id,
        "course_id": summary.course_id,
        "lesson_id": summary.lesson_id,
        "subject": summary.subject,
        "summary": summary.summary,
        "key_points": list(summary.key_points),
        "review_items": list(summary.review_items),
        "important_terms": [asdict(item) for item in summary.important_terms],
        "metadata": dict(summary.metadata),
    }


@router.post("/{session_id}/quiz")
async def generate_session_quiz(session_id: str, payload: SessionQuizRequest):
    try:
        quiz = session_lesson_quiz_service.generate_quiz(
            session_id=session_id,
            focus=payload.focus,
            question_count=payload.question_count,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"session transcript not found: {session_id}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ImportError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return {
        "session_id": quiz.session_id,
        "course_id": quiz.course_id,
        "lesson_id": quiz.lesson_id,
        "subject": quiz.subject,
        "questions": [asdict(item) for item in quiz.questions],
        "metadata": dict(quiz.metadata),
    }
