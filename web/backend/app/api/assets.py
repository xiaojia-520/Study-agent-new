from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile

from config.settings import settings
from src.application.container import ApplicationServices
from src.core.documents.asset_files import validate_asset_file_name
from web.backend.app.dependencies import get_backend_services
from web.backend.app.tasks import BackgroundTaskRunner
from web.backend.app.uploads import save_upload_file

router = APIRouter(prefix="/sessions", tags=["assets"])


@router.get("/assets")
async def list_lesson_assets(
    limit: int = Query(default=100, ge=1, le=500),
    services: ApplicationServices = Depends(get_backend_services),
):
    items = services.lesson_asset.list_assets(limit=limit)
    return {
        "count": len(items),
        "items": [services.lesson_asset.to_dict(item) for item in items],
    }


@router.post("/assets")
async def upload_lesson_asset(
    file: UploadFile = File(...),
    subject: str | None = Form(default=None),
    services: ApplicationServices = Depends(get_backend_services),
):
    target_path: Path | None = None
    file_name = file.filename or "document"
    try:
        validate_asset_file_name(file_name)
        asset_id, safe_name, target_path = services.lesson_asset.allocate_library_upload_path(
            file_name=file_name,
        )
        file_size = await save_upload_file(
            file,
            target_path,
            max_bytes=settings.MINERU_MAX_UPLOAD_BYTES,
            max_bytes_error="uploaded file exceeds MinerU precise API size limit",
        )
        asset = services.lesson_asset.create_library_asset(
            asset_id=asset_id,
            file_name=safe_name,
            file_path=target_path,
            file_size=file_size,
            media_type=file.content_type or "application/octet-stream",
            subject=(subject or "").strip() or None,
            metadata={"original_file_name": file_name, "library_asset": True},
        )
    except ValueError as exc:
        if target_path is not None:
            target_path.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        await file.close()

    BackgroundTaskRunner().enqueue(services.lesson_asset.parse_and_index_asset, asset.asset_id)
    return {"item": services.lesson_asset.to_dict(asset)}


@router.post("/{session_id}/assets")
async def upload_session_asset(
    session_id: str,
    file: UploadFile = File(...),
    services: ApplicationServices = Depends(get_backend_services),
):
    session = services.session_manager.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"session not found: {session_id}")

    target_path: Path | None = None
    file_name = file.filename or "document"
    try:
        validate_asset_file_name(file_name)
        asset_id, safe_name, target_path = services.lesson_asset.allocate_upload_path(
            session_id=session_id,
            file_name=file_name,
        )
        file_size = await save_upload_file(
            file,
            target_path,
            max_bytes=settings.MINERU_MAX_UPLOAD_BYTES,
            max_bytes_error="uploaded file exceeds MinerU precise API size limit",
        )
        asset = services.lesson_asset.create_asset(
            asset_id=asset_id,
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

    BackgroundTaskRunner().enqueue(services.lesson_asset.parse_and_index_asset, asset.asset_id)
    return {"item": services.lesson_asset.to_dict(asset)}


@router.get("/{session_id}/assets")
async def list_session_assets(
    session_id: str,
    services: ApplicationServices = Depends(get_backend_services),
):
    session = services.session_manager.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"session not found: {session_id}")

    items = services.lesson_asset.list_session_assets(session_id)
    return {
        "session_id": session_id,
        "count": len(items),
        "items": [services.lesson_asset.to_dict(item) for item in items],
    }


@router.get("/assets/{asset_id}")
async def get_lesson_asset(
    asset_id: str,
    services: ApplicationServices = Depends(get_backend_services),
):
    asset = services.lesson_asset.get_asset(asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail=f"asset not found: {asset_id}")
    return {"item": services.lesson_asset.to_dict(asset)}
