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
            interrupt_on={"execute": True, "write_file": True}
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

        async for event in self.compiled_agent.astream_events(
            {"messages": [HumanMessage(content=message)]},
            config=config,
            version="v2"
        ):
            print(event)
            yield self._format_event(event)

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
        return {"success": True, "message": "Resumed successfully", "messages": json.dump(result['messages'])}

    def _format_event(self, event: Any) -> str:
        event_type = event.get("event", "")
        data = event.get("data", {})

        if event_type == "on_chat_model_stream":
            chunk = data.get("chunk", {})
            # Handle both dict and AIMessageChunk objects
            if isinstance(chunk, dict):
                content = chunk.get("content", "")
            else:
                # AIMessageChunk object
                content = getattr(chunk, "content", "")
            if content:
                return f"data: {content}\n\n"
        return ""
