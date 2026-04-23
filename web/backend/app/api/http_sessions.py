from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from config.settings import settings
from src.core.asr.realtime_models import resolve_realtime_asr_model
from web.backend.app.services.chat_memory_service import chat_memory_service
from web.backend.app.services.lesson_asset_service import lesson_asset_service, validate_asset_file_name
from web.backend.app.services.session_lesson_quiz_service import session_lesson_quiz_service
from web.backend.app.services.session_lesson_summary_service import session_lesson_summary_service
from web.backend.app.services.session_rag_query_service import QueryScope, session_rag_query_service
from web.backend.app.services.session_manager import session_manager
from web.backend.app.services.session_transcript_refine_service import session_transcript_refine_service
from web.backend.app.services.session_video_service import session_video_service, validate_video_file_name
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


@router.get("/history/refined-transcripts")
async def get_lesson_refined_transcripts(
    course_id: str = Query(..., min_length=1),
    lesson_id: str = Query(..., min_length=1),
):
    items = session_transcript_refine_service.list_lesson_refined_transcripts(
        course_id=course_id,
        lesson_id=lesson_id,
    )
    return {
        "course_id": course_id,
        "lesson_id": lesson_id,
        "count": len(items),
        "items": [asdict(item) for item in items],
    }


@router.get("/history/videos")
async def get_lesson_videos(
    course_id: str = Query(..., min_length=1),
    lesson_id: str = Query(..., min_length=1),
):
    items = session_video_service.list_lesson_videos(course_id=course_id, lesson_id=lesson_id)
    return {
        "course_id": course_id,
        "lesson_id": lesson_id,
        "count": len(items),
        "items": [_video_response_item(item) for item in items],
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


@router.post("/{session_id}/assets")
async def upload_session_asset(
    session_id: str,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
):
    session = session_manager.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"session not found: {session_id}")

    file_name = file.filename or "document"
    try:
        validate_asset_file_name(file_name)
        asset_id, safe_name, target_path = lesson_asset_service.allocate_upload_path(
            session_id=session_id,
            file_name=file_name,
        )
        file_size = 0
        with target_path.open("wb") as handle:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                file_size += len(chunk)
                handle.write(chunk)
        asset = lesson_asset_service.create_asset(
            asset_id=asset_id,
            session=session,
            file_name=safe_name,
            file_path=target_path,
            file_size=file_size,
            media_type=file.content_type or "application/octet-stream",
            metadata={"original_file_name": file_name},
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        await file.close()

    background_tasks.add_task(lesson_asset_service.parse_and_index_asset, asset.asset_id)
    return {"item": lesson_asset_service.to_dict(asset)}


@router.get("/{session_id}/assets")
async def list_session_assets(session_id: str):
    session = session_manager.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"session not found: {session_id}")

    items = lesson_asset_service.list_session_assets(session_id)
    return {
        "session_id": session_id,
        "count": len(items),
        "items": [lesson_asset_service.to_dict(item) for item in items],
    }


@router.get("/assets/{asset_id}")
async def get_lesson_asset(asset_id: str):
    asset = lesson_asset_service.get_asset(asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail=f"asset not found: {asset_id}")
    return {"item": lesson_asset_service.to_dict(asset)}


@router.post("/{session_id}/videos")
async def upload_session_video(
    session_id: str,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
):
    session = session_manager.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"session not found: {session_id}")

    target_path: Path | None = None
    file_name = file.filename or "recording.webm"
    try:
        validate_video_file_name(file_name)
        video_id, safe_name, target_path = session_video_service.allocate_upload_path(
            session_id=session_id,
            file_name=file_name,
        )
        file_size = 0
        with target_path.open("wb") as handle:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                file_size += len(chunk)
                if file_size > settings.VIDEO_MAX_UPLOAD_BYTES:
                    raise ValueError("uploaded video exceeds size limit")
                handle.write(chunk)
        video = session_video_service.create_video(
            video_id=video_id,
            session=session,
            file_name=safe_name,
            file_path=target_path,
            file_size=file_size,
            media_type=file.content_type or "application/octet-stream",
            metadata={"original_file_name": file_name},
        )
    except ValueError as exc:
        if target_path is not None:
            target_path.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        await file.close()

    background_tasks.add_task(session_video_service.process_video, video.video_id)
    return {"item": _video_response_item(video)}


@router.get("/{session_id}/videos")
async def list_session_videos(session_id: str):
    session = session_manager.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"session not found: {session_id}")

    items = session_video_service.list_session_videos(session_id)
    return {
        "session_id": session_id,
        "count": len(items),
        "items": [_video_response_item(item) for item in items],
    }


@router.get("/videos/{video_id}")
async def get_session_video(video_id: str):
    video = session_video_service.get_video(video_id)
    if video is None:
        raise HTTPException(status_code=404, detail=f"video not found: {video_id}")
    return {"item": _video_response_item(video)}


@router.get("/videos/{video_id}/file")
async def download_session_video_file(video_id: str):
    video = session_video_service.get_video(video_id)
    if video is None:
        raise HTTPException(status_code=404, detail=f"video not found: {video_id}")

    file_path = Path(video.file_path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="video file not found")
    return FileResponse(file_path, media_type=video.media_type, filename=video.file_name)


@router.get("/videos/{video_id}/srt")
async def download_session_video_srt(video_id: str):
    video = session_video_service.get_video(video_id)
    if video is None:
        raise HTTPException(status_code=404, detail=f"video not found: {video_id}")
    if video.status != "done" or not video.srt_path:
        raise HTTPException(status_code=404, detail="subtitle is not ready")

    srt_path = Path(video.srt_path)
    if not srt_path.exists():
        raise HTTPException(status_code=404, detail="subtitle file not found")
    return FileResponse(srt_path, media_type="application/x-subrip", filename=f"{video.video_id}.srt")


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


def _video_response_item(video):
    item = session_video_service.to_dict(video)
    item["video_url"] = f"/sessions/videos/{video.video_id}/file"
    item["srt_url"] = f"/sessions/videos/{video.video_id}/srt" if video.srt_path else None
    return item
