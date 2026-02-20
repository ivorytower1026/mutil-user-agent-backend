"""Daytona SDK 单例客户端"""
from daytona import Daytona, DaytonaConfig
from src.config import settings


class DaytonaClient:
    """Daytona SDK 单例客户端"""
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._client = Daytona(DaytonaConfig(
                api_key=settings.DAYTONA_API_KEY,
                api_url=settings.DAYTONA_API_URL,
            ))
        return cls._instance
    
    @property
    def client(self) -> Daytona:
        return self._client


def get_daytona_client() -> DaytonaClient:
    """获取 Daytona 客户端单例"""
    return DaytonaClient()
