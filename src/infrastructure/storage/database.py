from __future__ import annotations

from typing import Any, Iterable, Protocol


class DatabaseStore(Protocol):
    def init_schema(self) -> None:
        ...

    def execute(self, sql: str, params: Iterable[Any] = ()) -> int:
        ...

    def execute_many(self, sql: str, param_sets: Iterable[Iterable[Any]]) -> None:
        ...

    def query_all(self, sql: str, params: Iterable[Any] = ()) -> list[dict[str, Any]]:
        ...

    def query_one(self, sql: str, params: Iterable[Any] = ()) -> dict[str, Any] | None:
        ...

    def close(self) -> None:
        ...
