import json
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
    auto_reject: bool = False  # plan 模式下自动拒绝
    error: str | None = None


@dataclass
class RunnerState:
    last_tool_name: str = ""
    last_tool_args: dict = field(default_factory=dict)

    in_subagent: bool = False
    current_subagent_id: str | None = None
    current_subagent_name: str | None = None
    subagent_stack: list = field(default_factory=list)


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
            "callbacks": callbacks or [],
        }
        current_input = initial_input

        while True:
            auto_resume = False
            auto_reject = False

            try:
                async for chunk in self._stream_one_cycle(current_input, config, mode):
                    if chunk.auto_resume:
                        auto_resume = True
                        break
                    elif chunk.auto_reject:
                        auto_reject = True
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
            elif auto_reject:
                # plan 模式下拒绝，并告诉 LLM 原因
                current_input = Command(
                    resume={
                        "decisions": [
                            {
                                "type": "reject",
                                "message": "当前为思考模式，此操作需要写入权限。请友好提示用户切换到【执行】模式后再继续。不要重复尝试执行此操作。",
                            }
                        ]
                    }
                )
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
                for chunk in self._handle_messages(subgraph_path, data):
                    yield chunk

            elif stream_mode == "updates":
                for chunk in self._handle_updates(subgraph_path, data, mode):
                    yield chunk

    def _handle_messages(self, subgraph_path: tuple, data: Any) -> list[StreamChunk]:
        """
        Handle messages stream - LLM token and tool_calls

        Args:
            subgraph_path: Namespace tuple from subgraphs=True
            data: (AIMessageChunk, metadata: dict)

        Note:
            - tool_calls args are streamed incrementally (may be empty in first chunks)
            - For write_todos, we get complete args from updates mode instead.
            - Only output AIMessageChunk content, skip ToolMessage content (internal messages)
        """
        chunks = []

        # 解析 namespace
        namespace = list(subgraph_path) if subgraph_path else None
        is_main_agent = not bool(subgraph_path)

        # 确定子代理信息
        subagent_id = None
        subagent_name = None

        if not is_main_agent and self._state.in_subagent:
            # 从 namespace 提取 ID
            for segment in subgraph_path:
                if isinstance(segment, str) and segment.startswith("tools:"):
                    subagent_id = segment.split(":", 1)[1]
                    self._state.current_subagent_id = subagent_id
                    if self._state.subagent_stack:
                        self._state.subagent_stack[-1]["id"] = subagent_id
                    break

            subagent_name = self._state.current_subagent_name

        if isinstance(data, tuple) and len(data) == 2:
            msg, metadata = data

            # 只处理 AIMessageChunk，跳过 ToolMessage（工具返回结果）
            msg_type = type(msg).__name__
            if msg_type == "ToolMessage":
                # 检查是否是 task 工具的结束
                if (
                    self._state.in_subagent
                    and hasattr(msg, "name")
                    and msg.name == "task"
                ):
                    # 子代理结束，弹出栈
                    if self._state.subagent_stack:
                        self._state.subagent_stack.pop()
                        if not self._state.subagent_stack:
                            self._state.in_subagent = False
                            self._state.current_subagent_id = None
                            self._state.current_subagent_name = None
                return chunks

            if hasattr(msg, "tool_calls") and msg.tool_calls:
                for tc in msg.tool_calls:
                    if isinstance(tc, dict):
                        name = tc.get("name", "")
                        args = tc.get("args", {})
                        if name:
                            self._state.last_tool_name = name
                            self._state.last_tool_args = (
                                args if isinstance(args, dict) else {}
                            )

                            # 检查是否为子代理调用（只在主代理中检测）
                            if name == "task" and is_main_agent:
                                # 进入子代理模式
                                self._state.in_subagent = True
                                subagent_name_from_args = (
                                    args.get("subagent_type", "unknown")
                                    if isinstance(args, dict)
                                    else "unknown"
                                )
                                self._state.current_subagent_name = (
                                    subagent_name_from_args
                                )

                                # 压入栈（支持嵌套）
                                self._state.subagent_stack.append(
                                    {"id": None, "name": subagent_name_from_args}
                                )

                            # write_todos 不在这里发送 tool/start，在 updates 模式中发送（有完整 todos）
                            # task 工具也不发送（内部工具）
                            if name != "write_todos" and name != "task":
                                chunks.append(
                                    StreamChunk(
                                        event=self.formatter.make_tool_start_event(
                                            name,
                                            namespace=namespace,
                                            subagent_id=subagent_id,
                                            subagent_name=subagent_name,
                                        )
                                    )
                                )

            if hasattr(msg, "content") and msg.content:
                content = msg.content
                if isinstance(content, str) and content:
                    # 过滤掉内部系统消息
                    if not self._is_internal_message(content):
                        chunks.append(
                            StreamChunk(
                                event=self.formatter.make_content_event(
                                    content,
                                    namespace=namespace,
                                    subagent_id=subagent_id,
                                    subagent_name=subagent_name,
                                )
                            )
                        )

        return chunks

    def _is_internal_message(self, content: str) -> bool:
        """检查是否是内部系统消息，不应显示给用户"""
        internal_patterns = [
            "User rejected the tool call",
            "Tool call rejected",
            "Tool result:",
            "Action rejected",
        ]
        for pattern in internal_patterns:
            if pattern in content:
                return True
        return False

    def _handle_updates(
        self, subgraph_path: tuple, data: dict, mode: str
    ) -> list[StreamChunk]:
        """
        Handle updates stream - tool events and interrupts

        Args:
            subgraph_path: Namespace tuple from subgraphs=True
            data: {"agent": ..., "tools": ..., "__interrupt__": ...}
            mode: "build" or "plan"

        Note:
            - data["tools"] may be dict instead of ToolMessage
            - data["agent"] contains complete tool_calls with todos for write_todos
        """
        chunks = []

        if not isinstance(data, dict):
            return chunks

        # 解析 namespace
        namespace = list(subgraph_path) if subgraph_path else None
        is_main_agent = not bool(subgraph_path)

        # 确定子代理信息
        subagent_id = None
        subagent_name = None

        if not is_main_agent and self._state.in_subagent:
            # 从 namespace 提取 ID
            for segment in subgraph_path:
                if isinstance(segment, str) and segment.startswith("tools:"):
                    subagent_id = segment.split(":", 1)[1]
                    self._state.current_subagent_id = subagent_id
                    if self._state.subagent_stack:
                        self._state.subagent_stack[-1]["id"] = subagent_id
                    break

            subagent_name = self._state.current_subagent_name

        # 处理 model 更新 - 获取完整的 tool_calls 信息（包含 write_todos 的 todos）
        if "model" in data:
            model_data = data["model"]
            if isinstance(model_data, dict) and "messages" in model_data:
                for msg in model_data.get("messages", []):
                    if hasattr(msg, "tool_calls") and msg.tool_calls:
                        for tc in msg.tool_calls:
                            if isinstance(tc, dict):
                                name = tc.get("name", "")

                                # 检查是否为子代理调用（只在主代理中检测）
                                if name == "task" and is_main_agent:
                                    args = tc.get("args", {})
                                    self._state.in_subagent = True
                                    self._state.current_subagent_name = args.get(
                                        "subagent_type", "unknown"
                                    )

                                    # 压入栈
                                    self._state.subagent_stack.append(
                                        {
                                            "id": None,
                                            "name": self._state.current_subagent_name,
                                        }
                                    )

                                if name == "write_todos":
                                    args = tc.get("args", {})
                                    todos = (
                                        args.get("todos", [])
                                        if isinstance(args, dict)
                                        else []
                                    )
                                    self._state.last_tool_name = name
                                    self._state.last_tool_args = (
                                        args if isinstance(args, dict) else {}
                                    )
                                    chunks.append(
                                        StreamChunk(
                                            event=self.formatter.make_tool_start_event(
                                                name,
                                                todos,
                                                namespace=namespace,
                                                subagent_id=subagent_id,
                                                subagent_name=subagent_name,
                                            )
                                        )
                                    )

        if "tools" in data:
            tool_data = data["tools"]
            if isinstance(tool_data, dict):
                tool_name = tool_data.get(
                    "name", self._state.last_tool_name or "unknown"
                )
            elif hasattr(tool_data, "name"):
                tool_name = tool_data.name
            else:
                tool_name = self._state.last_tool_name or "unknown"

            # 不发送 task 工具的 tool/end 事件
            if tool_name != "task":
                chunks.append(
                    StreamChunk(
                        event=self.formatter.make_tool_end_event(
                            tool_name,
                            namespace=namespace,
                            subagent_id=subagent_id,
                            subagent_name=subagent_name,
                        )
                    )
                )

        if "__interrupt__" in data:
            interrupt_chunk = self._handle_interrupt(subgraph_path, data, mode)
            if (
                interrupt_chunk.event
                or interrupt_chunk.auto_resume
                or interrupt_chunk.auto_reject
            ):
                chunks.append(interrupt_chunk)

        return chunks

    def _handle_interrupt(
        self, subgraph_path: tuple, data: dict, mode: str
    ) -> StreamChunk:
        """Handle interrupt event"""
        interrupt_list = data.get("__interrupt__", [])
        if not interrupt_list:
            return StreamChunk()

        # 解析 namespace
        namespace = list(subgraph_path) if subgraph_path else None
        is_main_agent = not bool(subgraph_path)

        # 确定子代理信息
        subagent_id = None
        subagent_name = None

        if not is_main_agent and self._state.in_subagent:
            # 从 namespace 提取 ID
            for segment in subgraph_path:
                if isinstance(segment, str) and segment.startswith("tools:"):
                    subagent_id = segment.split(":", 1)[1]
                    break

            subagent_name = self._state.current_subagent_name

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
                # plan 模式下自动拒绝，让 LLM 继续运行并友好提示用户
                return StreamChunk(auto_reject=True)

        return StreamChunk(
            event=self.formatter.make_interrupt_event(
                {
                    "info": self._format_interrupt_info(request),
                    "taskName": TASK_DISPLAY_NAMES.get(tool_name, tool_name)
                    or tool_name,
                    "data": sanitize_for_json(interrupt.value),
                    "questions": self._parse_questions(
                        request.get("args", {}).get("questions")
                    ),
                },
                namespace=namespace,
                subagent_id=subagent_id,
                subagent_name=subagent_name,
            )
        )

    def _parse_questions(self, questions: Any) -> list[dict]:
        """Parse questions from args, handling string or list format"""
        if questions is None:
            return []
        if isinstance(questions, list):
            return questions
        if isinstance(questions, str):
            # 清理可能存在的错误格式
            clean_str = questions.split('", "answers"')[0]
            try:
                import json

                return json.loads(clean_str)
            except (json.JSONDecodeError, ValueError):
                return []
        return []

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
            questions = self._parse_questions(args.get("questions"))
            return f"Agent 提出了 {len(questions)} 个问题"
        else:
            return "正在执行操作"
