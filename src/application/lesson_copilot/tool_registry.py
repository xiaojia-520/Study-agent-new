from dataclasses import dataclass
from typing import Any, Callable, Mapping

from pydantic import BaseModel


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    handler: Callable[[Mapping[str, Any]], Any]
    fn_schema: type[BaseModel] | None = None

    def to_llamaindex_tool(self):
        from llama_index.core.tools import FunctionTool, ToolMetadata

        def _placeholder(**kwargs):
            return None

        return FunctionTool(
            fn=_placeholder,
            metadata=ToolMetadata(
                name=self.name,
                description=self.description,
                fn_schema=self.fn_schema,
            ),
        )


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        return self._tools[name]

    def list_tools(self) -> list[Tool]:
        return list(self._tools.values())
