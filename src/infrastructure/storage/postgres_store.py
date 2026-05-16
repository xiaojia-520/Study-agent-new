from __future__ import annotations

import re
import threading
from typing import Any, Iterable

from config.settings import settings
from src.infrastructure.storage.database import DatabaseStore

try:
    import psycopg
    from psycopg_pool import ConnectionPool
    from psycopg.rows import dict_row
except ImportError as exc:  # pragma: no cover - exercised only when dependency is absent.
    psycopg = None
    ConnectionPool = None
    dict_row = None
    _PSYCOPG_IMPORT_ERROR = exc
else:
    _PSYCOPG_IMPORT_ERROR = None


class PostgresStore(DatabaseStore):
    def __init__(self, dsn: str | None = None) -> None:
        if psycopg is None or ConnectionPool is None:
            raise RuntimeError("PostgreSQL storage requires the psycopg package with pool support") from _PSYCOPG_IMPORT_ERROR
        self.dsn = dsn or settings.DATABASE_URL
        self._lock = threading.RLock()
        self._pool = ConnectionPool(
            conninfo=self.dsn,
            min_size=max(0, int(settings.DATABASE_POOL_MIN_SIZE)),
            max_size=max(1, int(settings.DATABASE_POOL_MAX_SIZE)),
            timeout=max(1.0, float(settings.DATABASE_POOL_TIMEOUT_SECONDS)),
            kwargs={"row_factory": dict_row},
            open=True,
        )

    def init_schema(self) -> None:
        statements = (
            """
            CREATE TABLE IF NOT EXISTS chat_messages (
                id BIGSERIAL PRIMARY KEY,
                session_id TEXT NOT NULL,
                course_id TEXT,
                lesson_id TEXT,
                role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
                content TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                metadata_json TEXT
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_chat_messages_session_created
            ON chat_messages(session_id, created_at, id)
            """,
            """
            CREATE TABLE IF NOT EXISTS transcript_records (
                id BIGSERIAL PRIMARY KEY,
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
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_transcript_records_lesson_created
            ON transcript_records(course_id, lesson_id, created_at, id)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_transcript_records_session_created
            ON transcript_records(session_id, created_at, id)
            """,
            """
            CREATE TABLE IF NOT EXISTS refined_transcript_records (
                id BIGSERIAL PRIMARY KEY,
                source_record_id BIGINT NOT NULL,
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
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_refined_transcript_records_lesson_created
            ON refined_transcript_records(course_id, lesson_id, created_at, id)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_refined_transcript_records_session_created
            ON refined_transcript_records(session_id, created_at, id)
            """,
            """
            CREATE TABLE IF NOT EXISTS lesson_assets (
                id BIGSERIAL PRIMARY KEY,
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
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_lesson_assets_session_created
            ON lesson_assets(session_id, created_at, id)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_lesson_assets_lesson_created
            ON lesson_assets(course_id, lesson_id, created_at, id)
            """,
            """
            CREATE TABLE IF NOT EXISTS lesson_videos (
                id BIGSERIAL PRIMARY KEY,
                video_id TEXT NOT NULL UNIQUE,
                session_id TEXT NOT NULL,
                course_id TEXT,
                lesson_id TEXT,
                subject TEXT,
                file_name TEXT NOT NULL,
                file_path TEXT NOT NULL,
                file_size BIGINT NOT NULL,
                media_type TEXT NOT NULL,
                status TEXT NOT NULL,
                wav_path TEXT,
                srt_path TEXT,
                text TEXT,
                segment_count INTEGER NOT NULL DEFAULT 0,
                error_message TEXT,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                metadata_json TEXT,
                segments_json TEXT
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_lesson_videos_session_created
            ON lesson_videos(session_id, created_at, id)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_lesson_videos_lesson_created
            ON lesson_videos(course_id, lesson_id, created_at, id)
            """,
            """
            CREATE TABLE IF NOT EXISTS lesson_notes (
                id BIGSERIAL PRIMARY KEY,
                note_id TEXT NOT NULL UNIQUE,
                course_id TEXT NOT NULL,
                lesson_id TEXT NOT NULL,
                session_id TEXT,
                status TEXT NOT NULL,
                title TEXT,
                summary TEXT,
                markdown TEXT,
                note_json TEXT,
                source_record_count INTEGER NOT NULL DEFAULT 0,
                source_hash TEXT,
                model_name TEXT,
                error_message TEXT,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                metadata_json TEXT
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_lesson_notes_lesson_updated
            ON lesson_notes(course_id, lesson_id, updated_at, id)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_lesson_notes_status_updated
            ON lesson_notes(status, updated_at, id)
            """,
        )
        with self._lock:
            with self._connection() as conn:
                with conn.cursor() as cursor:
                    for statement in statements:
                        cursor.execute(statement)
                conn.commit()

    def execute(self, sql: str, params: Iterable[Any] = ()) -> int:
        query = _translate_sql(sql)
        if _is_insert(query) and " RETURNING " not in query.upper():
            query = query.rstrip().rstrip(";") + " RETURNING id"

        with self._connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(query, tuple(params))
                row = cursor.fetchone() if cursor.description is not None else None
            conn.commit()

        if not row:
            return 0
        return int(row["id"] if isinstance(row, dict) else row[0])

    def execute_many(self, sql: str, param_sets: Iterable[Iterable[Any]]) -> None:
        query = _translate_sql(sql)
        materialized = [tuple(params) for params in param_sets]
        if not materialized:
            return

        with self._connection() as conn:
            with conn.cursor() as cursor:
                cursor.executemany(query, materialized)
            conn.commit()

    def query_all(self, sql: str, params: Iterable[Any] = ()) -> list[dict[str, Any]]:
        with self._connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(_translate_sql(sql), tuple(params))
                return [dict(row) for row in cursor.fetchall()]

    def query_one(self, sql: str, params: Iterable[Any] = ()) -> dict[str, Any] | None:
        with self._connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(_translate_sql(sql), tuple(params))
                row = cursor.fetchone()
                return dict(row) if row is not None else None

    def close(self) -> None:
        self._pool.close()

    def _connection(self):
        return self._pool.connection()


