from datetime import datetime
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


class ThreadListItem(BaseModel):
    thread_id: str
    title: Optional[str] = None
    created_at: Optional[datetime] = None
    message_count: int = 0
    status: Literal["idle", "interrupted"] = "idle"


class ThreadListResponse(BaseModel):
    threads: list[ThreadListItem]
    total: int


# WebDAV and Chunk Upload Models

class UploadInitRequest(BaseModel):
    filename: str
    total_chunks: int
    total_size: int
    target_path: str | None = None


class UploadInitResponse(BaseModel):
    upload_id: str
    chunk_size: int


class UploadChunkRequest(BaseModel):
    upload_id: str
    chunk_index: int


class UploadCompleteRequest(BaseModel):
    upload_id: str
    target_path: str


class FileInfo(BaseModel):
    name: str
    path: str
    type: Literal["file", "directory"]
    size: int | None = None
    modified: str | None = None
    etag: str | None = None
