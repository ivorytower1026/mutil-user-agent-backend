"""Daytona SDK 封装 + 沙箱管理"""
from daytona import Daytona, DaytonaConfig, CreateSandboxFromSnapshotParams
from langchain_daytona import DaytonaSandbox
from src.config import settings
from src.utils.get_logger import get_logger

logger = get_logger("daytona-client")


class DaytonaClient:
    """Daytona 客户端单例"""
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._client = Daytona(DaytonaConfig(
                api_key=settings.DAYTONA_API_KEY,
                api_url=settings.DAYTONA_API_URL,
            ))
            logger.info("[DaytonaClient] Initialized")
        return cls._instance
    
    @property
    def client(self) -> Daytona:
        return self._client
    
    def create_agent_sandbox(self, thread_id: str, user_id: str) -> DaytonaSandbox:
        """基于 Skills 快照创建 Agent 沙箱"""
        from src.snapshot_manager import get_snapshot_manager
        
        snapshot_id = get_snapshot_manager().get_current_snapshot_id()
        
        if snapshot_id:
            params = CreateSandboxFromSnapshotParams(
                snapshot=snapshot_id,
                labels={"type": "agent", "thread_id": thread_id, "user_id": user_id},
                auto_stop_interval=settings.DAYTONA_AUTO_STOP_INTERVAL,
                auto_delete_interval=settings.DAYTONA_AUTO_STOP_INTERVAL * 2,
            )
            logger.info(f"[DaytonaClient] Creating sandbox from snapshot {snapshot_id[:8]}...")
        else:
            params = CreateSandboxFromSnapshotParams(
                labels={"type": "agent", "thread_id": thread_id, "user_id": user_id},
                auto_stop_interval=settings.DAYTONA_AUTO_STOP_INTERVAL,
                auto_delete_interval=settings.DAYTONA_AUTO_STOP_INTERVAL * 2,
            )
            logger.info("[DaytonaClient] Creating sandbox with default image")
        
        sandbox = self._client.create(params)
        logger.info(f"[DaytonaClient] Created sandbox {sandbox.id}")
        
        return DaytonaSandbox(sandbox=sandbox)
    
    def find_sandbox(self, labels: dict):
        """根据标签查找沙箱"""
        try:
            return self._client.find_one(labels=labels)
        except Exception as e:
            logger.debug(f"[DaytonaClient] Sandbox not found: {e}")
            return None
    
    def get_or_create_sandbox(self, thread_id: str, user_id: str) -> DaytonaSandbox:
        """获取或创建沙箱（支持会话恢复）"""
        existing = self.find_sandbox({"thread_id": thread_id, "type": "agent"})
        
        if existing:
            logger.info(f"[DaytonaClient] Reusing existing sandbox {existing.id}")
            return DaytonaSandbox(sandbox=existing)
        
        return self.create_agent_sandbox(thread_id, user_id)
    
    def delete_sandbox(self, sandbox_id: str):
        """删除沙箱"""
        try:
            self._client.delete(sandbox_id)
            logger.info(f"[DaytonaClient] Deleted sandbox {sandbox_id}")
        except Exception as e:
            logger.warning(f"[DaytonaClient] Failed to delete sandbox: {e}")


def get_daytona_client() -> DaytonaClient:
    return DaytonaClient()
