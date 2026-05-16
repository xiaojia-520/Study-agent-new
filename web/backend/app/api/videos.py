from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from config.settings import settings
from src.application.container import ApplicationServices
from src.application.video.video_service import validate_video_file_name
from web.backend.app.dependencies import get_backend_services
from web.backend.app.presenters import video_response_item
from web.backend.app.tasks import BackgroundTaskRunner
from web.backend.app.uploads import save_upload_file

router = APIRouter(prefix="/sessions", tags=["videos"])


@router.post("/{session_id}/videos")
async def upload_session_video(
    session_id: str,
    file: UploadFile = File(...),
    recording_started_at_ms: int | None = Form(default=None),
    recording_ended_at_ms: int | None = Form(default=None),
    services: ApplicationServices = Depends(get_backend_services),
):
    session = services.session_manager.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"session not found: {session_id}")

    target_path: Path | None = None
    file_name = file.filename or "recording.webm"
    try:
        validate_video_file_name(file_name)
        video_id, safe_name, target_path = services.session_video.allocate_upload_path(
            session_id=session_id,
            file_name=file_name,
        )
        file_size = await save_upload_file(
            file,
            target_path,
            max_bytes=settings.VIDEO_MAX_UPLOAD_BYTES,
            max_bytes_error="uploaded video exceeds size limit",
        )
        video = services.session_video.create_video(
            video_id=video_id,
            session=session,
            file_name=safe_name,
            file_path=target_path,
            file_size=file_size,
            media_type=file.content_type or "application/octet-stream",
            metadata={
                "original_file_name": file_name,
                "recording_started_at_ms": recording_started_at_ms,
                "recording_ended_at_ms": recording_ended_at_ms,
            },
        )
    except ValueError as exc:
        if target_path is not None:
            target_path.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        await file.close()

    BackgroundTaskRunner().enqueue(services.session_video.process_video, video.video_id)
    return {"item": video_response_item(video)}


@router.get("/{session_id}/videos")
async def list_session_videos(
    session_id: str,
    services: ApplicationServices = Depends(get_backend_services),
):
    session = services.session_manager.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"session not found: {session_id}")

    items = services.session_video.list_session_videos(session_id)
    return {
        "session_id": session_id,
        "count": len(items),
        "items": [video_response_item(item) for item in items],
    }


@router.get("/videos/{video_id}")
async def get_session_video(
    video_id: str,
    services: ApplicationServices = Depends(get_backend_services),
):
    video = services.session_video.get_video(video_id)
    if video is None:
        raise HTTPException(status_code=404, detail=f"video not found: {video_id}")
    return {"item": video_response_item(video)}


@router.get("/videos/{video_id}/file")
async def download_session_video_file(
    video_id: str,
    services: ApplicationServices = Depends(get_backend_services),
):
    video = services.session_video.get_video(video_id)
    if video is None:
        raise HTTPException(status_code=404, detail=f"video not found: {video_id}")

    file_path = Path(video.file_path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="video file not found")
    return FileResponse(file_path, media_type=video.media_type, filename=video.file_name)


@router.get("/videos/{video_id}/srt")
async def download_session_video_srt(
    video_id: str,
    services: ApplicationServices = Depends(get_backend_services),
):
    video = services.session_video.get_video(video_id)
    if video is None:
        raise HTTPException(status_code=404, detail=f"video not found: {video_id}")
    if video.status != "done" or not video.srt_path:
        raise HTTPException(status_code=404, detail="subtitle is not ready")

    srt_path = Path(video.srt_path)
    if not srt_path.exists():
        raise HTTPException(status_code=404, detail="subtitle file not found")
    return FileResponse(srt_path, media_type="application/x-subrip", filename=f"{video.video_id}.srt")
