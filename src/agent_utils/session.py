import uuid
from typing import Any

from src.database import SessionLocal, Thread
from src.docker_sandbox import get_thread_backend
from src.utils.inject_hint import filter_hints


class SessionManager:
    def __init__(self, compiled_agent: Any):
        self.agent = compiled_agent

    def create(self, user_id: str) -> str:
        thread_id = f"{user_id}-{uuid.uuid4()}"
        get_thread_backend(thread_id)

        with SessionLocal() as db:
            db.add(Thread(thread_id=thread_id, user_id=user_id))
            db.commit()

        return thread_id

    async def list_sessions(
        self, user_id: str, page: int = 1, page_size: int = 20
    ) -> dict:
        with SessionLocal() as db:
            query = db.query(Thread).filter(Thread.user_id == user_id)
            total = query.count()
            threads = (
                query.order_by(Thread.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
                .all()
            )

        result = []
        for t in threads:
            status = await self.get_status(t.thread_id)
            result.append(
                {
                    "thread_id": t.thread_id,
                    "title": t.title,
                    "created_at": t.created_at.isoformat() if t.created_at else None,
                    "message_count": status["message_count"],
                    "status": status["status"],
                }
            )

        return {"threads": result, "total": total}

    async def get_status(self, thread_id: str) -> dict:
        config = {"configurable": {"thread_id": thread_id}}
        snapshot = await self.agent.aget_state(config)

        has_pending_tasks = bool(snapshot.tasks)
        status = "interrupted" if has_pending_tasks else "idle"

        interrupt_info = None
        if snapshot.tasks:
            for task in snapshot.tasks:
                if hasattr(task, "interrupts") and task.interrupts:
                    interrupt_info = {
                        "task_name": task.name,
                        "interrupts": [str(i) for i in task.interrupts],
                    }
                    break

        messages = snapshot.values.get("messages", [])

        return {
            "thread_id": thread_id,
            "status": status,
            "has_pending_tasks": has_pending_tasks,
            "interrupt_info": interrupt_info,
            "message_count": len(messages),
        }

    async def get_history(self, thread_id: str) -> dict:
        config = {"configurable": {"thread_id": thread_id}}
        snapshot = await self.agent.aget_state(config)
        messages = snapshot.values.get("messages", [])

        formatted_messages = []
        subagent_context = None  # 跟踪当前子代理上下文

        for msg in messages:
            role = "unknown"
            content = ""

            if hasattr(msg, "type"):
                msg_type = msg.type
                content = (
                    str(msg.content) if hasattr(msg, "content") and msg.content else ""
                )

                if msg_type == "system":
                    continue

                if msg_type == "human":
                    role = "user"
                    content = filter_hints(content)
                elif msg_type == "ai":
                    role = "assistant"
                elif msg_type == "tool":
                    role = "tool"

            if role == "unknown":
                continue

            formatted_msg = {"role": role, "content": content}

            # 检测子代理调用
            if role == "assistant" and hasattr(msg, "tool_calls") and msg.tool_calls:
                tool_calls_data = []
                for tc in msg.tool_calls:
                    tc_name = (
                        getattr(tc, "name", "")
                        if hasattr(tc, "name")
                        else tc.get("name", "")
                    )
                    tc_args = (
                        getattr(tc, "args", {})
                        if hasattr(tc, "args")
                        else tc.get("args", {})
                    )

                    # 检查是否为子代理调用
                    if tc_name == "task":
                        subagent_name = (
                            tc_args.get("subagent_type", "unknown")
                            if isinstance(tc_args, dict)
                            else "unknown"
                        )
                        subagent_context = subagent_name
                        formatted_msg["is_subagent_call"] = True
                        formatted_msg["subagent_name"] = subagent_name
                        # 不将 task 工具添加到 toolCalls 中
                        continue

                    tool_call_entry = {"name": tc_name, "status": "completed"}

                    if tc_name == "write_todos" and "todos" in tc_args:
                        tool_call_entry["todos"] = tc_args["todos"]

                    tool_calls_data.append(tool_call_entry)

                if tool_calls_data:
                    formatted_msg["toolCalls"] = tool_calls_data

            # 如果在子代理上下文中，标记消息
            if subagent_context and role in ["assistant", "tool"]:
                formatted_msg["in_subagent"] = True
                formatted_msg["subagent_name"] = subagent_context

            # 过滤非子代理的工具消息（在更新 subagent_context 之前）
            if role == "tool" and not subagent_context:
                continue

            # ToolMessage 可能表示子代理结束
            if role == "tool" and hasattr(msg, "name") and msg.name == "task":
                subagent_context = None

            if content or formatted_msg.get("toolCalls") or formatted_msg.get("is_subagent_call"):
                formatted_messages.append(formatted_msg)

        return {"thread_id": thread_id, "messages": formatted_messages}
