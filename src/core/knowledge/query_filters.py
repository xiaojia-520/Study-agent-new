from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


FilterOperatorName = Literal["eq", "ne"]
FilterConditionName = Literal["and", "or"]


@dataclass(frozen=True, slots=True)
class MetadataFilterClause:
    key: str
    value: object
    operator: FilterOperatorName = "eq"


@dataclass(frozen=True, slots=True)
class MetadataFilterSpec:
    clauses: tuple[MetadataFilterClause, ...]
    condition: FilterConditionName = "and"

    def __post_init__(self) -> None:
        if not self.clauses:
            raise ValueError("MetadataFilterSpec requires at least one clause")
