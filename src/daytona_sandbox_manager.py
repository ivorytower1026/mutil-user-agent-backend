"""Sandbox 生命周期管理（纯内存缓存）"""
from src.config import settings
from src.daytona_client import get_daytona_client
from src.daytona_sandbox import DaytonaSandboxBackend


class DaytonaSandboxManager:
    """Sandbox 管理器（单例，纯内存缓存）"""
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._client = get_daytona_client().client
            cls._instance._agent_sandboxes = {}  # thread_id -> backend
            cls._instance._files_sandboxes = {}  # user_id -> backend
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
    
    def _extract_user_id(self, thread_id: str) -> str:
        """从 thread_id 提取 user_id（格式为 {user_id}-{timestamp}）"""
        return thread_id[:36] if len(thread_id) > 36 else thread_id


def get_sandbox_manager() -> DaytonaSandboxManager:
    """获取 Sandbox 管理器单例"""
    return DaytonaSandboxManager()
