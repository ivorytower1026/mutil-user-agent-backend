import uuid
from typing import Any

from src.database import SessionLocal, Thread
from src.docker_sandbox import get_thread_backend


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

    async def list_sessions(self, user_id: str, page: int = 1, page_size: int = 20) -> dict:
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
        snapshot = await self.agent.aget_state(config)
        messages = snapshot.values.get("messages", [])
        
        formatted_messages = []
        for msg in messages:
            role = "unknown"
            content = ""
            
            if hasattr(msg, "type"):
                msg_type = msg.type
                content = str(msg.content) if hasattr(msg, "content") and msg.content else ""
                
                if msg_type == "system":
                    continue
                
                if msg_type == "human":
                    role = "user"
                elif msg_type == "ai":
                    role = "assistant"
            
            if role != "unknown" and content:
                formatted_messages.append({
                    "role": role,
                    "content": content
                })
        
        return {
            "thread_id": thread_id,
            "messages": formatted_messages
        }
