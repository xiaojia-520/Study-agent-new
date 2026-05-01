from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from web.backend.app.services.lesson_copilot_service import (
    lesson_copilot_result_to_dict,
    lesson_copilot_service,
)

router = APIRouter(prefix="/lessons", tags=["lesson-copilot"])


class LessonCopilotRequest(BaseModel):
    message: str
    session_id: str | None = None


@router.post("/{course_id}/{lesson_id}/copilot")
async def run_lesson_copilot(course_id: str, lesson_id: str, payload: LessonCopilotRequest):
    message = (payload.message or "").strip()
    if not message:
        raise HTTPException(status_code=422, detail="message is required")

    try:
        result = lesson_copilot_service.run(
            course_id=course_id,
            lesson_id=lesson_id,
            session_id=payload.session_id,
            message=message,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"lesson transcript or note context not found: {course_id}/{lesson_id}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return lesson_copilot_result_to_dict(result)
