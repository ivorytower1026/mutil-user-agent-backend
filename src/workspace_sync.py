"""实时双向文件同步服务"""
import asyncio
from pathlib import Path

from daytona import FileUpload
from src.config import settings
from src.daytona_client import get_daytona_client
from src.utils.get_logger import get_logger

logger = get_logger("workspace-sync")

SYNC_WORKSPACE = "/home/daytona"


class RealtimeFileSyncService:
    """实时双向文件同步"""
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._base_dir = Path(settings.WORKSPACE_ROOT)
            cls._instance._sync_tasks: dict[str, asyncio.Task] = {}
            cls._instance._file_mtimes: dict[str, dict[str, float]] = {}
            cls._instance._poll_interval = settings.SYNC_POLL_INTERVAL
            cls._instance._synced_users: set[str] = set()
            logger.info(f"[FileSync] Initialized, poll_interval={cls._instance._poll_interval}s")
        return cls._instance
    
    def _get_user_workspace(self, user_id: str) -> Path:
        return self._base_dir / user_id
    
    def on_local_file_change(self, user_id: str, thread_id: str, path: str, content: bytes):
        """本地文件变化时触发（WebDAV PUT 调用）"""
        try:
            client = get_daytona_client()
            sandbox = client.get_or_create_sandbox(thread_id, user_id)
            sandbox.upload_files([(
                f"{SYNC_WORKSPACE}/{path}",
                content
            )])
            logger.debug(f"[FileSync] Synced to sandbox: {path}")
        except Exception as e:
            logger.warning(f"[FileSync] Sync to sandbox failed: {e}")
    
    def on_local_file_delete(self, user_id: str, thread_id: str, path: str):
        """本地文件删除时触发（WebDAV DELETE 调用）"""
        try:
            client = get_daytona_client()
            sandbox = client.get_or_create_sandbox(thread_id, user_id)
            sandbox._sandbox.fs.delete_file(f"{SYNC_WORKSPACE}/{path}")
            logger.debug(f"[FileSync] Deleted from sandbox: {path}")
        except Exception as e:
            logger.warning(f"[FileSync] Delete from sandbox failed: {e}")
    
    def start_polling(self, thread_id: str, user_id: str):
        """启动轮询任务（按 user_id 去重）"""
        if user_id in self._sync_tasks:
            return
        
        task = asyncio.create_task(self._poll_sandbox_changes(user_id))
        self._sync_tasks[user_id] = task
        logger.info(f"[FileSync] Started polling for user {user_id}")
    
    def stop_polling(self, user_id: str):
        """停止轮询任务"""
        if user_id in self._sync_tasks:
            self._sync_tasks[user_id].cancel()
            del self._sync_tasks[user_id]
            if user_id in self._file_mtimes:
                del self._file_mtimes[user_id]
            self._synced_users.discard(user_id)
            logger.info(f"[FileSync] Stopped polling for user {user_id}")
    
    async def _poll_sandbox_changes(self, user_id: str):
        """轮询检测沙箱文件变化（按 user_id）"""
        while True:
            try:
                await asyncio.sleep(self._poll_interval)
                
                client = get_daytona_client()
                sandbox_info = client.find_sandbox({"user_id": user_id, "type": "agent"})
                
                if not sandbox_info:
                    continue
                
                sandbox = client.get_or_create_sandbox(sandbox_info.labels.get("thread_id", ""), user_id)
                await self._check_and_sync_changes(sandbox, user_id)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[FileSync] Polling error: {e}")
                await asyncio.sleep(10)
    
    async def _check_and_sync_changes(self, sandbox, user_id: str):
        """检测并同步变化的文件"""
        local_workspace = self._get_user_workspace(user_id)
        
        try:
            files = sandbox._sandbox.fs.list_files(SYNC_WORKSPACE)
        except Exception:
            return
        
        if user_id not in self._file_mtimes:
            self._file_mtimes[user_id] = {}
        mtimes = self._file_mtimes[user_id]
        
        changes = []
        for file_info in files:
            if file_info.is_dir:
                continue
            
            path = file_info.name
            remote_mtime = file_info.mod_time.timestamp() if file_info.mod_time else 0
            
            if path not in mtimes or mtimes[path] < remote_mtime:
                local_path = local_workspace / path
                if local_path.exists():
                    local_mtime = local_path.stat().st_mtime
                    if local_mtime > remote_mtime:
                        continue
                
                changes.append(path)
                mtimes[path] = remote_mtime
        
        if changes:
            await self._sync_from_sandbox(sandbox, user_id, changes)
    
    async def _sync_from_sandbox(self, sandbox, user_id: str, paths: list[str]):
        """从沙箱同步文件到本地"""
        local_workspace = self._get_user_workspace(user_id)
        sandbox_paths = [f"{SYNC_WORKSPACE}/{p}" for p in paths]
        
        try:
            results = sandbox.download_files(sandbox_paths)
            
            for result in results:
                if result.content:
                    relative = result.path.replace(f"{SYNC_WORKSPACE}/", "")
                    local_path = local_workspace / relative
                    local_path.parent.mkdir(parents=True, exist_ok=True)
                    local_path.write_bytes(result.content)
                    logger.info(f"[FileSync] Synced from sandbox: {relative}")
        except Exception as e:
            logger.error(f"[FileSync] Sync from sandbox failed: {e}")
    
    def sync_to_daytona(self, user_id: str, thread_id: str, paths: list[str]) -> dict:
        """手动同步本地文件到沙箱"""
        local_workspace = self._get_user_workspace(user_id)
        client = get_daytona_client()
        sandbox = client.get_or_create_sandbox(thread_id, user_id)
        
        files = []
        errors = []
        
        for path in paths:
            local_path = local_workspace / path
            if local_path.is_file():
                try:
                    files.append((f"{SYNC_WORKSPACE}/{path}", local_path.read_bytes()))
                except Exception as e:
                    errors.append({"path": path, "error": str(e)})
            elif local_path.is_dir():
                for fp in local_path.rglob("*"):
                    if fp.is_file():
                        relative = fp.relative_to(local_workspace)
                        try:
                            files.append((f"{SYNC_WORKSPACE}/{relative}", fp.read_bytes()))
                        except Exception as e:
                            errors.append({"path": str(relative), "error": str(e)})
        
        if files:
            results = sandbox.upload_files(files)
            failed = sum(1 for r in results if r.error)
        else:
            failed = 0
        
        logger.info(f"[FileSync] Manual sync to daytona: {len(files) - failed} files")
        return {"synced": len(files) - failed, "failed": failed, "errors": errors}
    
    def initial_sync_to_sandbox(self, user_id: str, daytona_sandbox) -> bool:
        """首次同步用户工作空间到沙箱（全量同步）"""
        if user_id in self._synced_users:
            return False
        
        local_workspace = self._get_user_workspace(user_id)
        
        if not local_workspace.exists():
            self._synced_users.add(user_id)
            return True
        
        files = []
        for fp in local_workspace.rglob("*"):
            if fp.is_file():
                relative = fp.relative_to(local_workspace)
                try:
                    files.append(FileUpload(
                        source=fp.read_bytes(),
                        destination=f"{SYNC_WORKSPACE}/{relative}"
                    ))
                except Exception as e:
                    logger.warning(f"[FileSync] Failed to read {relative}: {e}")
        
        if files:
            try:
                daytona_sandbox._sandbox.fs.upload_files(files)
                logger.info(f"[FileSync] Initial sync for user {user_id}: {len(files)} files")
            except Exception as e:
                logger.error(f"[FileSync] Initial sync failed for user {user_id}: {e}")
                return False
        
        self._synced_users.add(user_id)
        return True
    
    def sync_from_daytona(self, user_id: str, thread_id: str, paths: list[str]) -> dict:
        """手动从沙箱同步文件到本地"""
        local_workspace = self._get_user_workspace(user_id)
        client = get_daytona_client()
        sandbox = client.get_or_create_sandbox(thread_id, user_id)
        
        sandbox_paths = [f"{SYNC_WORKSPACE}/{p}" for p in paths]
        results = sandbox.download_files(sandbox_paths)
        
        synced = 0
        failed = 0
        errors = []
        
        for result in results:
            if result.content:
                relative = result.path.replace(f"{SYNC_WORKSPACE}/", "")
                local_path = local_workspace / relative
                try:
                    local_path.parent.mkdir(parents=True, exist_ok=True)
                    local_path.write_bytes(result.content)
                    synced += 1
                except Exception as e:
                    failed += 1
                    errors.append({"path": relative, "error": str(e)})
            else:
                failed += 1
                errors.append({"path": result.path, "error": result.error or "download failed"})
        
        logger.info(f"[FileSync] Manual sync from daytona: {synced} files")
        return {"synced": synced, "failed": failed, "errors": errors}


def get_sync_service() -> RealtimeFileSyncService:
    return RealtimeFileSyncService()
