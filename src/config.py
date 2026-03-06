"""Configuration settings for the backend application."""

import platform
from pathlib import Path
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from langchain_openai import ChatOpenAI

from src.utils.get_root_path import get_project_root


def _get_default_base_dir() -> Path:
    """Get platform-specific default base directory.
    
    Windows: C:\\Users\\<username>\\.mutil-user-agent
    Linux/Mac: /home/<username>/.mutil-user-agent
    """
    return Path.home() / ".mutil-user-agent"


# Pre-compute default directories for the current platform
_DEFAULT_BASE_DIR = _get_default_base_dir()


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=get_project_root() / ".env", env_file_encoding="utf-8"
    )

    # 智谱AI配置
    ZHIPUAI_API_KEY: str
    ZHIPUAI_API_BASE: str = "https://open.bigmodel.cn/api/coding/paas/v4"

    # Langfuse配置
    IS_LANGFUSE: int = 1
    LANGFUSE_SECRET_KEY: str
    LANGFUSE_PUBLIC_KEY: str
    LANGFUSE_BASE_URL: str

    # 工作空间配置
    WORKSPACE_ROOT: str = str(_DEFAULT_BASE_DIR / "workspace")
    SHARED_DIR: str = str(_DEFAULT_BASE_DIR / "shared")
    SKILL_DIR: str = str(_DEFAULT_BASE_DIR / "skills")
    SKILL_DISABLE_DIR: str = str(_DEFAULT_BASE_DIR / "skills_disable")
    DOCKER_IMAGE: str = "mutil-user-agent-sandbox:latest"
    CONTAINER_WORKSPACE_DIR: str = "/workspace"
    CONTAINER_SHARED_DIR: str = "/shared"
    CONTAINER_SKILLS_DIR: str = "/skills"

    # 数据库配置
    DATABASE_URL: str

    # JWT配置
    SECRET_KEY: str
    ACCESS_TOKEN_EXPIRE_HOURS: int = 24

    PORT: int = 8005

    OPENAI_API_BASE_8001: str = "http://192.168.110.44:8001/v1"
    OPENAI_API_BASE_8002: str = "http://192.168.110.44:8002/v1"

    MODELSCOPE_SDK_TOKEN: str = ""
    MODELSCOPE_URL: str = "https://api-inference.modelscope.cn/v1"

    # Skill 验证相关配置
    SKILL_IMAGES_DIR: str = str(_DEFAULT_BASE_DIR / "skill-images")
    SKILL_IMAGE_VERSIONS_TO_KEEP: int = 5
    SKILL_PENDING_DIR: str = (
        ""  # 待验证 skill 目录，默认为 {WORKSPACE_ROOT}/skills_pending
    )
    SKILL_APPROVED_DIR: str = ""  # 已入库 skill 目录，默认为 {SHARED_DIR}/skills

    # Docker 资源限制
    DOCKER_CPU_LIMIT: float = 1.0  # CPU 核数
    DOCKER_MEMORY_LIMIT: str = "2g"  # 内存限制

    # 沙箱超时配置
    DOCKER_IDLE_TIMEOUT_SECONDS: int = 300  # 5分钟无操作自动清理
    REDIS_URL: str = "redis://localhost:6379/0"

    # Thread 生命周期配置
    THREAD_IDLE_TIMEOUT_HOURS: int = 720  # 30天无活动则清理
    THREAD_CLEANUP_INTERVAL_SECONDS: int = 300  # 每 5 分钟检查一次

    LLM_MODE: int = 1

    # Mem0 记忆系统配置
    MEMORY_ENABLED: int = 0  # 是否启用记忆功能 (1=开启, 0=关闭)
    MEM0_COLLECTION_NAME: str = "multi_agent_memory"
    MEM0_QDRANT_HOST: str = "localhost"
    MEM0_QDRANT_PORT: int = 6333

    FLASH_MODEL_NAME: str = "Qwen3.5-35B-A3B"
    FLASH_MODEL_URL: str = "http://192.168.110.44:8001/v1"

    LOG_LEVEL: str = "INFO"
    LOG_TO_CONSOLE: int = 0
    LOG_BACKUP_DAYS: int = 30

    @field_validator("IS_LANGFUSE", mode="before")
    def parse_is_langfuse(cls, v):
        return int(v)

    @field_validator("MEMORY_ENABLED", mode="before")
    def parse_memory_enabled(cls, v):
        return int(v)

    @field_validator("LOG_TO_CONSOLE", mode="before")
    def parse_log_to_console(cls, v):
        return int(v)

    @field_validator("LLM_MODE", mode="before")
    def parse_llm_mode(cls, v):
        return int(v)

    @field_validator("PORT", mode="before")
    def parse_port(cls, v):
        return int(v)

    @field_validator("ACCESS_TOKEN_EXPIRE_HOURS", mode="before")
    def parse_access_token_expire_hours(cls, v):
        return int(v)

    @field_validator("DOCKER_CPU_LIMIT", mode="before")
    def parse_docker_cpu_limit(cls, v):
        return float(v)

    @field_validator("DOCKER_IDLE_TIMEOUT_SECONDS", mode="before")
    def parse_docker_idle_timeout_seconds(cls, v):
        return int(v)

    @field_validator("MEM0_QDRANT_PORT", mode="before")
    def parse_mem0_qdrant_port(cls, v):
        return int(v)

    @field_validator("SKILL_IMAGE_VERSIONS_TO_KEEP", mode="before")
    def parse_skill_image_versions_to_keep(cls, v):
        return int(v)

    @field_validator("THREAD_IDLE_TIMEOUT_HOURS", mode="before")
    def parse_thread_idle_timeout_hours(cls, v):
        return int(v)

    @field_validator("THREAD_CLEANUP_INTERVAL_SECONDS", mode="before")
    def parse_thread_cleanup_interval_seconds(cls, v):
        return int(v)


