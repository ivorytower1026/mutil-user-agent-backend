import asyncio
import json
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
from src.memory_manager import get_memory_manager

from psycopg_pool import AsyncConnectionPool
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver


from src.agent_utils.formatter import SSEFormatter
from src.agent_utils.session import SessionManager
from src.agent_utils.types import InterruptAction
from src.agent_utils.stream import AgentStreamRunner
from src.agent_utils.resume_builder import ResumeCommandBuilder
from src.utils.inject_hint import inject_hint
from datetime import datetime

logger = get_logger("main-agent")

AUTO_APPROVE_TOOLS = {"execute", "write_file", "edit_file"}

MEMORY_SYSTEM_PROMPT = """
# 记忆系统使用指南

你拥有一个智能记忆系统，可以保存和检索信息。合理使用记忆系统能让你更好地服务用户。

## 何时保存记忆

保存以下信息为长期记忆，这些信息会跨会话保留：

1. **用户偏好**
   - 喜欢的编程语言、框架、工具
   - 代码风格偏好（缩进、命名规范等）
   - 工作习惯（喜欢详细解释还是简洁输出）

2. **用户背景**
   - 职业角色（前端/后端/全栈/数据科学家等）
   - 技术栈（Spring、Django、React、Vue 等）
   - 项目领域（电商、金融、AI、物联网等）

3. **重要事实**
   - 项目配置信息（数据库连接、API 端点）
   - 团队约定（Git 分支策略、代码审查流程）
   - 业务规则（折扣计算、用户权限）

示例：
- 用户说"我喜欢用 TypeScript" → add_memory("用户偏好使用 TypeScript", {"category": "preference"})
- 用户说"我是后端工程师，主要用 Java" → add_memory("用户是后端工程师，技术栈为 Java", {"category": "background"})

## 何时检索记忆

在以下情况下，主动调用 search_memories 检索相关信息：

1. **用户询问过往信息**
   - "我之前说过我喜欢什么语言？"
   - "我的技术栈是什么？"

2. **需要上下文做决策**
   - 选择技术方案时，参考用户偏好
   - 编写代码时，遵循用户的代码风格
   - 解释概念时，根据用户背景调整深度

示例：
- 用户问"我应该用哪个框架？" → search_memories("技术栈 框架偏好")
- 用户说"继续" → search_memories("任务进度 当前任务")

## 记忆管理原则

1. **质量优于数量**
   - 只保存真正有价值的信息
   - 避免保存临时性、易变的信息

2. **及时更新**
   - 当用户纠正信息时，保存新版本
   - Mem0 会自动处理冲突检测和更新

3. **主动检索**
   - 不要等用户提醒才去查记忆
   - 在需要决策时，主动参考用户偏好

## 注意事项

1. **隐私保护**
   - 不要保存敏感信息（密码、密钥、个人隐私）
   - 如果不确定，先询问用户

2. **避免冗余**
   - 不要重复保存相同信息
   - Mem0 会自动去重，但你应该有意识避免

3. **上下文相关性**
   - 保存时添加 metadata，方便后续检索
   - 使用有意义的标签（category、task、domain 等）

4. **性能考虑**
   - 不要过度频繁调用记忆工具
   - 检索时设置合理的 limit（默认 5）

注：会话级短期记忆（如当前任务进度、临时计算结果）由 LangGraph 自动管理，无需手动保存。
"""

