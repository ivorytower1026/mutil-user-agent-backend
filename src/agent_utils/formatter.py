import json
import os
from typing import Any

from langchain_core.messages import AIMessage

from .types import (
    InternalEventType,
    INTERNAL_TO_SSE_EVENT,
    TOOL_EXECUTE,
    TOOL_WRITE_FILE,
    TOOL_ASK_USER,
    TASK_DISPLAY_NAMES,
    InterruptData,
)


def sanitize_for_json(data: Any) -> Any:
    if isinstance(data, dict):
        filtered = {k: v for k, v in data.items() if k not in ["content", "messages"]}
        return _convert_for_json(filtered)
    return _convert_for_json(data)


def _convert_for_json(data: Any) -> Any:
    if isinstance(data, (str, int, float, bool, type(None))):
        return data
    elif isinstance(data, dict):
        return {k: _convert_for_json(v) for k, v in data.items()}
    elif isinstance(data, (list, tuple)):
        return [_convert_for_json(item) for item in data]
    else:
        return str(data)


class SSEFormatter:
    def format(self, event_type: str, data: dict) -> str:
        event_name = INTERNAL_TO_SSE_EVENT.get(event_type, event_type)
        
        if event_type == InternalEventType.CONTENT:
            sanitized = _convert_for_json(data)
        else:
            sanitized = sanitize_for_json(data)
        
        return f"event: {event_name}\ndata: {json.dumps(sanitized, ensure_ascii=False)}\n\n"

    def make_content_event(self, content: str) -> str:
        return self.format(InternalEventType.CONTENT, {"content": content})

    def make_tool_start_event(self, tool: str) -> str:
        return self.format(InternalEventType.TOOL_START, {"tool": tool, "status": "running"})

    def make_tool_end_event(self, tool: str) -> str:
        return self.format(InternalEventType.TOOL_END, {"tool": tool, "status": "completed"})

    def make_interrupt_event(self, data: InterruptData) -> str:
        return self.format(InternalEventType.INTERRUPT, dict(data))

    def make_error_event(self, message: str) -> str:
        return self.format(InternalEventType.ERROR, {"message": message})

    def make_done_event(self, action: str | None = None) -> str:
        data = {"action": action} if action else {}
        return self.format(InternalEventType.DONE, data)

    def make_title_updated_event(self, title: str) -> str:
        return self.format(InternalEventType.TITLE_UPDATED, {"title": title})


class StreamDataFormatter:
    def __init__(self, sse_formatter: SSEFormatter):
        self.sse = sse_formatter

    def format_stream_data(self, mode: str, data: Any) -> str | None:
        if mode == "messages":
            return self._format_message(data)
        elif mode == "updates":
            return self._format_update(data)
        return None

    def format_astream_chunk(self, chunk: Any) -> str | None:
        if not isinstance(chunk, tuple) or len(chunk) != 3:
            return None
        
        mode = chunk[1]
        data = chunk[2]
        
        if mode == "messages":
            return self._format_astream_message(data)
        elif mode == "updates":
            return self._format_astream_update(data)
        return None

    def _format_message(self, data: Any) -> str | None:
        if not isinstance(data, tuple) or len(data) != 2:
            return None
        
        msg, _ = data
        if not isinstance(msg, AIMessage) or not msg.content:
            return None
        
        return self.sse.make_content_event(msg.content)

    def _format_astream_message(self, data: Any) -> str | None:
        if isinstance(data, tuple) and len(data) == 2:
            token, _ = data
            if token and isinstance(token, AIMessage):
                content = getattr(token, "content", "")
                if content:
                    return self.sse.make_content_event(content)
        elif isinstance(data, str):
            return self.sse.make_content_event(data)
        return None

    def _format_update(self, data: Any) -> str | None:
        if not isinstance(data, dict):
            return None
        
        interrupt_result = self._format_interrupt(data)
        if interrupt_result:
            return interrupt_result
        
        return self._format_tool_update(data)

    def _format_astream_update(self, data: Any) -> str | None:
        if not isinstance(data, dict):
            return None
        return self._format_interrupt(data)

    def _format_interrupt(self, data: dict) -> str | None:
        if "__interrupt__" not in data:
            return None
        
        interrupt_list = data.get("__interrupt__", [])
        if not interrupt_list:
            return None
        
        interrupt = interrupt_list[0]
        requests = interrupt.value.get("action_requests", [])
        if not requests:
            return None
        
        request = requests[0]
        tool_name = request.get("name", "Unknown")
        
        return self.sse.make_interrupt_event({
            "info": self.format_interrupt_info(request),
            "taskName": TASK_DISPLAY_NAMES.get(tool_name, tool_name),
            "data": sanitize_for_json(interrupt.value),
            "questions": request.get("args", {}).get("questions"),
        })

    def _format_tool_update(self, data: dict) -> str | None:
        for key, value in data.items():
            if key == "__interrupt__":
                continue
            
            if isinstance(value, dict):
                if "input" in value and "output" not in value:
                    return self.sse.make_tool_start_event(key)
                elif "output" in value:
                    return self.sse.make_tool_end_event(key)
            elif isinstance(value, list):
                for item in value:
                    if hasattr(item, 'name') and hasattr(item, 'args'):
                        tool_name = getattr(item, 'name', key)
                        return self.sse.make_tool_start_event(tool_name)
        return None

    @staticmethod
    def format_interrupt_info(request: dict) -> str:
        tool_name = request.get("name", "Unknown")
        args = request.get("args", {})
        
        if tool_name == TOOL_EXECUTE:
            command = args.get("command", "")
            cmd_preview = command[:30] + "..." if len(command) > 30 else command
            return f"正在执行命令: {cmd_preview}"
        elif tool_name == TOOL_WRITE_FILE:
            file_path = args.get("file_path", "")
            file_name = os.path.basename(file_path) if file_path else "文件"
            return f"正在写入文件: {file_name}"
        elif tool_name == TOOL_ASK_USER:
            questions = args.get("questions", [])
            return f"Agent 提出了 {len(questions)} 个问题"
        else:
            return "正在执行操作"
