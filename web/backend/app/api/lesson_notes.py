from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from src.application.container import ApplicationServices
from web.backend.app.dependencies import get_backend_services
from web.backend.app.presenters import lesson_note_to_dict
from web.backend.app.schemas import LessonNoteGenerateRequest
from web.backend.app.tasks import BackgroundTaskRunner

router = APIRouter(prefix="/lessons", tags=["lesson-notes"])


@router.get("/notes/{note_id}")
async def get_lesson_note(
    note_id: str,
    services: ApplicationServices = Depends(get_backend_services),
):
    note = services.lesson_note.get_note(note_id)
    if note is None:
        raise HTTPException(status_code=404, detail=f"lesson note not found: {note_id}")
    return {"item": lesson_note_to_dict(note)}


@router.get("/{course_id}/{lesson_id}/notes/latest")
async def get_latest_lesson_note(
    course_id: str,
    lesson_id: str,
    services: ApplicationServices = Depends(get_backend_services),
):
    note = services.lesson_note.get_latest_note(course_id=course_id, lesson_id=lesson_id)
    if note is None:
        raise HTTPException(
            status_code=404,
            detail=f"lesson note not found: {course_id}/{lesson_id}",
        )
    return {"item": lesson_note_to_dict(note)}


@router.post("/{course_id}/{lesson_id}/notes/generate")
async def generate_lesson_note(
    course_id: str,
    lesson_id: str,
    payload: LessonNoteGenerateRequest | None = None,
    services: ApplicationServices = Depends(get_backend_services),
):
    payload = payload or LessonNoteGenerateRequest()
    try:
        plan = services.lesson_note.request_generation(
            course_id=course_id,
            lesson_id=lesson_id,
            session_id=payload.session_id,
            focus=payload.focus,
            max_items=payload.max_items,
            force=payload.force,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"lesson transcript not found: {course_id}/{lesson_id}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if plan.should_generate:
        BackgroundTaskRunner().enqueue(
            services.lesson_note.generate_pending_note,
            plan.note.note_id,
            focus=payload.focus,
            max_items=payload.max_items,
            raise_errors=False,
        )
    return {
        "item": lesson_note_to_dict(plan.note),
        "queued": plan.should_generate,
    }