def _translate_sql(sql: str) -> str:
    translated = sql.strip()
    translated = re.sub(
        r"\bINTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT\b",
        "BIGSERIAL PRIMARY KEY",
        translated,
        flags=re.IGNORECASE,
    )

    insert_ignore_pattern = re.compile(
        r"\bINSERT\s+OR\s+IGNORE\s+INTO\s+transcript_records\b",
        flags=re.IGNORECASE,
    )
    if insert_ignore_pattern.search(translated):
        translated = insert_ignore_pattern.sub("INSERT INTO transcript_records", translated)
        if "ON CONFLICT" not in translated.upper():
            translated = translated.rstrip().rstrip(";") + "\nON CONFLICT(session_id, chunk_id) DO NOTHING"

    return _replace_qmark_params(translated)


def _replace_qmark_params(sql: str) -> str:
    result: list[str] = []
    in_single_quote = False
    in_double_quote = False
    index = 0
    while index < len(sql):
        char = sql[index]
        if char == "'" and not in_double_quote:
            result.append(char)
            if in_single_quote and index + 1 < len(sql) and sql[index + 1] == "'":
                result.append(sql[index + 1])
                index += 2
                continue
            in_single_quote = not in_single_quote
            index += 1
            continue
        if char == '"' and not in_single_quote:
            in_double_quote = not in_double_quote
            result.append(char)
            index += 1
            continue
        if char == "?" and not in_single_quote and not in_double_quote:
            result.append("%s")
        else:
            result.append(char)
        index += 1
    return "".join(result)


def _is_insert(sql: str) -> bool:
    return sql.lstrip().upper().startswith("INSERT ")