DEFAULT_SYSTEM_PROMPT = f"""
用户的工作目录在/workspace中，若无明确要求，请在/workspace目录【及子目录】下执行操作,
当你不明确用户需求时，可以调用提问工具向用户提问(可以同时提多个问题)，这个提问工具最多调用两次
优先尝试使用已有的skill完成任务。
你有子agent时，优先尝试使用子agent处理专门的任务。
现在的时间是{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

{MEMORY_SYSTEM_PROMPT}
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
        self.stream_runner: AgentStreamRunner | None = None
        self.session_manager: SessionManager | None = None
        self.mcp_manager = get_mcp_manager()
        self.config_manager = get_agent_config_manager()
        self.memory_manager = get_memory_manager()

    async def init(self):
        await self.pool.open()
        self.checkpointer = AsyncPostgresSaver(self.pool)
        await self.checkpointer.setup()

        await self.mcp_manager.init()

        with SessionLocal() as db:
            self.config_manager.load_configs(db)
            self.memory_manager.init(db)

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

        # Add memory tools
        memory_tools = self.memory_manager.create_tools()
        all_tools = mcp_tools + memory_tools

        skills_paths = self._build_skills_paths(main_config.skills or [])

        system_prompt = DEFAULT_SYSTEM_PROMPT + main_config.system_prompt

        self.compiled_agent = create_deep_agent(
            model=big_llm,
            backend=lambda runtime: get_thread_backend(
                self._get_thread_id(runtime) or "default"
            ),
            checkpointer=self.checkpointer,
            tools=all_tools,
            interrupt_on={
                "execute": True,
                "write_file": True,
                "edit_file": True,
                "ask_user": {
                    "allowed_decisions": ["edit"],
                    "description": "Agent 请求用户回答问题",
                },
            },
            skills=[settings.CONTAINER_SKILLS_DIR],
            system_prompt=system_prompt,
            subagents=subagents,
        )

        self.stream_runner = AgentStreamRunner(
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
                "skills": [settings.CONTAINER_SKILLS_DIR],
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
        """Stream chat using AgentStreamRunner"""
        queue: asyncio.Queue[str | None] = asyncio.Queue()
        pending = {"count": 2}

        with SessionLocal() as db:
            thread = db.query(Thread).filter(Thread.thread_id == thread_id).first()
            need_title = thread and thread.title is None

        messages = self._build_messages(message, files, mode)
        initial_input = {"messages": messages}

        async def agent_task():
            try:
                handler, _ = init_langfuse()
                callbacks = [handler] if handler else []
                
                async for event in self.stream_runner.run(
                    thread_id=thread_id,
                    initial_input=initial_input,
                    mode=mode,
                    callbacks=callbacks,
                ):
                    await queue.put(event)
            except Exception as e:
                logger.exception("agent_task error")
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
                title = await self._generate_title(thread_id, message)
                if title:
                    await queue.put(self.sse_formatter.make_title_updated_event(title))
            except Exception as e:
                logger.warning("Title generation failed: %s", e)
            finally:
                pending["count"] -= 1
                if pending["count"] == 0:
                    await queue.put(None)

        asyncio.create_task(agent_task())
        asyncio.create_task(title_task())

        while True:
            item = await queue.get()
            if item is None:
                break
            yield item

        yield self.sse_formatter.make_done_event()

    def _build_messages(self, message: str, files: list[str] | None, mode: str) -> list:
        """Build message list"""
        enhanced_msg = message
        
        if files:
            file_list = "\n".join(f"- {path}" for path in files)
            file_hint = f"这是用户刚刚上传的文件，后续用户可能会询问你有关这些文件的内容：\n{file_list}"
            enhanced_msg = inject_hint(enhanced_msg, file_hint)

        if mode == "plan":
            plan_hint = """# Plan Mode - 思考模式

当前为**思考模式**，你只能进行只读操作：
- ✅ 可以：读取文件、搜索、分析、规划、向用户提问
- ❌ 禁止：执行命令、写入文件、编辑文件

如果需要执行写入操作，请**直接告诉用户**：
"当前为思考模式，请切换到【执行】模式后再继续操作。"

**不要尝试调用 write_file、edit_file、execute 等工具**，这些操作在思考模式下会被自动拒绝。"""
            enhanced_msg = inject_hint(enhanced_msg, plan_hint)
        
        messages = [HumanMessage(content=enhanced_msg)]
        return messages

    async def _generate_title(self, thread_id: str, message: str) -> str | None:
        """Generate thread title"""
        try:
            with SessionLocal() as db:
                flash_llm = get_llm_manager().get_flash_llm(db)
                prompt = f"用5-10个字概括主题，只返回标题：{message[:100]}"
                response = await flash_llm.ainvoke(prompt)
            title = str(response.content).strip()[:20]
            
            with SessionLocal() as db:
                thread = db.query(Thread).filter(Thread.thread_id == thread_id).first()
                if thread and thread.title is None:
                    thread.title = title
                    db.commit()
            
            return title
        except Exception as e:
            logger.warning("Title generation failed: %s", e)
            return None

    async def stream_resume_interrupt(
        self,
        thread_id: str,
        action: str,
        answers: list[str] | None = None,
        mode: str = "build",
    ) -> AsyncIterator[str]:
        """Resume interrupted session using ResumeCommandBuilder and AgentStreamRunner"""
        try:
            interrupt_action = InterruptAction(action)
        except ValueError:
            yield self.sse_formatter.make_error_event(f"无效的 action: {action}")
            yield self.sse_formatter.make_done_event()
            return

        snapshot = await self.compiled_agent.aget_state(
            {"configurable": {"thread_id": thread_id}}
        )

        resume_command = ResumeCommandBuilder.build(interrupt_action, snapshot, answers)

        if resume_command is None:
            error_msg = ResumeCommandBuilder.get_error_message(
                interrupt_action, snapshot, answers
            )
            yield self.sse_formatter.make_error_event(error_msg)
            yield self.sse_formatter.make_done_event()
            return

        try:
            handler, _ = init_langfuse()
            callbacks = [handler] if handler else []
            
            async for event in self.stream_runner.run(
                thread_id=thread_id,
                initial_input=resume_command,
                mode=mode,
                callbacks=callbacks,
            ):
                yield event
        except Exception as e:
            logger.exception("stream_resume error")
            yield self.sse_formatter.make_error_event(str(e))

        yield self.sse_formatter.make_done_event()

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
