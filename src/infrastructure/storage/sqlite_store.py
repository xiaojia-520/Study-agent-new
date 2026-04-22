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
