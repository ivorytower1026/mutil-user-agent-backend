"""Sandbox 生命周期管理（纯内存缓存）"""
from src.config import settings
from src.daytona_client import get_daytona_client
from src.daytona_sandbox import DaytonaSandboxBackend
from src.utils.get_logger import get_logger

logger = get_logger("sandbox-manager")


class DaytonaSandboxManager:
    """Sandbox 管理器（单例，纯内存缓存）"""
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._client = get_daytona_client().client
            cls._instance._agent_sandboxes = {}  # thread_id -> backend
            cls._instance._files_sandboxes = {}  # user_id -> backend
            cls._instance._validation_sandboxes = {}  # skill_id -> backend (联网)
            cls._instance._offline_sandboxes = {}  # skill_id -> backend (离线)
        return cls._instance
    
    def get_thread_backend(self, thread_id: str) -> DaytonaSandboxBackend:
        """获取 Agent Sandbox（每线程一个）"""
        if thread_id in self._agent_sandboxes:
            return self._agent_sandboxes[thread_id]
        
        user_id = self._extract_user_id(thread_id)
        sandbox = self._client.create()
        
        backend = DaytonaSandboxBackend(thread_id, sandbox)
        self._agent_sandboxes[thread_id] = backend
        return backend
    
    def get_files_backend(self, user_id: str) -> DaytonaSandboxBackend:
        """获取 Files Sandbox（每用户一个，按需创建）"""
        if user_id in self._files_sandboxes:
            return self._files_sandboxes[user_id]
        
        sandbox = self._client.create()
        
        backend = DaytonaSandboxBackend(f"files-{user_id[:8]}", sandbox)
        self._files_sandboxes[user_id] = backend
        return backend
    
    def destroy_thread_backend(self, thread_id: str) -> bool:
        """销毁 Agent Sandbox"""
        if thread_id not in self._agent_sandboxes:
            return False
        self._agent_sandboxes[thread_id].destroy()
        del self._agent_sandboxes[thread_id]
        return True
    
    def get_validation_backend(self, skill_id: str) -> DaytonaSandboxBackend:
        """获取验证 Sandbox（联网环境）
        
        用于 Skill 的联网验证阶段。
        """
        sandbox_id = f"validation_{skill_id}"
        if sandbox_id in self._validation_sandboxes:
            return self._validation_sandboxes[sandbox_id]
        
        logger.info(f"[get_validation_backend] 创建联网 Sandbox skill_id={skill_id}")
        sandbox = self._client.create()
        
        backend = DaytonaSandboxBackend(sandbox_id, sandbox)
        self._validation_sandboxes[sandbox_id] = backend
        return backend
    
    def get_offline_backend(self, skill_id: str) -> DaytonaSandboxBackend:
        """获取离线 Sandbox（network_block_all=True）
        
        用于 Skill 的离线验证阶段。
        在创建时设置 network_block_all=True，阻断所有网络访问。
        """
        sandbox_id = f"offline_{skill_id}"
        if sandbox_id in self._offline_sandboxes:
            return self._offline_sandboxes[sandbox_id]
        
        logger.info(f"[get_offline_backend] 创建离线 Sandbox skill_id={skill_id}")
        from daytona import CreateSandboxFromSnapshotParams
        
        sandbox = self._client.create(CreateSandboxFromSnapshotParams(
            network_block_all=True
        ))
        
        backend = DaytonaSandboxBackend(sandbox_id, sandbox)
        self._offline_sandboxes[sandbox_id] = backend
        return backend
    
    def destroy_validation_backends(self, skill_id: str):
        """销毁验证相关的所有 Sandbox
        
        包括联网 Sandbox 和离线 Sandbox。
        """
        sandbox_ids = [
            f"validation_{skill_id}",
            f"offline_{skill_id}"
        ]
        
        for sid in sandbox_ids:
            for cache in [self._validation_sandboxes, self._offline_sandboxes]:
                if sid in cache:
                    try:
                        logger.info(f"[destroy_validation_backends] 销毁 Sandbox {sid}")
                        cache[sid].destroy()
                    except Exception as e:
                        logger.warning(f"[destroy_validation_backends] 销毁失败 {sid}: {e}")
                    del cache[sid]
    
    def _extract_user_id(self, thread_id: str) -> str:
        """从 thread_id 提取 user_id（格式为 {user_id}-{timestamp}）"""
        return thread_id[:36] if len(thread_id) > 36 else thread_id


def get_sandbox_manager() -> DaytonaSandboxManager:
    """获取 Sandbox 管理器单例"""
    return DaytonaSandboxManager()
