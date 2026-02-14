"""Chunk upload manager for large file uploads."""
import json
import shutil
import uuid
from pathlib import Path
from datetime import datetime, timedelta


class ChunkUploadManager:
    """Manager for chunked file uploads.
    
    Supports uploading large files in chunks, with resume capability.
    """
    
    CHUNK_SIZE = 10 * 1024 * 1024  # 10MB
    EXPIRE_HOURS = 24
    
    def __init__(self, workspace_root: str):
        self.root = Path(workspace_root)
        self.upload_dir = self.root / ".uploads"
        self.upload_dir.mkdir(exist_ok=True)
    
    def init(self, user_id: str, filename: str, total_chunks: int, 
             total_size: int, target_path: str | None = None) -> str:
        """Initialize a chunked upload session.
        
        Args:
            user_id: User ID
            filename: Original filename
            total_chunks: Number of chunks expected
            total_size: Total file size in bytes
            target_path: Optional target path (defaults to filename)
            
        Returns:
            upload_id: Unique upload session ID
        """
        upload_id = str(uuid.uuid4())
        upload_path = self.upload_dir / upload_id
        upload_path.mkdir()
        
        meta = {
            "user_id": user_id,
            "filename": filename,
            "total_chunks": total_chunks,
            "total_size": total_size,
            "target_path": target_path or filename,
            "received": [],
            "created_at": datetime.now().isoformat()
        }
        (upload_path / "meta.json").write_text(json.dumps(meta), encoding='utf-8')
        
        return upload_id
    
    def save_chunk(self, upload_id: str, chunk_index: int, data: bytes) -> bool:
        """Save a chunk to temporary storage.
        
        Args:
            upload_id: Upload session ID
            chunk_index: Chunk index (0-based)
            data: Chunk data bytes
            
        Returns:
            True if successful
            
        Raises:
            ValueError: If upload_id not found
        """
        meta = self._load_meta(upload_id)
        
        if chunk_index < 0 or chunk_index >= meta["total_chunks"]:
            raise ValueError(f"Invalid chunk index: {chunk_index}")
        
        chunk_path = self.upload_dir / upload_id / f"chunk_{chunk_index}"
        chunk_path.write_bytes(data)
        
        if chunk_index not in meta["received"]:
            meta["received"].append(chunk_index)
            self._save_meta(upload_id, meta)
        
        return True
    
    def get_progress(self, upload_id: str) -> dict:
        """Get upload progress information.
        
        Args:
            upload_id: Upload session ID
            
        Returns:
            Dict with received chunks info
        """
        meta = self._load_meta(upload_id)
        return {
            "total_chunks": meta["total_chunks"],
            "received": sorted(meta["received"]),
            "total_size": meta["total_size"],
            "filename": meta["filename"]
        }
    
    def complete(self, upload_id: str, user_id: str, target_path: str) -> Path:
        """Merge all chunks and save to final location.
        
        Args:
            upload_id: Upload session ID
            user_id: User ID (for verification)
            target_path: Final destination path
            
        Returns:
            Path to the completed file
            
        Raises:
            ValueError: If not all chunks received or user mismatch
        """
        meta = self._load_meta(upload_id)
        
        if meta["user_id"] != user_id:
            raise ValueError("User ID mismatch")
        
        if len(meta["received"]) != meta["total_chunks"]:
            received = sorted(meta["received"])
            missing = [i for i in range(meta["total_chunks"]) if i not in received]
            raise ValueError(f"Not all chunks received. Missing: {missing}")
        
        base = (self.root / user_id).resolve()
        target = (base / target_path.lstrip('/')).resolve()
        
        if not str(target).startswith(str(base)):
            raise ValueError("Invalid target path")
        
        target.parent.mkdir(parents=True, exist_ok=True)
        
        with open(target, 'wb') as outfile:
            for i in range(meta["total_chunks"]):
                chunk_path = self.upload_dir / upload_id / f"chunk_{i}"
                outfile.write(chunk_path.read_bytes())
        
        self.cancel(upload_id)
        
        return target
    
    def cancel(self, upload_id: str) -> None:
        """Cancel an upload and clean up temporary files.
        
        Args:
            upload_id: Upload session ID
        """
        upload_path = self.upload_dir / upload_id
        if upload_path.exists():
            shutil.rmtree(upload_path)
    
    def cleanup_stale(self) -> int:
        """Clean up expired upload sessions.
        
        Should be called on application startup.
        
        Returns:
            Number of cleaned up sessions
        """
        count = 0
        threshold = datetime.now() - timedelta(hours=self.EXPIRE_HOURS)
        
        for upload_dir in self.upload_dir.iterdir():
            if not upload_dir.is_dir():
                continue
            if upload_dir.name.startswith('.'):
                continue
            try:
                meta = self._load_meta(upload_dir.name)
                created = datetime.fromisoformat(meta["created_at"])
                if created < threshold:
                    self.cancel(upload_dir.name)
                    count += 1
            except Exception:
                self.cancel(upload_dir.name)
                count += 1
        
        return count
    
    def _load_meta(self, upload_id: str) -> dict:
        """Load upload metadata.
        
        Args:
            upload_id: Upload session ID
            
        Returns:
            Metadata dict
            
        Raises:
            ValueError: If upload_id not found
        """
        meta_path = self.upload_dir / upload_id / "meta.json"
        if not meta_path.exists():
            raise ValueError(f"Upload session not found: {upload_id}")
        return json.loads(meta_path.read_text(encoding='utf-8'))
    
    def _save_meta(self, upload_id: str, meta: dict) -> None:
        """Save upload metadata.
        
        Args:
            upload_id: Upload session ID
            meta: Metadata dict
        """
        meta_path = self.upload_dir / upload_id / "meta.json"
        meta_path.write_text(json.dumps(meta), encoding='utf-8')
