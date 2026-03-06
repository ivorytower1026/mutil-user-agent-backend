"""Thread lifecycle management and cleanup."""

import asyncio
import time
from datetime import datetime, timedelta, UTC
from sqlalchemy import select
import docker

from src.config import settings
from src.database import SessionLocal, Thread
from src.docker_sandbox import _get_redis
from src.utils.get_logger import get_logger

logger = get_logger("thread-cleanup")


class ThreadCleanupManager:
    """Manages thread lifecycle and cleanup.
    
    Thread table is the single source of truth.
    All cleanup decisions are based on Thread table.
    """
    
    def __init__(self, checkpointer):
        self.checkpointer = checkpointer
        self.docker_client = docker.from_env()
    
    async def sync_on_startup(self) -> dict:
        """Sync container state on startup, clean up orphan containers.
        
        Returns:
            {"restored": N, "orphans_removed": M}
        """
        r = _get_redis()
        restored = 0
        orphans_removed = 0
        
        containers = self.docker_client.containers.list(
            all=True, 
            filters={"name": "sandbox-"}
        )
        
        for container in containers:
            name = container.name
            if not name.startswith("sandbox-"):
                continue
                
            thread_id = name.replace("sandbox-", "")
            
            with SessionLocal() as db:
                thread = db.query(Thread).filter(
                    Thread.thread_id == thread_id
                ).first()
            
            if thread:
                r.hset(f"sandbox:{thread_id}", mapping={
                    "container_id": container.id,
                    "last_active_at": str(time.time())
                })
                restored += 1
                logger.info(f"[ThreadCleanup] Restored mapping: {thread_id}")
            else:
                try:
                    container.remove(force=True)
                    r.delete(f"sandbox:{thread_id}")
                    orphans_removed += 1
                    logger.info(f"[ThreadCleanup] Removed orphan container: {name}")
                except Exception as e:
                    logger.error(f"[ThreadCleanup] Failed to remove orphan {name}: {e}")
        
        logger.info(
            f"[ThreadCleanup] Startup sync complete: "
            f"restored={restored}, orphans_removed={orphans_removed}"
        )
        return {"restored": restored, "orphans_removed": orphans_removed}
    
    async def cleanup_expired_threads(self) -> int:
        """Clean up threads that have been idle for too long.
        
        Thread table is the single source of truth.
        
        Returns:
            Number of threads cleaned up
        """
        timeout_hours = settings.THREAD_IDLE_TIMEOUT_HOURS
        cutoff_time = datetime.now(UTC) - timedelta(hours=timeout_hours)
        
        cleaned = 0
        
        with SessionLocal() as db:
            expired_threads = db.execute(
                select(Thread).where(Thread.last_active_at < cutoff_time)
            ).scalars().all()
            
            for thread in expired_threads:
                try:
                    await self._cleanup_single_thread(thread.thread_id, db)
                    cleaned += 1
                    logger.info(f"[ThreadCleanup] Cleaned up thread: {thread.thread_id}")
                except Exception as e:
                    logger.error(f"[ThreadCleanup] Failed to cleanup {thread.thread_id}: {e}")
            
            db.commit()
        
        return cleaned
    
    async def _cleanup_single_thread(self, thread_id: str, db):
        """Clean up a single thread and all associated resources."""
        r = _get_redis()
        
        await self.checkpointer.adelete_thread(thread_id)
        
        try:
            container = self.docker_client.containers.get(f"sandbox-{thread_id}")
            container.remove(force=True)
        except docker.errors.NotFound:
            pass
        
        r.delete(f"sandbox:{thread_id}")
        
        thread = db.query(Thread).filter(Thread.thread_id == thread_id).first()
        if thread:
            db.delete(thread)
    
    async def run_cleanup_loop(self):
        """Background task that periodically cleans up expired threads."""
        interval = settings.THREAD_CLEANUP_INTERVAL_SECONDS
        
        while True:
            await asyncio.sleep(interval)
            try:
                cleaned = await self.cleanup_expired_threads()
                if cleaned > 0:
                    logger.info(f"[ThreadCleanup] Cleaned {cleaned} expired threads")
            except Exception as e:
                logger.error(f"[ThreadCleanup] Cleanup loop error: {e}")
