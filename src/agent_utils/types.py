import logging
from enum import StrEnum
from typing import Any, TypedDict

logger = logging.getLogger(__name__)


class SSEEvent(StrEnum):
    CONTENT = "messages/partial"
    TOOL_START = "tool/start"
    TOOL_END = "tool/end"
    INTERRUPT = "interrupt"
    STRUCTURED = "structured"
    ERROR = "error"
    END = "end"
    TITLE_UPDATED = "title_updated"
    TODOS_UPDATED = "todos_updated"


class InterruptAction(StrEnum):
    CONTINUE = "continue"
    CANCEL = "cancel"
    ANSWER = "answer"


class InternalEventType(StrEnum):
    CONTENT = "content"
    TOOL_START = "tool_start"
    TOOL_END = "tool_end"
    INTERRUPT = "interrupt"
    STRUCTURED = "structured"
    ERROR = "error"
    DONE = "done"
    TITLE_UPDATED = "title_updated"
    TODOS_UPDATED = "todos_updated"


TOOL_EXECUTE = "execute"
TOOL_WRITE_FILE = "write_file"
TOOL_ASK_USER = "ask_user"

TASK_DISPLAY_NAMES: dict[str, str] = {
    TOOL_EXECUTE: "执行命令",
    TOOL_WRITE_FILE: "写入文件",
    TOOL_ASK_USER: "用户问答",
}

INTERNAL_TO_SSE_EVENT: dict[str, str] = {
    InternalEventType.CONTENT: SSEEvent.CONTENT,
    InternalEventType.TOOL_START: SSEEvent.TOOL_START,
    InternalEventType.TOOL_END: SSEEvent.TOOL_END,
    InternalEventType.INTERRUPT: SSEEvent.INTERRUPT,
    InternalEventType.STRUCTURED: SSEEvent.STRUCTURED,
    InternalEventType.ERROR: SSEEvent.ERROR,
    InternalEventType.DONE: SSEEvent.END,
    InternalEventType.TITLE_UPDATED: SSEEvent.TITLE_UPDATED,
    InternalEventType.TODOS_UPDATED: SSEEvent.TODOS_UPDATED,
}


class InterruptData(TypedDict):
    info: str
    taskName: str
    data: dict[str, Any]
    questions: list[dict[str, Any]] | None


class ToolStartData(TypedDict):
    tool: str
    status: str


class ToolEndData(TypedDict):
    tool: str
    status: str


class ContentData(TypedDict):
    content: str


class ErrorData(TypedDict):
    message: str
