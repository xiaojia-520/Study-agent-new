from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from web.backend.app.services.lesson_note_service import lesson_note_service, lesson_note_to_dict

router = APIRouter(prefix="/lessons", tags=["lesson-notes"])


class LessonNoteGenerateRequest(BaseModel):
    session_id: str | None = None
    focus: str | None = None
    max_items: int | None = None
    force: bool = False


@router.get("/notes/{note_id}")
async def get_lesson_note(note_id: str):
    note = lesson_note_service.get_note(note_id)
    if note is None:
        raise HTTPException(status_code=404, detail=f"lesson note not found: {note_id}")
    return {"item": lesson_note_to_dict(note)}


@router.get("/{course_id}/{lesson_id}/notes/latest")
async def get_latest_lesson_note(course_id: str, lesson_id: str):
    note = lesson_note_service.get_latest_note(course_id=course_id, lesson_id=lesson_id)
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
    background_tasks: BackgroundTasks,
    payload: LessonNoteGenerateRequest | None = None,
):
    payload = payload or LessonNoteGenerateRequest()
    try:
        plan = lesson_note_service.request_generation(
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
        background_tasks.add_task(
            lesson_note_service.generate_pending_note,
            plan.note.note_id,
            focus=payload.focus,
            max_items=payload.max_items,
            raise_errors=False,
        )
    return {
        "item": lesson_note_to_dict(plan.note),
        "queued": plan.should_generate,
    }
