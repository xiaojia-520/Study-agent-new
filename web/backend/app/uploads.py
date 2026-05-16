from __future__ import annotations

from pathlib import Path

from fastapi import UploadFile

from web.backend.app.execution import run_blocking


UPLOAD_CHUNK_SIZE = 1024 * 1024


async def save_upload_file(
    file: UploadFile,
    target_path: Path,
    *,
    max_bytes: int | None = None,
    max_bytes_error: str = "uploaded file exceeds size limit",
) -> int:
    file_size = 0
    with target_path.open("wb") as handle:
        while True:
            chunk = await file.read(UPLOAD_CHUNK_SIZE)
            if not chunk:
                break
            file_size += len(chunk)
            if max_bytes is not None and file_size > max_bytes:
                raise ValueError(max_bytes_error)
            await run_blocking(handle.write, chunk)
    return file_size
