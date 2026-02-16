import asyncio
import json
import logging
from typing import Any, AsyncIterator

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import BaseTool, StructuredTool
from deepagents import create_deep_agent
from typing import Annotated

from src.config import big_llm, settings, flash_llm
from src.database import SessionLocal, Thread
from src.docker_sandbox import get_thread_backend
from src.utils.langfuse_monitor import init_langfuse

from psycopg_pool import AsyncConnectionPool
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from src.agent_utils.formatter import SSEFormatter, StreamDataFormatter
from src.agent_utils.interrupt import InterruptHandler
from src.agent_utils.session import SessionManager
from src.agent_utils.types import InterruptAction

logger = logging.getLogger(__name__)


class AgentManager:
    def __init__(self):
        self.checkpointer = None
        self.compiled_agent = None
        self.pool = AsyncConnectionPool(
            conninfo=settings.DATABASE_URL,
            max_size=20,
            kwargs={"autocommit": True, "prepare_threshold": 0},
            open=False,
        )
        self.sse_formatter = SSEFormatter()
        self.stream_formatter = StreamDataFormatter(self.sse_formatter)
        self.interrupt_handler: InterruptHandler | None = None
        self.session_manager: SessionManager | None = None

    async def init(self):
        await self.pool.open()
        self.checkpointer = AsyncPostgresSaver(self.pool)
        await self.checkpointer.setup()

        self.compiled_agent = create_deep_agent(
            model=big_llm,
            backend=lambda runtime: get_thread_backend(
                self._get_thread_id(runtime) or "default"
            ),
            checkpointer=self.checkpointer,
            tools=[self._create_ask_user_tool()],
            interrupt_on={
                "execute": True,
                "write_file": True,
                "ask_user": {
                    "allowed_decisions": ["edit"],
                    "description": "Agent 请求用户回答问题"
                }
            },
            system_prompt="""
            用户的工作目录在/workspace中，若无明确要求，请在/workspace目录【及子目录】下执行操作,
            当你不明确用户需求时，可以调用提问工具向用户提问(可以同时提多个问题)，这个提问工具最多调用两次""",
        )
        
        self.interrupt_handler = InterruptHandler(self.compiled_agent, self.sse_formatter)
        self.session_manager = SessionManager(self.compiled_agent)
        
        logger.info("[AgentManager] Initialized with AsyncPostgresSaver")

    def _get_thread_id(self, runtime: Any) -> str | None:
        config = getattr(runtime, "config", None)
        if config and isinstance(config, dict):
            configurable = config.get("configurable", {})
            return configurable.get("thread_id")
        return None

    def _create_ask_user_tool(self) -> BaseTool:
        def ask_user(
            questions: Annotated[list[dict], "问题列表，每个问题包含 question 和 options"],
            answers: Annotated[list[str] | None, "用户答案（恢复时注入）"] = None,
        ) -> str:
            if answers:
                return json.dumps(answers, ensure_ascii=False)
            return "Waiting for user response..."
        
        return StructuredTool.from_function(
            name="ask_user",
            description="向用户提问并等待回答。问题格式: [{question: string, options: [{label: string, value: string, allow_custom?: boolean}]}]",
            func=ask_user,
        )

    async def create_session(self, user_id: str) -> str:
        return self.session_manager.create(user_id)

    async def stream_chat(
        self, 
        thread_id: str, 
        message: str, 
        files: list[str] | None = None
    ) -> AsyncIterator[str]:
        queue: asyncio.Queue[str | None] = asyncio.Queue()
        pending = {'count': 2}
        
        with SessionLocal() as db:
            thread = db.query(Thread).filter(Thread.thread_id == thread_id).first()
            need_title = thread and thread.title is None
        
        async def agent_task():
            try:
                handler, _ = init_langfuse()
                config = {"configurable": {"thread_id": thread_id}, "callbacks": [handler]}
                
                messages = []
                if files:
                    file_list = "\n".join(f"- {path}" for path in files)
                    messages.append(SystemMessage(
                        content=f"当前对话中用户已上传的文件：\n{file_list}"
                    ))
                messages.append(HumanMessage(content=message))
                
                async for stream_mode, data in self.compiled_agent.astream(
                    {"messages": messages},
                    config=config,
                    stream_mode=["messages", "updates"],
                ):
                    formatted = self.stream_formatter.format_stream_data(stream_mode, data)
                    if formatted:
                        await queue.put(formatted)
            except Exception as e:
                logger.exception("Error in agent_task")
                await queue.put(self.sse_formatter.make_error_event(str(e)))
            finally:
                pending['count'] -= 1
                if pending['count'] == 0:
                    await queue.put(None)
        
        async def title_task():
            if not need_title:
                pending['count'] -= 1
                return
            try:
                prompt = f"用5-10个字概括主题，只返回标题：{message[:100]}"
                response = await flash_llm.ainvoke(prompt)
                title = str(response.content).strip()[:20]
                
                with SessionLocal() as db:
                    thread = db.query(Thread).filter(Thread.thread_id == thread_id).first()
                    if thread and thread.title is None:
                        thread.title = title
                        db.commit()
                
                await queue.put(self.sse_formatter.make_title_updated_event(title))
            except Exception as e:
                logger.warning("Title generation failed: %s", e)
            finally:
                pending['count'] -= 1
                if pending['count'] == 0:
                    await queue.put(None)
        
        asyncio.create_task(title_task())
        asyncio.create_task(agent_task())

        while True:
            item = await queue.get()
            if item is None:
                break
            yield item
        
        yield self.sse_formatter.make_done_event()

    async def stream_resume_interrupt(
        self, 
        thread_id: str, 
        action: str,
        answers: list[str] | None = None
    ) -> AsyncIterator[str]:
        handler, _ = init_langfuse()
        
        async for chunk in self.interrupt_handler.resume(
            thread_id=thread_id,
            action=InterruptAction(action),
            answers=answers,
            langfuse_handler=handler,
        ):
            yield chunk

    async def get_status(self, thread_id: str) -> dict:
        return await self.session_manager.get_status(thread_id)

    async def get_history(self, thread_id: str) -> dict:
        return await self.session_manager.get_history(thread_id)

    async def list_sessions(self, user_id: str, page: int = 1, page_size: int = 20) -> dict:
        return await self.session_manager.list_sessions(user_id, page, page_size)
