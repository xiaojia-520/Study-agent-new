from dataclasses import dataclass
from typing import Any, Callable, Mapping


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    handler: Callable[[Mapping[str, Any]], Any]


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        return self._tools[name]

    def list_tools(self) -> list[Tool]:
        return list(self._tools.values())
