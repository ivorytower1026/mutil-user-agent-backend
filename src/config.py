"""Configuration settings for the backend application."""

from pathlib import Path
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from langchain_openai import ChatOpenAI

from src.utils.get_root_path import get_project_root


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=get_project_root() / ".env", env_file_encoding="utf-8"
    )

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
    CONTAINER_SKILLS_DIR: str
    CONTAINER_SHARED_DIR: str

    # 数据库配置
    DATABASE_URL: str

    # JWT配置
    SECRET_KEY: str
    ACCESS_TOKEN_EXPIRE_HOURS: int

    PORT: int

    OPENAI_API_BASE_8001: str
    OPENAI_API_BASE_8002: str

    MODELSCOPE_SDK_TOKEN: str
    MODELSCOPE_URL: str

    # Skill 验证相关配置
    SKILL_IMAGES_DIR: str = "D:\\docker_volume\\mutil-user-agent\\skill-images"
    SKILL_IMAGE_VERSIONS_TO_KEEP: int = 5
    SKILL_PENDING_DIR: str = (
        ""  # 待验证 skill 目录，默认为 {WORKSPACE_ROOT}/skills_pending
    )
    SKILL_APPROVED_DIR: str = ""  # 已入库 skill 目录，默认为 {SHARED_DIR}/skills

    SKILL_DIR: str = ""
    SKILL_DISABLE_DIR: str = ""

    # Docker 资源限制
    DOCKER_CPU_LIMIT: float = 1.0  # CPU 核数
    DOCKER_MEMORY_LIMIT: str = "2g"  # 内存限制

    # 沙箱超时配置
    DOCKER_IDLE_TIMEOUT_SECONDS: int = 60  # 1 分钟无操作自动清理
    REDIS_URL: str = "redis://localhost:6379/0"

    LLM_MODE: int

    # Mem0 记忆系统配置
    MEMORY_ENABLED: int = 2  # 是否启用记忆功能 (1=开启, 0=关闭)
    MEM0_COLLECTION_NAME: str = "multi_agent_memory"
    MEM0_QDRANT_HOST: str = "192.168.11.16"
    MEM0_QDRANT_PORT: int = 6333

    @field_validator("IS_LANGFUSE", mode="before")
    def parse_is_langfuse(cls, v):
        return int(v)


def _resolve_path(path_str: str) -> str:
    """Resolve a path string to an absolute path."""
    path = Path(path_str).expanduser().absolute()
    return str(path)


# Global settings instance
settings = Settings()


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
