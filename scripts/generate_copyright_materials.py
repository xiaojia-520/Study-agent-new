from __future__ import annotations

import json
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "copyright_materials"

SOURCE_EXTENSIONS = {".py", ".vue", ".ts", ".js", ".css", ".html", ".sql"}
EXCLUDED_FILES = {
    "1.py",
    "scripts/generate_copyright_materials.py",
}
EXCLUDED_DIRS = {
    ".git",
    ".idea",
    ".pytest_cache",
    ".venv",
    "__pycache__",
    "build",
    "ClaudeCode",
    "copyright_materials",
    "coverage",
    "data",
    "dist",
    "logs",
    "models",
    "node_modules",
    "uploads",
    "venv",
}

PAGE_SIZE = (1240, 1754)
MARGIN_X = 72
MARGIN_TOP = 72
MARGIN_BOTTOM = 72
LINE_HEIGHT = 25
BODY_FONT_SIZE = 18
TITLE_FONT_SIZE = 24


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        Path("C:/Windows/Fonts/msyh.ttc"),
        Path("C:/Windows/Fonts/simsun.ttc"),
        Path("C:/Windows/Fonts/simhei.ttf"),
        Path("C:/Windows/Fonts/arial.ttf"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size=size)
    return ImageFont.load_default()


BODY_FONT = _font(BODY_FONT_SIZE)
TITLE_FONT = _font(TITLE_FONT_SIZE)


def _is_excluded(path: Path) -> bool:
    rel_path = path.relative_to(ROOT).as_posix()
    if rel_path in EXCLUDED_FILES:
        return True
    return any(part in EXCLUDED_DIRS for part in path.relative_to(ROOT).parts)


def _collect_source_files() -> list[Path]:
    files: list[Path] = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        if _is_excluded(path):
            continue
        if path.suffix.lower() in SOURCE_EXTENSIONS:
            files.append(path)
    return sorted(files, key=lambda item: item.relative_to(ROOT).as_posix().lower())


def _read_text(path: Path) -> str:
    for encoding in ("utf-8", "utf-8-sig", "gbk"):
        try:
            return path.read_text(encoding=encoding, errors="strict")
        except UnicodeError:
            continue
    return path.read_text(encoding="utf-8", errors="replace")


def _wrap_line(line: str, width: int) -> list[str]:
    normalized = line.expandtabs(4).rstrip()
    if not normalized:
        return [""]
    return textwrap.wrap(
        normalized,
        width=width,
        replace_whitespace=False,
        drop_whitespace=False,
        break_long_words=True,
        break_on_hyphens=False,
    ) or [""]


def _paginate(lines: list[str], *, chars_per_line: int, lines_per_page: int) -> list[list[str]]:
    pages: list[list[str]] = []
    page: list[str] = []
    for raw_line in lines:
        for line in _wrap_line(raw_line, chars_per_line):
            page.append(line)
            if len(page) >= lines_per_page:
                pages.append(page)
                page = []
    if page:
        pages.append(page)
    return pages


def _select_deposit_pages(pages: list[list[str]]) -> list[list[str]]:
    if len(pages) <= 60:
        return pages
    return pages[:30] + pages[-30:]


def _render_pages(
    pages: list[list[str]],
    output_path: Path,
    *,
    title: str,
    original_page_count: int,
    selected_page_count: int,
) -> None:
    images: list[Image.Image] = []
    for index, page_lines in enumerate(pages, start=1):
        image = Image.new("RGB", PAGE_SIZE, "white")
        draw = ImageDraw.Draw(image)
        draw.text((MARGIN_X, 36), title, fill=(20, 20, 20), font=TITLE_FONT)
        draw.text(
            (PAGE_SIZE[0] - 420, 42),
            f"第 {index} 页 / 共 {selected_page_count} 页",
            fill=(90, 90, 90),
            font=BODY_FONT,
        )
        y = MARGIN_TOP + 32
        for line in page_lines:
            draw.text((MARGIN_X, y), line, fill=(30, 30, 30), font=BODY_FONT)
            y += LINE_HEIGHT
        footer = f"鉴别材料页数：原始 {original_page_count} 页，交存 {selected_page_count} 页"
        draw.text((MARGIN_X, PAGE_SIZE[1] - 52), footer, fill=(110, 110, 110), font=BODY_FONT)
        images.append(image)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    first, rest = images[0], images[1:]
    first.save(output_path, "PDF", resolution=150.0, save_all=True, append_images=rest)


def _build_source_lines() -> list[str]:
    lines = [
        "智课枢 软件源程序鉴别材料",
        "交存方式：一般交存",
        "内容：源程序前连续30页和后连续30页",
        "",
    ]
    for file_path in _collect_source_files():
        rel_path = file_path.relative_to(ROOT).as_posix()
        lines.extend(
            [
                "",
                "=" * 96,
                f"文件：{rel_path}",
                "=" * 96,
            ]
        )
        lines.extend(_read_text(file_path).splitlines())
    return lines


def _build_document_lines() -> list[str]:
    readme = ROOT / "README.md"
    lines = [
        "智课枢 软件说明书鉴别材料",
        "交存方式：一般交存",
        "文档来源：项目 README 和软件功能说明",
        "",
        "软件名称：智课枢",
        "软件类型：教育软件、人工智能软件",
        "",
    ]
    if readme.exists():
        lines.extend(_read_text(readme).splitlines())
    return lines


def _build_pdf(lines: list[str], output_path: Path, *, title: str) -> dict[str, int | str]:
    max_lines = (PAGE_SIZE[1] - MARGIN_TOP - MARGIN_BOTTOM - 40) // LINE_HEIGHT
    pages = _paginate(lines, chars_per_line=78, lines_per_page=max_lines)
    selected_pages = _select_deposit_pages(pages)
    _render_pages(
        selected_pages,
        output_path,
        title=title,
        original_page_count=len(pages),
        selected_page_count=len(selected_pages),
    )
    return {
        "path": str(output_path),
        "original_pages": len(pages),
        "deposit_pages": len(selected_pages),
    }


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    result = {
        "source": _build_pdf(
            _build_source_lines(),
            OUTPUT_DIR / "智课枢_程序鉴别材料_一般交存.pdf",
            title="智课枢 程序鉴别材料",
        ),
        "document": _build_pdf(
            _build_document_lines(),
            OUTPUT_DIR / "智课枢_文档鉴别材料_一般交存.pdf",
            title="智课枢 文档鉴别材料",
        ),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