def _resolve_path(path_str: str) -> str:
    """Resolve a path string to an absolute path."""
    path = Path(path_str).expanduser().absolute()
    return str(path)


# Global settings instance
settings = Settings()


def _ensure_directories():
    """Ensure all required directories exist."""
    directories = [
        settings.WORKSPACE_ROOT,
        settings.SHARED_DIR,
        settings.SKILL_DIR,
        settings.SKILL_DISABLE_DIR,
        settings.SKILL_IMAGES_DIR,
    ]
    
    for dir_path in directories:
        path = Path(dir_path)
        if not path.exists():
            path.mkdir(parents=True, exist_ok=True)
            print(f"[Config] Created directory: {dir_path}")


_ensure_directories()


def get_fallback_big_llm() -> ChatOpenAI:
    """Get fallback big LLM from environment variables."""
    if settings.LLM_MODE == 1:
        return ChatOpenAI(
            model="glm-5",
            temperature=0,
            openai_api_key=settings.ZHIPUAI_API_KEY,
            openai_api_base=settings.ZHIPUAI_API_BASE,
            extra_body={
                "response_format": {"type": "text"},
                "thinking": {"type": "enabled"},
            },
        )
    return ChatOpenAI(
        model="MiniMax-M2.1",
        base_url=settings.OPENAI_API_BASE_8002,
        api_key="EMPTY",
        temperature=0.7,
        max_tokens=1024,
    )


def get_fallback_flash_llm() -> ChatOpenAI:
    """Get fallback flash LLM from environment variables."""
    if settings.LLM_MODE == 1:
        return ChatOpenAI(
            model="Qwen/Qwen3-VL-30B-A3B-Instruct",
            base_url=settings.MODELSCOPE_URL,
            api_key=settings.MODELSCOPE_SDK_TOKEN,
            temperature=0.7,
            max_tokens=1024,
        )
    return ChatOpenAI(
        model="Qwen3-VL-30B-A3B-Instruct",
        base_url=settings.OPENAI_API_BASE_8001,
        api_key="EMPTY",
        temperature=0.7,
        max_tokens=1024,
    )


llm_glm_4_7 = ChatOpenAI(
    model="glm-4.7",
    temperature=0,
    openai_api_key=settings.ZHIPUAI_API_KEY,
    openai_api_base=settings.ZHIPUAI_API_BASE,
    extra_body={"response_format": {"type": "text"}, "thinking": {"type": "enabled"}},
)

llm_glm_5 = ChatOpenAI(
    model="glm-5",
    temperature=0,
    openai_api_key=settings.ZHIPUAI_API_KEY,
    openai_api_base=settings.ZHIPUAI_API_BASE,
    extra_body={"response_format": {"type": "text"}, "thinking": {"type": "enabled"}},
)

llm_qwen3_vl_30b_a3b_instruct = ChatOpenAI(
    model="Qwen3-VL-30B-A3B-Instruct",
    base_url=settings.OPENAI_API_BASE_8001,
    api_key="EMPTY",
    temperature=0.7,
    max_tokens=1024,
)

llm_minimax_m2_1 = ChatOpenAI(
    model="MiniMax-M2.1",
    base_url=settings.OPENAI_API_BASE_8002,
    api_key="EMPTY",
    temperature=0.7,
    max_tokens=1024,
)

llm_modelscope_qwen3_vl_30b_a3b_instruct = ChatOpenAI(
    model="Qwen/Qwen3-VL-30B-A3B-Instruct",
    base_url=settings.MODELSCOPE_URL,
    api_key=settings.MODELSCOPE_SDK_TOKEN,
    temperature=0.7,
    max_tokens=1024,
)

if settings.LLM_MODE == 1:
    big_llm = llm_glm_5
    flash_llm = llm_modelscope_qwen3_vl_30b_a3b_instruct
else:
    big_llm = llm_minimax_m2_1
    flash_llm = llm_qwen3_vl_30b_a3b_instruct
