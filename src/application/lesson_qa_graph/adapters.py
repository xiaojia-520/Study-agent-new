from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


class RetrieverProtocol(Protocol):
    def search(self, query: str, **kwargs: Any) -> list[Any]: ...


class MemoryProtocol(Protocol):
    def list_recent_lesson_turns(self, **kwargs: Any) -> list[Any]: ...

    def append_turn(self, **kwargs: Any) -> None: ...


@dataclass(slots=True)
class LessonQaGraphAdapters:
    retriever: RetrieverProtocol
    memory: MemoryProtocol | None = None

