from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from starlette.responses import StreamingResponse

from src.application.container import ApplicationServices
from web.backend.app.dependencies import get_backend_services
from web.backend.app.execution import run_blocking
from web.backend.app.presenters import lesson_copilot_result_to_dict
from web.backend.app.schemas import LessonCopilotRequest

router = APIRouter(prefix="/lessons", tags=["lesson-copilot"])


@router.post("/{course_id}/{lesson_id}/copilot")
async def run_lesson_copilot(
    course_id: str,
    lesson_id: str,
    payload: LessonCopilotRequest,
    services: ApplicationServices = Depends(get_backend_services),
):
    message = (payload.message or "").strip()
    if not message:
        raise HTTPException(status_code=422, detail="message is required")

    try:
        result = await run_blocking(
            services.lesson_copilot.run,
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


@router.post("/{course_id}/{lesson_id}/copilot/stream")
async def stream_lesson_copilot(
    course_id: str,
    lesson_id: str,
    payload: LessonCopilotRequest,
    services: ApplicationServices = Depends(get_backend_services),
):
    message = (payload.message or "").strip()
    if not message:
        raise HTTPException(status_code=422, detail="message is required")

    def event_stream():
        for item in services.lesson_copilot.stream(
            course_id=course_id,
            lesson_id=lesson_id,
            session_id=payload.session_id,
            message=message,
        ):
            event_name = str(item.get("event") or "message")
            data = json.dumps(item.get("data") or {}, ensure_ascii=False, default=str)
            yield f"event: {event_name}\ndata: {data}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
