import asyncio
import json
import logging
import time
from typing import Any, AsyncIterator

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import BaseTool, StructuredTool
from deepagents import create_deep_agent
from deepagents.middleware.subagents import SubAgent
from typing import Annotated

from src.config import settings
from src.database import SessionLocal, Thread
from src.llm_manager import get_llm_manager
from src.docker_sandbox import get_thread_backend
from src.utils.get_logger import get_logger
from src.utils.langfuse_monitor import init_langfuse
from src.mcp_manager import get_mcp_manager
from src.agent_config_manager import get_agent_config_manager
from src.simple_skill_manager import get_skills_dir

from psycopg_pool import AsyncConnectionPool
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from langgraph.types import Command

from src.agent_utils.formatter import SSEFormatter, StreamDataFormatter
from src.agent_utils.interrupt import InterruptHandler
from src.agent_utils.session import SessionManager
from src.agent_utils.types import InterruptAction
from datetime import datetime;
logger = get_logger("main-agent")

AUTO_APPROVE_TOOLS = {"execute", "write_file", "edit_file"}

DEFAULT_SYSTEM_PROMPT = f"""
用户的工作目录在/workspace中，若无明确要求，请在/workspace目录【及子目录】下执行操作,
当你不明确用户需求时，可以调用提问工具向用户提问(可以同时提多个问题)，这个提问工具最多调用两次
优先尝试使用已有的skill完成任务。
你有子agent时，优先尝试使用子agent处理专门的任务。
现在的时间是{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
"""

