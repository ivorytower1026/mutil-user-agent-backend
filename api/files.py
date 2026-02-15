"""File operation API routes for chunk upload."""
from datetime import datetime
from pathlib import Path
import uuid

from fastapi import APIRouter, Depends, HTTPException, File, UploadFile, Form

from src.chunk_upload import ChunkUploadManager
from src.auth import get_current_user
from src.config import settings
from api.models import (
    UploadInitRequest,
    UploadInitResponse,
    UploadCompleteRequest,
    FileInfo
)

MAX_UPLOAD_SIZE = 50 * 1024 * 1024  # 50MB

router = APIRouter(prefix="/files", tags=["files"])
upload_manager = ChunkUploadManager(settings.WORKSPACE_ROOT)


@router.post("/init-upload", response_model=UploadInitResponse)
async def init_upload(
    request: UploadInitRequest,
    user_id: str = Depends(get_current_user)
):
    """Initialize a chunked upload session.
    
    Args:
        request: Upload initialization parameters
        user_id: Authenticated user ID
        
    Returns:
        upload_id and chunk_size
    """
    upload_id = upload_manager.init(
        user_id=user_id,
        filename=request.filename,
        total_chunks=request.total_chunks,
        total_size=request.total_size,
        target_path=request.target_path
    )
    
    return UploadInitResponse(
        upload_id=upload_id,
        chunk_size=ChunkUploadManager.CHUNK_SIZE
    )


@router.post("/upload-chunk")
async def upload_chunk(
    upload_id: str = Form(...),
    chunk_index: int = Form(...),
    chunk: UploadFile = File(...),
    user_id: str = Depends(get_current_user)
):
    """Upload a file chunk.
    
    Args:
        upload_id: Upload session ID from init-upload
        chunk_index: Chunk index (0-based)
        chunk: Chunk file data
        user_id: Authenticated user ID
        
    Returns:
        Success status with progress info
    """
    try:
        data = await chunk.read()
        upload_manager.save_chunk(upload_id, chunk_index, data)
        progress = upload_manager.get_progress(upload_id)
        return {
            "success": True,
            "chunk_index": chunk_index,
            "received_count": len(progress["received"])
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/complete-upload")
async def complete_upload(
    request: UploadCompleteRequest,
    user_id: str = Depends(get_current_user)
):
    """Complete a chunked upload and merge all chunks.
    
    Args:
        request: Complete request with upload_id and target_path
        user_id: Authenticated user ID
        
    Returns:
        Success status with final file path
    """
    try:
        target = upload_manager.complete(
            upload_id=request.upload_id,
            user_id=user_id,
            target_path=request.target_path
        )
        return {
            "success": True,
            "path": str(target.relative_to(Path(settings.WORKSPACE_ROOT) / user_id))
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/upload/{upload_id}")
async def cancel_upload(
    upload_id: str,
    user_id: str = Depends(get_current_user)
):
    """Cancel an in-progress upload.
    
    Args:
        upload_id: Upload session ID
        user_id: Authenticated user ID
        
    Returns:
        Success status
    """
    upload_manager.cancel(upload_id)
    return {"success": True, "message": "Upload cancelled"}


@router.get("/upload/{upload_id}/progress")
async def get_upload_progress(
    upload_id: str,
    user_id: str = Depends(get_current_user)
):
    """Get upload progress.
    
    Args:
        upload_id: Upload session ID
        user_id: Authenticated user ID
        
    Returns:
        Progress information
    """
    try:
        progress = upload_manager.get_progress(upload_id)
        return progress
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/upload-simple")
async def upload_simple(
    file: UploadFile = File(...),
    user_id: str = Depends(get_current_user)
):
    """Simple file upload for chat context.
    
    Args:
        file: File to upload (max 50MB)
        user_id: Authenticated user ID
        
    Returns:
        Upload result with path, filename, and size
    """
    content = await file.read()
    
    if len(content) > MAX_UPLOAD_SIZE:
        raise HTTPException(
            status_code=413,
            detail="文件超过 50MB，请使用 WebDAV 上传到工作目录"
        )
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    uid = uuid.uuid4().hex[:8]
    ext = Path(file.filename).suffix if file.filename else ""
    new_filename = f"{timestamp}_{uid}{ext}"
    
    user_dir = Path(settings.WORKSPACE_ROOT) / user_id
    uploads_dir = user_dir / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    
    file_path = uploads_dir / new_filename
    file_path.write_bytes(content)
    
    return {
        "success": True,
        "path": f"/workspace/uploads/{new_filename}",
        "filename": file.filename,
        "size": len(content)
    }
