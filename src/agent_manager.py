import asyncio
import json
import os
import uuid
from typing import Any, AsyncIterator

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from deepagents import create_deep_agent
from langgraph.types import Command

from src.config import big_llm, settings, flash_llm
from src.database import SessionLocal, Thread
from src.docker_sandbox import get_thread_backend
from src.utils.langfuse_monitor import init_langfuse

from psycopg_pool import AsyncConnectionPool
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

class AgentManager:
    def __init__(self):
        self.checkpointer = None
        self.compiled_agent = None
        self.pool = AsyncConnectionPool(
            conninfo=settings.DATABASE_URL,
            max_size=20,
            kwargs={"autocommit": True, "prepare_threshold": 0},
            open=False,  # 不在构造里自动打开
        )

    async def init(self):
        # 👉 必须在 async 上下文里 open pool
        await self.pool.open()
        self.checkpointer = AsyncPostgresSaver(self.pool)
        await self.checkpointer.setup()

        self.compiled_agent = create_deep_agent(
            model=big_llm,
            backend=lambda runtime: get_thread_backend(
                self._get_thread_id(runtime) or "default"
            ),
            checkpointer=self.checkpointer,
            interrupt_on={"execute": True, "write_file": True},
            system_prompt="用户的工作目录在/workspace中，若无明确要求，请在/workspace目录【及子目录】下执行操作",
        )
        print("[AgentManager] Initialized with AsyncPostgresSaver")

    def _get_thread_id(self, runtime: Any) -> str | None:
        config = getattr(runtime, "config", None)
        if config and isinstance(config, dict):
            configurable = config.get("configurable", {})
            return configurable.get("thread_id")
        return None

    async def create_session(self, user_id: str) -> str:
        """Create a new session for a user.
        
        Args:
            user_id: The user ID
            
        Returns:
            thread_id: Format is {user_id}-{uuid}
        """
        thread_id = f"{user_id}-{uuid.uuid4()}"
        get_thread_backend(thread_id)
        
        with SessionLocal() as db:
            db.add(Thread(thread_id=thread_id, user_id=user_id))
            db.commit()
        
        return thread_id

    async def stream_chat(self, thread_id: str, message: str) -> AsyncIterator[str]:
        """Stream chat with parallel title generation."""
        queue: asyncio.Queue[str | None] = asyncio.Queue()
        pending = {'count': 2}
        
        with SessionLocal() as db:
            thread = db.query(Thread).filter(Thread.thread_id == thread_id).first()
            need_title = thread and thread.title is None
        
        async def agent_task():
            try:
                handler, _ = init_langfuse()
                config = {"configurable": {"thread_id": thread_id}, "callbacks": [handler]}
                
                async for stream_mode, data in self.compiled_agent.astream(
                    {"messages": [HumanMessage(content=message)]},
                    config=config,
                    stream_mode=["messages", "updates"],
                ):
                    formatted = self._format_stream_data(stream_mode, data)
                    if formatted:
                        await queue.put(formatted)
            except Exception as e:
                await queue.put(self._make_sse("error", {"message": str(e)}))
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
                
                await queue.put(self._make_sse("title_updated", {"title": title}))
            except Exception as e:
                print(f"[AgentManager] Title generation failed: {e}")
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
        
        yield self._make_sse("done", {})
    
    def _format_stream_data(self, stream_mode: str, data: Any) -> str | None:
        """Format stream data to SSE string."""
        if stream_mode == "messages":
            if isinstance(data, tuple) and len(data) == 2:
                msg, metadata = data
                if hasattr(msg, "content") and msg.content:
                    return self._make_sse("content", {"content": msg.content})
        
        elif stream_mode == "updates":
            if isinstance(data, dict):
                if "__interrupt__" in data:
                    interrupt_list = data["__interrupt__"]
                    if interrupt_list:
                        interrupt = interrupt_list[0]
                        requests = interrupt.value.get("action_requests", [])
                        if requests:
                            request = requests[0]
                            return self._make_sse("interrupt", {
                                "info": request.get("description", ""),
                                "taskName": request.get("name", "Unknown"),
                                "data": self._sanitize_for_json(interrupt.value)
                            })
        return None

    async def stream_resume_interrupt(self, thread_id: str, action: str) -> AsyncIterator[str]:
        if action not in ["continue", "cancel"]:
            raise ValueError("Action must be 'continue' or 'cancel'")

        handler, _ = init_langfuse()
        config: RunnableConfig = {"configurable": {"thread_id": thread_id}, "callbacks": [handler]}

        if action == "cancel":
            resume_command = Command(resume={"decisions": [{"type": "reject"}]})
        else:
            resume_command = Command(resume={"decisions": [{"type": "approve"}]})

        print(f"[DEBUG] stream_resume_interrupt: thread_id={thread_id}, action={action}")
        print(f"[DEBUG] resume_command={resume_command}")

        try:
            chunk_count = 0
            async for chunk in self.compiled_agent.astream(
                resume_command,
                config=config,
                stream_mode=["messages", "updates"],
                subgraphs=True,
            ):
                chunk_count += 1
                print(f"[DEBUG] Resume chunk #{chunk_count}: type={type(chunk)}, value={chunk}")
                formatted = self._format_astream_chunk(chunk)
                if formatted:
                    yield formatted
                else:
                    print(f"[DEBUG] Chunk formatted to None, yielding nothing")
            print(f"[DEBUG] Total chunks processed: {chunk_count}")
        except Exception as e:
            import traceback
            error_msg = f"{type(e).__name__}: {str(e)}"
            print(f"[ERROR] In stream_resume_interrupt: {error_msg}")
            traceback.print_exc()
            yield self._make_sse("error", {"message": error_msg})
            return
        finally:
            # Send done event at the end
            print(f"[DEBUG] Sending done event for action: {action}")
            yield self._make_sse("done", {"action": action})

    def _format_astream_chunk(self, chunk: Any) -> str | None:
        print(f"[DEBUG] _format_astream_chunk: type={type(chunk)}, len={len(chunk) if hasattr(chunk, '__len__') else 'N/A'}")
        if hasattr(chunk, '__len__'):
            print(f"[DEBUG] chunk={chunk}")
        
        if not isinstance(chunk, tuple):
            return None

        # astream 返回格式可能是 (mode, data) 的 tuple
        if len(chunk) == 3:
            mode = chunk[1]
            data = chunk[2]
            
            print(f"[DEBUG] mode={mode}, data_type={type(data)}")
            
            if mode == "messages":
                # 处理消息流 - data 可能是 LLM token 或 metadata
                if isinstance(data, tuple) and len(data) == 2:
                    token, metadata = data
                    if token:
                        if isinstance(token, str):
                            return self._make_sse("content", {"content": token})
                        elif hasattr(token, "content"):
                            return self._make_sse("content", {"content": getattr(token, "content", "")})
                        else:
                            return None
                elif isinstance(data, str):
                    return self._make_sse("content", {"content": data})
                else:
                    return None

            elif mode == "updates":
                # 处理状态更新
                if isinstance(data, dict):
                    if "__interrupt__" in data:
                        # 中断信息
                        interrupt_info = data["__interrupt__"]
                        if interrupt_info:
                            return self._make_sse("interrupt", {
                                "info": str(interrupt_info)
                            })

                    # 其他状态更新（节点状态等）
                    filtered_data = {k: v for k, v in data.items() 
                                   if k not in ["messages", "__interrupt__"] and v is not None and v != ""}
                    if filtered_data:
                        return self._make_sse("update", {"data": self._sanitize_for_json(filtered_data)})

        return None

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

        # 4. 模型生成结束 - 只发送结束标记
        elif event_type == "on_chat_model_end":
            return self._make_sse("content", {"is_final": True})

        # 5. 解析器流式输出（如果使用结构化输出）
        elif event_type == "on_parser_stream":
            chunk = data.get("chunk")
            if chunk:
                return self._make_sse("structured", {"data": self._sanitize_for_json(chunk)})

        return None

    def _extract_content(self, chunk: Any) -> str:
        if isinstance(chunk, dict):
            return chunk.get("content", "")
        return getattr(chunk, "content", "")

    def _make_sse(self, event_type: str, data: dict) -> str:
        event_name_map = {
            "content": "messages/partial",
            "tool_start": "tool/start",
            "tool_end": "tool/end",
            "interrupt": "interrupt",
            "update": "updates",
            "structured": "structured",
            "error": "error",
            "done": "end",
            "title_updated": "title_updated",
        }
        event_name = event_name_map.get(event_type, event_type)
        
        if event_type == "content":
            sanitized = self._convert_for_json(data)
        else:
            sanitized = self._sanitize_for_json(data)
        
        return f"event: {event_name}\ndata: {json.dumps(sanitized, ensure_ascii=False)}\n\n"

    def _sanitize_tool_input(self, input_data: Any) -> Any:
        if isinstance(input_data, dict) and "content" in input_data:
            return {k: v for k, v in input_data.items() if k != "content"}
        return input_data

    def _sanitize_tool_output(self, output_data: Any) -> Any:
        if isinstance(output_data, dict):
            return {k: v for k, v in output_data.items() if k not in ["content", "messages"]}
        return output_data

    def _convert_for_json(self, data: Any) -> Any:
        if isinstance(data, (str, int, float, bool, type(None))):
            return data
        elif isinstance(data, dict):
            return {k: self._convert_for_json(v) for k, v in data.items()}
        elif isinstance(data, (list, tuple)):
            return [self._convert_for_json(item) for item in data]
        else:
            return str(data)

    def _sanitize_for_json(self, data: Any) -> Any:
        if isinstance(data, dict):
            filtered = {k: v for k, v in data.items() if k not in ["content", "messages"]}
            return self._convert_for_json(filtered)
        return self._convert_for_json(data)

    async def get_status(self, thread_id: str) -> dict:
        config = {"configurable": {"thread_id": thread_id}}
        snapshot = await self.compiled_agent.aget_state(config)
        
        has_pending_tasks = bool(snapshot.tasks)
        status = "interrupted" if has_pending_tasks else "idle"
        
        interrupt_info = None
        if snapshot.tasks:
            for task in snapshot.tasks:
                if hasattr(task, "interrupts") and task.interrupts:
                    interrupt_info = {
                        "task_name": task.name,
                        "interrupts": [str(i) for i in task.interrupts]
                    }
                    break
        
        messages = snapshot.values.get("messages", [])
        
        return {
            "thread_id": thread_id,
            "status": status,
            "has_pending_tasks": has_pending_tasks,
            "interrupt_info": interrupt_info,
            "message_count": len(messages)
        }

    async def get_history(self, thread_id: str) -> dict:
        config = {"configurable": {"thread_id": thread_id}}
        snapshot = await self.compiled_agent.aget_state(config)
        messages = snapshot.values.get("messages", [])
        
        formatted_messages = []
        for msg in messages:
            role = "unknown"
            content = ""
            
            if hasattr(msg, "type"):
                msg_type = msg.type
                if msg_type == "human":
                    role = "user"
                elif msg_type == "ai":
                    role = "assistant"
                elif msg_type == "tool":
                    role = "tool"
                elif msg_type == "system":
                    role = "system"
            
            if hasattr(msg, "content"):
                content = str(msg.content) if msg.content else ""
            
            if role != "unknown" and content:
                formatted_messages.append({
                    "role": role,
                    "content": content
                })
        
        return {
            "thread_id": thread_id,
            "messages": formatted_messages
        }

    async def list_sessions(self, user_id: str, page: int = 1, page_size: int = 20) -> dict:
        """List all sessions for a user."""
        with SessionLocal() as db:
            query = db.query(Thread).filter(Thread.user_id == user_id)
            total = query.count()
            threads = query.order_by(Thread.created_at.desc()) \
                           .offset((page - 1) * page_size) \
                           .limit(page_size).all()
        
        result = []
        for t in threads:
            status = await self.get_status(t.thread_id)
            result.append({
                "thread_id": t.thread_id,
                "title": t.title,
                "created_at": t.created_at.isoformat() if t.created_at else None,
                "message_count": status["message_count"],
                "status": status["status"]
            })
        
        return {"threads": result, "total": total}
