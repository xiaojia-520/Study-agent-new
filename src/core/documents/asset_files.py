from __future__ import annotations

import re
import zipfile
from pathlib import Path


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".jp2", ".webp", ".gif", ".bmp"}
SLIDE_EXTENSIONS = {".ppt", ".pptx"}
SUPPORTED_ASSET_EXTENSIONS = {
    ".pdf",
    ".doc",
    ".docx",
    ".ppt",
    ".pptx",
    ".png",
    ".jpg",
    ".jpeg",
    ".jp2",
    ".webp",
    ".gif",
    ".bmp",
    ".html",
}


def sanitize_asset_filename(file_name: str) -> str:
    name = Path(file_name or "document").name.strip() or "document"
    cleaned = re.sub(r"[^\w.\-\u4e00-\u9fff]+", "_", name)
    cleaned = re.sub(r"_+", "_", cleaned).strip("._")
    return cleaned or "document"


def validate_asset_file_name(file_name: str) -> None:
    extension = Path(file_name or "").suffix.lower()
    if extension not in SUPPORTED_ASSET_EXTENSIONS:
        supported = ", ".join(sorted(SUPPORTED_ASSET_EXTENSIONS))
        raise ValueError(f"unsupported asset file type; supported extensions: {supported}")


def source_type_for_file(file_name: str) -> str:
    extension = Path(file_name).suffix.lower()
    if extension in IMAGE_EXTENSIONS:
        return "image"
    if extension in SLIDE_EXTENSIONS:
        return "slide"
    return "document"


def safe_extract_zip(zip_path: Path, result_dir: Path) -> None:
    result_dir.mkdir(parents=True, exist_ok=True)
    root = result_dir.resolve()
    with zipfile.ZipFile(zip_path) as archive:
        for member in archive.infolist():
            target_path = (result_dir / member.filename).resolve()
            if root not in target_path.parents and target_path != root:
                raise ValueError(f"unsafe path in MinerU zip: {member.filename}")
        archive.extractall(result_dir)


def find_markdown_file(result_dir: Path) -> Path | None:
    full_md = [path for path in result_dir.rglob("full.md") if path.is_file()]
    if full_md:
        return sorted(full_md)[0]
    markdown_files = [path for path in result_dir.rglob("*.md") if path.is_file()]
    return sorted(markdown_files)[0] if markdown_files else None


def find_content_list_file(result_dir: Path, *, suffix: str) -> Path | None:
    matches = [
        path
        for path in result_dir.rglob("*.json")
        if path.is_file() and (path.name == suffix.lstrip("_") or path.name.endswith(suffix))
    ]
    return sorted(matches)[0] if matches else None
