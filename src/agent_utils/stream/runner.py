import logging
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Iterator

from langgraph.types import Command

from ..types import AUTO_APPROVE_TOOLS, TASK_DISPLAY_NAMES
from ..formatter import SSEFormatter, sanitize_for_json

logger = logging.getLogger(__name__)


@dataclass
class StreamChunk:
    event: str | None = None
    auto_resume: bool = False
    error: str | None = None


@dataclass
class RunnerState:
    last_tool_name: str = ""
    last_tool_args: dict = field(default_factory=dict)


class AgentStreamRunner:
    """
    Stream runner - encapsulates auto_resume loop
    
    Uses LangGraph native stream modes:
    - messages: LLM token stream + tool_calls detection
    - updates: state updates + tool events + interrupts
    
    Note: tools stream mode is not available (returns 0 chunks)
    """
    
    def __init__(self, agent: Any, formatter: SSEFormatter):
        self.agent = agent
        self.formatter = formatter
        self._state = RunnerState()
    
    async def run(
        self,
        thread_id: str,
        initial_input: dict | Command,
        mode: str = "build",
        callbacks: list | None = None,
    ) -> AsyncIterator[str]:
        """
        Execute stream processing
        
        Args:
            thread_id: Session ID
            initial_input: Initial input (message dict or resume Command)
            mode: Run mode ("build" | "plan")
            callbacks: Langfuse etc callbacks
            
        Yields:
            SSE formatted event string
        """
        config = {
            "configurable": {"thread_id": thread_id},
            "callbacks": callbacks or []
        }
        current_input = initial_input
        
        while True:
            auto_resume = False
            
            try:
                async for chunk in self._stream_one_cycle(current_input, config, mode):
                    if chunk.auto_resume:
                        auto_resume = True
                        break
                    elif chunk.error:
                        yield chunk.error
                        return
                    elif chunk.event:
                        yield chunk.event
            except Exception as e:
                logger.exception("AgentStreamRunner error")
                yield self.formatter.make_error_event(str(e))
                return
            
            if auto_resume:
                current_input = Command(resume={"decisions": [{"type": "approve"}]})
            else:
                break
    
    async def _stream_one_cycle(
        self,
        current_input: dict | Command,
        config: dict,
        mode: str,
    ) -> AsyncIterator[StreamChunk]:
        """Process single stream cycle"""
        
        async for subgraph_path, stream_mode, data in self.agent.astream(
            current_input,
            config=config,
            stream_mode=["messages", "updates"],
            subgraphs=True,
        ):
            if stream_mode == "messages":
                for chunk in self._handle_messages(data):
                    yield chunk
            
            elif stream_mode == "updates":
                chunk = self._handle_updates(data, mode)
                if chunk:
                    yield chunk
    
    def _handle_messages(self, data: Any) -> list[StreamChunk]:
        """
        Handle messages stream - LLM token and tool_calls
        
        Data format: (AIMessageChunk, metadata: dict)
        """
        chunks = []
        if isinstance(data, tuple) and len(data) == 2:
            msg, metadata = data
            
            if hasattr(msg, 'tool_calls') and msg.tool_calls:
                for tc in msg.tool_calls:
                    if isinstance(tc, dict):
                        name = tc.get('name', '')
                        args = tc.get('args', {})
                        if name:
                            self._state.last_tool_name = name
                            self._state.last_tool_args = args if isinstance(args, dict) else {}
                            chunks.append(StreamChunk(event=self.formatter.make_tool_start_event(name)))
            
            if hasattr(msg, 'content') and msg.content:
                content = msg.content
                if isinstance(content, str) and content:
                    chunks.append(StreamChunk(event=self.formatter.make_content_event(content)))
        
        return chunks
    
    def _handle_updates(self, data: dict, mode: str) -> StreamChunk | None:
        """
        Handle updates stream - tool events and interrupts
        
        Data format: {"model": ..., "tools": ..., "__interrupt__": ...}
        
        Note: data["tools"] may be dict instead of ToolMessage
        """
        if not isinstance(data, dict):
            return None
        
        if "tools" in data:
            tool_data = data["tools"]
            if isinstance(tool_data, dict):
                tool_name = tool_data.get("name", self._state.last_tool_name or "unknown")
            elif hasattr(tool_data, 'name'):
                tool_name = tool_data.name
            else:
                tool_name = self._state.last_tool_name or "unknown"
            return StreamChunk(event=self.formatter.make_tool_end_event(tool_name))
        
        if "__interrupt__" in data:
            return self._handle_interrupt(data, mode)
        
        return None
    
    def _handle_interrupt(self, data: dict, mode: str) -> StreamChunk:
        """Handle interrupt event"""
        interrupt_list = data.get("__interrupt__", [])
        if not interrupt_list:
            return StreamChunk()
        
        interrupt = interrupt_list[0]
        requests = interrupt.value.get("action_requests", [])
        if not requests:
            return StreamChunk()
        
        request = requests[0]
        tool_name = request.get("name", "")
        
        if tool_name in AUTO_APPROVE_TOOLS:
            if mode == "build":
                return StreamChunk(auto_resume=True)
            else:
                return StreamChunk(
                    error=self.formatter.make_error_event("当前为思考模式，请切换到 build 模式执行操作")
                )
        
        return StreamChunk(
            event=self.formatter.make_interrupt_event({
                "info": self._format_interrupt_info(request),
                "taskName": TASK_DISPLAY_NAMES.get(tool_name, tool_name) or tool_name,
                "data": sanitize_for_json(interrupt.value),
                "questions": request.get("args", {}).get("questions") or [],
            })
        )
    
    def _format_interrupt_info(self, request: dict[str, Any]) -> str:
        """Format interrupt info"""
        import os
        
        tool_name = request.get("name", "Unknown") or "Unknown"
        args = request.get("args", {}) or {}
        
        if tool_name == "execute":
            command = args.get("command", "") or ""
            preview = command[:30] + "..." if len(command) > 30 else command
            return f"正在执行命令: {preview}"
        elif tool_name == "write_file":
            file_path = args.get("file_path", "") or ""
            name = os.path.basename(file_path) if file_path else "文件"
            return f"正在写入文件: {name}"
        elif tool_name == "edit_file":
            file_path = args.get("file_path", "") or ""
            name = os.path.basename(file_path) if file_path else "文件"
            return f"正在编辑文件: {name}"
        elif tool_name == "ask_user":
            questions = args.get("questions", []) or []
            return f"Agent 提出了 {len(questions)} 个问题"
        else:
            return "正在执行操作"
