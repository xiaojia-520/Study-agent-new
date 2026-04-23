from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Any, Iterable

from config.settings import settings


class SQLiteStore:
    def __init__(self, db_path: Path | str | None = None) -> None:
        self.db_path = Path(db_path or settings.SQLITE_DB_PATH)
        self._lock = threading.RLock()

    def init_schema(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS chat_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    course_id TEXT,
                    lesson_id TEXT,
                    role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
                    content TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    metadata_json TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_chat_messages_session_created
                ON chat_messages(session_id, created_at, id)
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS transcript_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    storage_id TEXT,
                    course_id TEXT,
                    lesson_id TEXT,
                    chunk_id INTEGER NOT NULL,
                    subject TEXT,
                    source_type TEXT NOT NULL,
                    source_file TEXT,
                    start_ms INTEGER,
                    end_ms INTEGER,
                    text TEXT NOT NULL,
                    clean_text TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    metadata_json TEXT,
                    UNIQUE(session_id, chunk_id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS lesson_assets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    asset_id TEXT NOT NULL UNIQUE,
                    session_id TEXT NOT NULL,
                    course_id TEXT,
                    lesson_id TEXT,
                    subject TEXT,
                    file_name TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    file_size INTEGER NOT NULL,
                    media_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    batch_id TEXT,
                    mineru_state TEXT,
                    full_zip_url TEXT,
                    result_dir TEXT,
                    markdown_path TEXT,
                    record_count INTEGER NOT NULL DEFAULT 0,
                    indexed_at INTEGER,
                    error_message TEXT,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL,
                    metadata_json TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_lesson_assets_session_created
                ON lesson_assets(session_id, created_at, id)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_lesson_assets_lesson_created
                ON lesson_assets(course_id, lesson_id, created_at, id)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_transcript_records_lesson_created
                ON transcript_records(course_id, lesson_id, created_at, id)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_transcript_records_session_created
                ON transcript_records(session_id, created_at, id)
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS refined_transcript_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_record_id INTEGER NOT NULL,
                    session_id TEXT NOT NULL,
                    course_id TEXT,
                    lesson_id TEXT,
                    chunk_id INTEGER NOT NULL,
                    original_text TEXT NOT NULL,
                    refined_text TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    refined_at INTEGER NOT NULL,
                    model_name TEXT,
                    metadata_json TEXT,
                    UNIQUE(source_record_id),
                    FOREIGN KEY(source_record_id) REFERENCES transcript_records(id) ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_refined_transcript_records_lesson_created
                ON refined_transcript_records(course_id, lesson_id, created_at, id)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_refined_transcript_records_session_created
                ON refined_transcript_records(session_id, created_at, id)
                """
            )
            conn.commit()

    def execute(self, sql: str, params: Iterable[Any] = ()) -> int:
        with self._lock:
            with self._connect() as conn:
                cursor = conn.execute(sql, tuple(params))
                conn.commit()
                return int(cursor.lastrowid or 0)

    def query_all(self, sql: str, params: Iterable[Any] = ()) -> list[dict[str, Any]]:
        with self._lock:
            with self._connect() as conn:
                cursor = conn.execute(sql, tuple(params))
                return [dict(row) for row in cursor.fetchall()]

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path), timeout=30)
        conn.row_factory = sqlite3.Row
        return conn


sqlite_store = SQLiteStore()
