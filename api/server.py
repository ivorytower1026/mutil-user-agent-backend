from typing import AsyncGenerator

from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse
from src.agent_manager import AgentManager
from src.auth import get_current_user, verify_thread_permission
from src.docker_sandbox import destroy_thread_backend
from api.models import (
    ChatRequest,
    CreateSessionResponse,
    ResumeRequest,
    ResumeResponse
)

router = APIRouter()
agent_manager = AgentManager()


@router.post("/sessions", response_model=CreateSessionResponse)
async def create_session(user_id: str = Depends(get_current_user)):
    """Create a new session.
    
    Requires authentication. Returns a thread_id in format {user_id}-{uuid}.
    """
    thread_id = await agent_manager.create_session(user_id)
    return CreateSessionResponse(thread_id=thread_id)


@router.post("/chat/{thread_id}")
async def chat(
    thread_id: str,
    request: ChatRequest,
    user_id: str = Depends(get_current_user)
):
    """Send a message to the agent.
    
    Requires authentication. User can only access their own threads.
    """
    # Verify thread ownership
    verify_thread_permission(user_id, thread_id)
    
    async def event_generator() -> AsyncGenerator[str, None]:
        async for chunk in agent_manager.stream_chat(thread_id, request.message):
            yield chunk

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream"
    )


@router.post("/resume/{thread_id}")
async def stream_resume_interrupt(
    thread_id: str,
    request: ResumeRequest,
    user_id: str = Depends(get_current_user)
):
    """Resume an interrupted session (HITL) with streaming.

    Requires authentication. User can only resume their own threads.
    """
    # Verify thread ownership
    verify_thread_permission(user_id, thread_id)

    if request.action not in ["continue", "cancel"]:
        raise HTTPException(
            status_code=400,
            detail="Action must be 'continue' or 'cancel'"
        )

    async def event_generator() -> AsyncGenerator[str, None]:
        async for chunk in agent_manager.stream_resume_interrupt(thread_id, request.action):
            yield chunk

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream"
    )


@router.delete("/sessions/{thread_id}")
async def destroy_session(
    thread_id: str,
    user_id: str = Depends(get_current_user)
):
    """Destroy a session and its container.
    
    Args:
        thread_id: The session/thread ID to destroy
        
    Returns:
        Status message
        
    Raises:
        403: If user doesn't own this thread
        404: If thread doesn't exist
    """
    verify_thread_permission(user_id, thread_id)
    
    destroyed = destroy_thread_backend(thread_id)
    
    if not destroyed:
        raise HTTPException(status_code=404, detail="Thread not found")
    
    return {"status": "destroyed", "thread_id": thread_id}
