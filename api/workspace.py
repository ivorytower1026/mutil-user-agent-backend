"""工作区文件同步 API"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Literal

from src.auth import get_current_user
from src.daytona_client import get_daytona_client
from src.workspace_sync import get_sync_service

router = APIRouter(prefix="/api/workspace", tags=["workspace"])


class SyncRequest(BaseModel):
    direction: Literal["to_daytona", "from_daytona"]
    paths: list[str]


class SyncResponse(BaseModel):
    status: str
    synced: int
    failed: int
    errors: list[dict]


@router.post("/threads/{thread_id}/sync", response_model=SyncResponse)
async def sync_workspace(
    thread_id: str,
    request: SyncRequest,
    user_id: str = Depends(get_current_user)
):
    """
    手动同步工作区文件
    
    - direction: "to_daytona" (上传到沙箱) 或 "from_daytona" (下载到本地)
    - paths: 要同步的文件/目录路径列表
    """
    if not thread_id.startswith(f"{user_id}-"):
        raise HTTPException(status_code=403, detail="Access denied")
    
    sync_service = get_sync_service()
    
    if request.direction == "to_daytona":
        result = sync_service.sync_to_daytona(user_id, thread_id, request.paths)
    else:
        result = sync_service.sync_from_daytona(user_id, thread_id, request.paths)
    
    return SyncResponse(
        status="completed",
        synced=result["synced"],
        failed=result["failed"],
        errors=result["errors"]
    )


@router.get("/threads/{thread_id}/sandbox/status")
async def get_sandbox_status(
    thread_id: str,
    user_id: str = Depends(get_current_user)
):
    """获取沙箱状态"""
    if not thread_id.startswith(f"{user_id}-"):
        raise HTTPException(status_code=403, detail="Access denied")
    
    client = get_daytona_client()
    sandbox = client.find_sandbox({"thread_id": thread_id, "type": "agent"})
    
    if sandbox is None:
        return {"exists": False, "status": "not_created"}
    
    return {
        "exists": True,
        "status": getattr(sandbox, "state", "unknown"),
        "sandbox_id": sandbox.id
    }


@router.post("/threads/{thread_id}/polling/start")
async def start_polling(
    thread_id: str,
    user_id: str = Depends(get_current_user)
):
    """启动文件变更轮询（按 user_id 去重）"""
    if not thread_id.startswith(f"{user_id}-"):
        raise HTTPException(status_code=403, detail="Access denied")
    
    sync_service = get_sync_service()
    sync_service.start_polling(thread_id, user_id)
    
    return {"status": "started", "user_id": user_id}


@router.post("/users/{user_id}/polling/stop")
async def stop_polling(
    user_id: str,
    current_user_id: str = Depends(get_current_user)
):
    """停止文件变更轮询（按 user_id）"""
    if user_id != current_user_id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    sync_service = get_sync_service()
    sync_service.stop_polling(user_id)
    
    return {"status": "stopped"}
