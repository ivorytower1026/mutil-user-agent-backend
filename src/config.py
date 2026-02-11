"""Configuration settings for the backend application."""
from pathlib import Path
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from langchain_openai import ChatOpenAI

from src.utils.get_root_path import get_project_root


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    model_config = SettingsConfigDict(env_file=get_project_root() / ".env", env_file_encoding="utf-8")

    # 智谱AI配置
    ZHIPUAI_API_KEY: str
    ZHIPUAI_API_BASE: str

    # Langfuse配置
    IS_LANGFUSE: int
    LANGFUSE_SECRET_KEY: str
    LANGFUSE_PUBLIC_KEY: str
    LANGFUSE_BASE_URL: str

    # 工作空间配置
    WORKSPACE_ROOT: str
    SHARED_DIR: str
    DOCKER_IMAGE: str
    CONTAINER_WORKSPACE_DIR: str
    CONTAINER_SHARED_DIR: str

    @field_validator("IS_LANGFUSE", mode="before")
    def parse_is_langfuse(cls, v):
        return int(v)


def _resolve_path(path_str: str) -> str:
    """Resolve a path string to an absolute path."""
    path = Path(path_str).expanduser().absolute()
    return str(path)


# Global settings instance
settings = Settings()

# Create LLM instance using settings
llm = ChatOpenAI(
    model="glm-4.7",
    temperature=0,
    openai_api_key=settings.ZHIPUAI_API_KEY,
    openai_api_base=settings.ZHIPUAI_API_BASE,
    extra_body={
        "response_format": {"type": "text"},
        "thinking": {"type": "enabled"}
    }
)

# Export convenience functions for backward compatibility
LANGFUSE_PUBLIC_KEY = settings.LANGFUSE_PUBLIC_KEY
LANGFUSE_SECRET_KEY = settings.LANGFUSE_SECRET_KEY
LANGFUSE_BASE_URL = settings.LANGFUSE_BASE_URL
WORKSPACE_ROOT = _resolve_path(settings.WORKSPACE_ROOT)
SHARED_DIR = _resolve_path(settings.SHARED_DIR)
DOCKER_IMAGE = settings.DOCKER_IMAGE
CONTAINER_WORKSPACE_DIR = settings.CONTAINER_WORKSPACE_DIR
CONTAINER_SHARED_DIR = settings.CONTAINER_SHARED_DIR
