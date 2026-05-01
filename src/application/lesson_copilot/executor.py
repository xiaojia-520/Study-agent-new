from src.application.lesson_copilot.types import ToolCall, ToolResult
from src.application.lesson_copilot.tool_registry import  ToolRegistry

class Executor:
    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry

    def execute(self, call: ToolCall) -> ToolResult:
        tool = self.registry.get(call.name)
        try:
            result = tool.handler(dict(call.arguments))
            return ToolResult(name=call.name, ok=True, content=result)
        except Exception as exc:
            return ToolResult(name=call.name, ok=False, error=str(exc))