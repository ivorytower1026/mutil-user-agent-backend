from pydantic import BaseModel


class ChatRequest(BaseModel):
    message: str


class CreateSessionResponse(BaseModel):
    thread_id: str


class ResumeRequest(BaseModel):
    action: str


class ResumeResponse(BaseModel):
    success: bool
    message: str
