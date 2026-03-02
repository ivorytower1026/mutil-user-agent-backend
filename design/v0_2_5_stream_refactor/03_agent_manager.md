# 03. AgentManager 重构

## 概述

重构 `AgentManager` 类，使用 `AgentStreamRunner` 和 `ResumeCommandBuilder`。

## 重构后的代码

```python
import asyncio
import logging
from typing import AsyncIterator

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.types import Command

from src.config import settings
from src.database import SessionLocal, Thread
from src.llm_manager import get_llm_manager
from src.utils.get_logger import get_logger
from src.utils.langfuse_monitor import init_langfuse
from src.agent_utils.stream import AgentStreamRunner, SSEFormatter
from src.agent_utils.resume_builder import ResumeCommandBuilder
from src.agent_utils.session import SessionManager
from src.agent_utils.types import InterruptAction

logger = get_logger("main-agent")


class AgentManager:
    def __init__(self):
        self.checkpointer = None
        self.compiled_agent = None
        # ... 其他初始化 ...
        self.formatter = SSEFormatter()
        self.stream_runner: AgentStreamRunner | None = None
        self.session_manager: SessionManager | None = None

    async def init(self):
        # ... 现有初始化逻辑 ...
        await self._build_agent()
        
        # 初始化流处理器
        self.stream_runner = AgentStreamRunner(self.compiled_agent, self.formatter)
        self.session_manager = SessionManager(self.compiled_agent)
        
        logger.info("[AgentManager] Initialized")

    # ... _build_agent 等方法保持不变 ...

    async def stream_chat(
        self,
        thread_id: str,
        message: str,
        files: list[str] | None = None,
        mode: str = "build",
    ) -> AsyncIterator[str]:
        """
        流式聊天
        """
        queue: asyncio.Queue[str | None] = asyncio.Queue()
        pending = {"count": 0}

        messages = self._build_messages(message, files, mode)
        initial_input = {"messages": messages}

        async def agent_task():
            pending["count"] += 1
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
                await queue.put(self.formatter.error(str(e)))
            finally:
                pending["count"] -= 1
                if pending["count"] == 0:
                    await queue.put(None)

        async def title_task():
            if not self._needs_title(thread_id):
                return
            pending["count"] += 1
            try:
                title = await self._generate_title(thread_id, message)
                if title:
                    await queue.put(self.formatter.title_updated(title))
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

        yield self.formatter.done()

    async def stream_resume_interrupt(
        self,
        thread_id: str,
        action: str,
        answers: list[str] | None = None,
        mode: str = "build",
    ) -> AsyncIterator[str]:
        """
        恢复中断的会话
        """
        try:
            interrupt_action = InterruptAction(action)
        except ValueError:
            yield self.formatter.error(f"无效的 action: {action}")
            yield self.formatter.done()
            return

        snapshot = await self.compiled_agent.aget_state(
            {"configurable": {"thread_id": thread_id}}
        )

        resume_command = ResumeCommandBuilder.build(interrupt_action, snapshot, answers)

        if resume_command is None:
            error_msg = ResumeCommandBuilder.get_error_message(
                interrupt_action, snapshot, answers
            )
            yield self.formatter.error(error_msg)
            yield self.formatter.done()
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
            yield self.formatter.error(str(e))

        yield self.formatter.done()

    def _build_messages(self, message: str, files: list[str] | None, mode: str) -> list:
        """构建消息列表"""
        messages = []
        
        if files:
            file_list = "\n".join(f"- {path}" for path in files)
            messages.append(SystemMessage(
                content=f"当前对话中用户已上传的文件：\n{file_list}"
            ))

        if mode == "plan":
            messages.append(SystemMessage(
                content="""# Plan Mode
当前为思考模式，你只能进行只读操作：
- 禁止执行命令、写入文件、编辑文件
- 只能观察、分析、规划
请先制定计划，并友好提示用户切换到【编辑】模式。"""
            ))

        messages.append(HumanMessage(content=message))
        return messages

    def _needs_title(self, thread_id: str) -> bool:
        with SessionLocal() as db:
            thread = db.query(Thread).filter(Thread.thread_id == thread_id).first()
            return thread and thread.title is None

    async def _generate_title(self, thread_id: str, message: str) -> str | None:
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

    # ... 其他方法保持不变 ...
```

## 对比

### stream_chat

| 方面 | 旧代码 | 新代码 |
|------|--------|--------|
| 行数 | ~140 行 | ~50 行 |
| 流处理 | 内联 | 委托给 stream_runner |
| 工具事件解析 | 手动 | LangGraph tools 流模式 |

### stream_resume_interrupt

| 方面 | 旧代码 | 新代码 |
|------|--------|--------|
| 实现 | 委托给 InterruptHandler | 直接使用 ResumeCommandBuilder |
| 行数 | ~15 行 + InterruptHandler | ~40 行（自包含） |

## 优势

1. **代码量减少** - 从 ~350 行减少到 ~150 行
2. **职责清晰** - 流处理 vs 业务逻辑分离
3. **使用原生能力** - 利用 LangGraph tools 流模式
4. **易于测试** - 可以单独测试 Runner 和 Builder
