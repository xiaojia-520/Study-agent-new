import json
import re
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

from config.settings import settings


def _sanitize_for_name(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return "unknown_subject"
    value = re.sub(r"[^\w\-]+", "_", value)
    value = re.sub(r"_+", "_", value).strip("_")
    return value or "unknown_subject"


class TranscriptJsonlStore:
    """
    Minimal JSONL store for lecture transcripts.
    One session writes to one JSONL file, and chunk_id is an incrementing integer.
    """

    def __init__(
        self,
        subject: str,
        session_id: Optional[str] = None,
        root_dir: Optional[Path] = None,
    ):
        self.subject = (subject or "").strip()
        if not self.subject:
            raise ValueError("subject is required")

        ts = time.strftime("%Y%m%d_%H%M%S", time.localtime())
        subject_tag = _sanitize_for_name(self.subject)
        self.session_id = session_id or f"{subject_tag}_{ts}"

        self.root_dir = root_dir or settings.TRANSCRIPT_SAVE_DIR
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self.file_path = self.root_dir / f"{self.session_id}.jsonl"
        if not self.file_path.exists():
            self.file_path.touch()

        self._lock = threading.Lock()
        self._next_chunk_id = self._load_next_chunk_id()

    def _load_next_chunk_id(self) -> int:
        line_count = 0
        with self.file_path.open("r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    line_count += 1
        return line_count + 1

    def append(
        self,
        text: str,
        source_type: str,
        source_file: Optional[str] = None,
        start_ms: Optional[int] = None,
        end_ms: Optional[int] = None,
    ) -> Dict[str, Any]:
        clean_text = (text or "").strip()
        if not clean_text:
            raise ValueError("text is required")

        source = (source_type or "").strip().lower()
        if source not in {"realtime", "video"}:
            raise ValueError("source_type must be 'realtime' or 'video'")

        with self._lock:
            chunk_id = self._next_chunk_id
            self._next_chunk_id += 1

            record: Dict[str, Any] = {
                "session_id": self.session_id,
                "chunk_id": chunk_id,
                "subject": self.subject,
                "source_type": source,
                "source_file": source_file,
                "start_ms": start_ms,
                "end_ms": end_ms,
                "text": clean_text,
                "clean_text": clean_text,
                "created_at": int(time.time()),
            }

            with self.file_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")

            return record
