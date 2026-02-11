import json
import os
import uuid
from typing import Any, AsyncIterator

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import MemorySaver
from deepagents import create_deep_agent
from langgraph.types import Command

from src.config import llm
from src.docker_sandbox import get_thread_backend
from src.utils.langfuse_monitor import init_langfuse


class AgentManager:
    def __init__(self):
        self.checkpointer = MemorySaver()
        self.compiled_agent = create_deep_agent(
            model=llm,
            backend=lambda runtime: get_thread_backend(self._get_thread_id(runtime) or "default"),
            checkpointer=self.checkpointer,
            interrupt_on={"execute": True, "write_file": True},
            system_prompt="用户的工作目录在/workspace中，若无明确要求，请在/workspace目录【及子目录】下执行操作"
        )
        print(f"[AgentManager] Initialized")

    def _get_thread_id(self, runtime: Any) -> str | None:
        config = getattr(runtime, "config", None)
        if config and isinstance(config, dict):
            configurable = config.get("configurable", {})
            return configurable.get("thread_id")
        return None

    async def create_session(self) -> str:
        thread_id = f"user-{uuid.uuid4()}"
        get_thread_backend(thread_id)
        return thread_id

    async def stream_chat(self, thread_id: str, message: str) -> AsyncIterator[str]:
        handler, _ = init_langfuse()
        config: RunnableConfig = {"configurable": {"thread_id": thread_id},"callbacks":[handler]}

        try:
            async for event in self.compiled_agent.astream_events(
                {"messages": [HumanMessage(content=message)]},
                config=config,
                version="v2"
            ):
                formatted = self._format_event(event)
                if formatted:
                    yield formatted
        except Exception as e:
            yield self._make_sse("error", {"message": str(e)})
            raise

        # Send done event at the end
        yield self._make_sse("done", {})

    async def resume_interrupt(self, thread_id: str, action: str):
        if action not in ["continue", "cancel"]:
            raise ValueError("Action must be 'continue' or 'cancel'")

        handler, _ = init_langfuse()
        config: RunnableConfig = {"configurable": {"thread_id": thread_id},"callbacks":[handler]}

        if action == "cancel":
            # 对于 cancel，需要传递拒绝决策
            result = await self.compiled_agent.ainvoke(
                Command(resume={"decisions": [{"type": "reject"}]}),
                config=config
            )
            return {"success": True, "message": "Operation cancelled"}

        # 对于 continue，传递批准决策
        result = await self.compiled_agent.ainvoke(
            Command(resume={"decisions": [{"type": "approve"}]}),
            config=config
        )
        return {"success": True, "message": "Resumed successfully", "lasted_messages": result['messages'][-1].content}

    def _format_event(self, event: Any) -> str | None:
        event_type = event.get("event", "")
        data = event.get("data", {})
        name = event.get("name", "")

        # 1. LLM 内容流式输出 - 核心
        if event_type == "on_chat_model_stream":
            chunk = data.get("chunk", {})
            content = self._extract_content(chunk)
            if content:
                return self._make_sse("content", {"content": content})

        # 2. 工具调用开始 - 显示执行进度
        elif event_type == "on_tool_start":
            input_data = data.get("input", {})
            return self._make_sse("tool_start", {
                "tool": name,
                "input": self._sanitize_for_json(input_data)
            })

        # 3. 工具调用结束 - 显示执行结果
        elif event_type == "on_tool_end":
            output_data = data.get("output", {})
            return self._make_sse("tool_end", {
                "tool": name,
                "output": self._sanitize_for_json(output_data)
            })

        # 4. 模型生成结束 - 通知流结束
        elif event_type == "on_chat_model_end":
            output = data.get("output", {})
            content = self._extract_content(output)
            if content:
                return self._make_sse("content", {"content": content, "is_final": True})

        # 5. 解析器流式输出（如果使用结构化输出）
        elif event_type == "on_parser_stream":
            chunk = data.get("chunk")
            if chunk:
                return self._make_sse("structured", {"data": self._sanitize_for_json(chunk)})

        # 6. 链的流式输出 - 过滤掉调试信息，只保留有用的部分
        elif event_type == "on_chain_stream":
            chunk = data.get("chunk")
            if chunk and isinstance(chunk, dict):
                # 只输出非空的、有意义的chain数据
                meaningful_data = {k: v for k, v in chunk.items() if v is not None and v != "" and v != {}}
                if meaningful_data:
                    return self._make_sse("chain", {"data": self._sanitize_for_json(meaningful_data)})

        return None

    def _extract_content(self, chunk: Any) -> str:
        if isinstance(chunk, dict):
            return chunk.get("content", "")
        return getattr(chunk, "content", "")

    def _make_sse(self, event_type: str, data: dict) -> str:
        event_data = {"type": event_type, **data}
        return f"data: {json.dumps(event_data, ensure_ascii=False)}\n\n"

    def _sanitize_tool_input(self, input_data: Any) -> Any:
        if isinstance(input_data, dict) and "content" in input_data:
            return {k: v for k, v in input_data.items() if k != "content"}
        return input_data

    def _sanitize_tool_output(self, output_data: Any) -> Any:
        if isinstance(output_data, dict):
            return {k: v for k, v in output_data.items() if k not in ["content", "messages"]}
        return output_data

    def _sanitize_for_json(self, data: Any) -> Any:
        def _convert(obj: Any) -> Any:
            if isinstance(obj, (str, int, float, bool, type(None))):
                return obj
            elif isinstance(obj, dict):
                return {k: _convert(v) for k, v in obj.items()}
            elif isinstance(obj, (list, tuple)):
                return [_convert(item) for item in obj]
            else:
                return str(obj)

        if isinstance(data, dict):
            filtered = {k: v for k, v in data.items() if k not in ["content", "messages"]}
            return _convert(filtered)
        return _convert(data)
