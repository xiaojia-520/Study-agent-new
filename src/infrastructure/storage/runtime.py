from __future__ import annotations

from config.settings import settings
from src.infrastructure.storage.database import DatabaseStore
from src.infrastructure.storage.sqlite_store import sqlite_store


def build_database_store() -> DatabaseStore:
    backend = (settings.DATABASE_BACKEND or "sqlite").strip().lower()
    if backend == "sqlite":
        return sqlite_store
    if backend in {"postgres", "postgresql"}:
        from src.infrastructure.storage.postgres_store import PostgresStore

        return PostgresStore(settings.DATABASE_URL)
    raise ValueError(f"unsupported DATABASE_BACKEND: {settings.DATABASE_BACKEND}")


database_store = build_database_store()


def close_database_store() -> None:
    database_store.close()