FIX_PROMPT = f"""现在的时间是{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}"""

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
        self.mcp_manager = get_mcp_manager()
        self.config_manager = get_agent_config_manager()

    async def init(self):
        await self.pool.open()
        self.checkpointer = AsyncPostgresSaver(self.pool)
        await self.checkpointer.setup()

        await self.mcp_manager.init()

        with SessionLocal() as db:
            self.config_manager.load_configs(db)

        await self._build_agent()

        logger.info("[AgentManager] Initialized with AsyncPostgresSaver")

    async def _build_agent(self):
        """Build agent with current configuration."""
        with SessionLocal() as db:
            main_config = self.config_manager.get_main_config(db)
            subagent_configs = self.config_manager.get_subagent_configs(db)
            big_llm = get_llm_manager().get_big_llm(db)

            subagents = await self._build_subagents(
                subagent_configs, main_config.subagents or [], db
            )

        mcp_tools = []
        for server_name in main_config.mcp_servers or []:
            tools = await self.mcp_manager.get_all_tools(server_name)
            mcp_tools.extend(tools)
        mcp_tools.append(self._create_ask_user_tool())

        skills_paths = self._build_skills_paths(main_config.skills or [])

        system_prompt = DEFAULT_SYSTEM_PROMPT + main_config.system_prompt

        self.compiled_agent = create_deep_agent(
            model=big_llm,
            backend=lambda runtime: get_thread_backend(
                self._get_thread_id(runtime) or "default"
            ),
            checkpointer=self.checkpointer,
            tools=mcp_tools,
            interrupt_on={
                "execute": True,
                "write_file": True,
                "edit_file": True,
                "ask_user": {
                    "allowed_decisions": ["edit"],
                    "description": "Agent 请求用户回答问题",
                },
            },
            skills=skills_paths if skills_paths else [settings.CONTAINER_SKILLS_DIR],
            system_prompt=system_prompt,
            subagents=subagents,
        )

        self.interrupt_handler = InterruptHandler(
            self.compiled_agent, self.sse_formatter
        )
        self.session_manager = SessionManager(self.compiled_agent)

        logger.info(
            f"[AgentManager] Built agent with {len(mcp_tools)} tools, {len(skills_paths)} skills, {len(subagents)} subagents"
        )

    def _build_skills_paths(self, skill_names: list[str]) -> list[str]:
        """Build skills paths from skill names."""
        skills_dir = settings.CONTAINER_SKILLS_DIR
        return skills_dir

    async def _build_subagents(
        self, subagent_configs: list, enabled_names: list[str], db
    ) -> list[SubAgent]:
        """Build subagents from configurations."""
        subagents = []
        llm_manager = get_llm_manager()

        for config in subagent_configs:
            if config.name not in enabled_names:
                continue

            tools = []
            for server_name in config.mcp_servers or []:
                server_tools = await self.mcp_manager.get_all_tools(server_name)
                tools.extend(server_tools)
            skills_paths = self._build_skills_paths(config.skills or [])

            subagent: SubAgent = {
                "name": config.name,
                "description": config.description or f"Subagent: {config.name}",
                "system_prompt": config.system_prompt + FIX_PROMPT,
                "tools": tools,
                "skills": skills_paths if skills_paths else None,
            }

            if config.model:
                if config.model == "big":
                    subagent["model"] = llm_manager.get_big_llm(db)
                elif config.model == "flash":
                    subagent["model"] = llm_manager.get_flash_llm(db)
                else:
                    subagent["model"] = config.model

            subagents.append(subagent)

        return subagents

    async def reload_configs(self) -> bool:
        """Reload configurations and rebuild agent."""
        try:
            with SessionLocal() as db:
                await self.mcp_manager.reload(db)
                self.config_manager.load_configs(db)

            await self._build_agent()
            logger.info("[AgentManager] Configs reloaded and agent rebuilt")
            return True
        except Exception as e:
            logger.exception(f"[AgentManager] Failed to reload configs: {e}")
            return False

    def _get_thread_id(self, runtime: Any) -> str | None:
        config = getattr(runtime, "config", None)
        if config and isinstance(config, dict):
            configurable = config.get("configurable", {})
            return configurable.get("thread_id")
        return None

    def _create_ask_user_tool(self) -> BaseTool:
        def ask_user(
            questions: Annotated[
                list[dict], "问题列表，每个问题包含 question 和 options"
            ],
            answers: Annotated[list[str] | None, "用户答案（恢复时注入）"] = None,
        ) -> str:
            if answers:
                return json.dumps(answers, ensure_ascii=False)
            return "Waiting for user response..."

        return StructuredTool.from_function(
            name="ask_user",
            description="向用户提问并等待回答，给出问题可能的方案。问题格式: [{question: string, options: [{label: string, value: string}]}]",
            func=ask_user,
        )

    async def create_session(self, user_id: str) -> str:
        return self.session_manager.create(user_id)

    async def stream_chat(
        self,
        thread_id: str,
        message: str,
        files: list[str] | None = None,
        mode: str = "build",
    ) -> AsyncIterator[str]:
        queue: asyncio.Queue[str | None] = asyncio.Queue()
        pending = {"count": 2}

        with SessionLocal() as db:
            thread = db.query(Thread).filter(Thread.thread_id == thread_id).first()
            need_title = thread and thread.title is None

        async def agent_task():
            try:
                handler, _ = init_langfuse()
                callbacks = [handler] if handler else []
                config = {
                    "configurable": {"thread_id": thread_id},
                    "callbacks": callbacks,
                }

                messages = []
                if files:
                    file_list = "\n".join(f"- {path}" for path in files)
                    messages.append(
                        SystemMessage(
                            content=f"当前对话中用户已上传的文件：\n{file_list}"
                        )
                    )

                if mode == "plan":
                    messages.append(
                        SystemMessage(
                            content="""# Plan Mode

当前为思考模式，你只能进行只读操作：
- 禁止执行命令、写入文件、编辑文件
- 只能观察、分析、规划
- 可以向用户提问澄清需求

请先制定计划，并友好提示用户当前处于思考模式，请用户切换到【编辑】模式后再执行操作。"""
                        )
                    )

                messages.append(HumanMessage(content=message))

                current_input = {"messages": messages}

                while True:
                    auto_resume = False

                    async for stream_mode, data in self.compiled_agent.astream(
                        current_input,
                        config=config,
                        stream_mode=["messages", "updates"],
                    ):
                        tool_name = self.stream_formatter.extract_interrupt_tool_name(
                            data
                        )

                        if tool_name in AUTO_APPROVE_TOOLS:
                            if mode == "build":
                                auto_resume = True
                                break
                            else:
                                await self.compiled_agent.ainvoke(
                                    Command(resume={"decisions": [{"type": "reject"}]}),
                                    config,
                                )
                                await queue.put(
                                    self.sse_formatter.make_error_event(
                                        "当前为思考模式，请切换到 build 模式执行操作"
                                    )
                                )
                                return
                        else:
                            formatted = self.stream_formatter.format_stream_data(
                                stream_mode, data
                            )
                            if formatted:
                                await queue.put(formatted)

                    if auto_resume:
                        current_input = Command(
                            resume={"decisions": [{"type": "approve"}]}
                        )
                    else:
                        break

            except Exception as e:
                logger.exception("Error in agent_task")
                await queue.put(self.sse_formatter.make_error_event(str(e)))
            finally:
                pending["count"] -= 1
                if pending["count"] == 0:
                    await queue.put(None)

        async def title_task():
            if not need_title:
                pending["count"] -= 1
                return
            try:
                with SessionLocal() as db:
                    flash_llm = get_llm_manager().get_flash_llm(db)
                    prompt = f"用5-10个字概括主题，只返回标题：{message[:100]}"
                    response = await flash_llm.ainvoke(prompt)
                title = str(response.content).strip()[:20]

                with SessionLocal() as db:
                    thread = (
                        db.query(Thread).filter(Thread.thread_id == thread_id).first()
                    )
                    if thread and thread.title is None:
                        thread.title = title
                        db.commit()

                await queue.put(self.sse_formatter.make_title_updated_event(title))
            except Exception as e:
                logger.warning("Title generation failed: %s", e)
            finally:
                pending["count"] -= 1
                if pending["count"] == 0:
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
        answers: list[str] | None = None,
        mode: str = "build",
    ) -> AsyncIterator[str]:
        handler, _ = init_langfuse()

        async for chunk in self.interrupt_handler.resume(
            thread_id=thread_id,
            action=InterruptAction(action),
            answers=answers,
            langfuse_handler=handler if handler else None,
            mode=mode,
        ):
            yield chunk

    async def get_status(self, thread_id: str) -> dict:
        return await self.session_manager.get_status(thread_id)

    async def get_history(self, thread_id: str) -> dict:
        return await self.session_manager.get_history(thread_id)

    async def list_sessions(
        self, user_id: str, page: int = 1, page_size: int = 20
    ) -> dict:
        return await self.session_manager.list_sessions(user_id, page, page_size)

    async def close(self):
        if self.pool:
            await self.pool.close()
            logger.info("[AgentManager] Connection pool closed")
