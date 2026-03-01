from datetime import datetime
from pydantic import BaseModel
from typing import Literal, Optional, Any


class ChatRequest(BaseModel):
    message: str
    files: list[str] | None = None
    mode: Literal["plan", "build"] = "build"


class CreateSessionResponse(BaseModel):
    thread_id: str


class ResumeRequest(BaseModel):
    action: str
    answers: list[str] | None = None
    mode: Literal["plan", "build"] = "build"


class ResumeResponse(BaseModel):
    success: bool
    message: str


class ThreadStatus(BaseModel):
    thread_id: str
    status: Literal["idle", "interrupted"]
    has_pending_tasks: bool
    interrupt_info: Optional[dict] = None
    message_count: int


class ToolCall(BaseModel):
    name: str
    status: Literal["running", "completed"]
    todos: Optional[list[dict[str, Any]]] = None


class Message(BaseModel):
    role: Literal["user", "assistant", "tool", "system"]
    content: str
    toolCalls: Optional[list[ToolCall]] = None


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


class LlmConfigCreate(BaseModel):
    name: str
    display_name: str | None = None
    description: str | None = None
    provider: str
    base_url: str
    api_key: str
    model_name: str
    temperature: float = 0.7
    max_tokens: int = 4096
    extra_params: dict = {}
    role: str
    activate: bool = False


class LlmConfigUpdate(BaseModel):
    display_name: str | None = None
    description: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    model_name: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    extra_params: dict | None = None


class LlmTestRequest(BaseModel):
    base_url: str
    api_key: str
    model_name: str


class LlmTestResponse(BaseModel):
    success: bool
    message: str
    response_time_ms: int | None = None
    response_preview: str | None = None


class LlmConfigResponse(BaseModel):
    id: str
    name: str
    display_name: str | None
    description: str | None
    provider: str
    base_url: str
    model_name: str
    temperature: float
    max_tokens: int
    extra_params: dict
    role: str
    is_active: bool
    created_at: str | None
    updated_at: str | None

    class Config:
        from_attributes = True


class LlmConfigListResponse(BaseModel):
    configs: list[LlmConfigResponse]
    total: int
