from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, Query

from src.application.container import ApplicationServices
from web.backend.app.dependencies import get_backend_services
from web.backend.app.presenters import video_response_item

router = APIRouter(prefix="/sessions", tags=["history"])


@router.get("/history")
async def list_lesson_history(
    limit: int = Query(default=50, ge=1, le=200),
    services: ApplicationServices = Depends(get_backend_services),
):
    items = services.chat_memory.list_lesson_summaries(limit=limit)
    return {
        "count": len(items),
        "items": [asdict(item) for item in items],
    }


@router.delete("/history/lesson")
async def delete_lesson_history(
    course_id: str = Query(..., min_length=1),
    lesson_id: str = Query(..., min_length=1),
    services: ApplicationServices = Depends(get_backend_services),
):
    try:
        return services.lesson_history.delete_lesson(course_id=course_id, lesson_id=lesson_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/history/messages")
async def get_lesson_messages(
    course_id: str = Query(..., min_length=1),
    lesson_id: str = Query(..., min_length=1),
    limit: int | None = Query(default=None, ge=1, le=500),
    services: ApplicationServices = Depends(get_backend_services),
):
    items = services.chat_memory.list_lesson_messages(
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
    services: ApplicationServices = Depends(get_backend_services),
):
    items = services.transcript.list_lesson_transcripts(course_id=course_id, lesson_id=lesson_id)
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
    services: ApplicationServices = Depends(get_backend_services),
):
    items = services.transcript_refine.list_lesson_refined_transcripts(
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
    services: ApplicationServices = Depends(get_backend_services),
):
    items = services.session_video.list_lesson_videos(course_id=course_id, lesson_id=lesson_id)
    return {
        "course_id": course_id,
        "lesson_id": lesson_id,
        "count": len(items),
        "items": [video_response_item(item) for item in items],
    }
