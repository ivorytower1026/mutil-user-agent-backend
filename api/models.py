from pydantic import BaseModel
from typing import Literal, Optional


class ChatRequest(BaseModel):
    message: str


class CreateSessionResponse(BaseModel):
    thread_id: str


class ResumeRequest(BaseModel):
    action: str


class ResumeResponse(BaseModel):
    success: bool
    message: str


class ThreadStatus(BaseModel):
    thread_id: str
    status: Literal["idle", "interrupted"]
    has_pending_tasks: bool
    interrupt_info: Optional[dict] = None
    message_count: int


class Message(BaseModel):
    role: Literal["user", "assistant", "tool", "system"]
    content: str


class HistoryResponse(BaseModel):
    thread_id: str
    messages: list[Message]
