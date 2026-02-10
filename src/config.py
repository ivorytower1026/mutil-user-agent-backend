import os
from pathlib import Path
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

load_dotenv()


def _resolve_path(path_str: str) -> str:
    path = Path(path_str).expanduser().absolute()
    return str(path)


llm = ChatOpenAI(
    model="glm-4.7",
    temperature=0,
    openai_api_key=os.getenv("ZHIPUAI_API_KEY", ""),
    openai_api_base=os.getenv("ZHIPUAI_API_BASE", "https://open.bigmodel.cn/api/paas/v4/"),
    extra_body={
        "response_format": {"type": "text"},
        "thinking": {"type": "enabled"}
    }
)

WORKSPACE_ROOT = _resolve_path(os.getenv("WORKSPACE_ROOT", "./workspaces"))

SHARED_DIR = _resolve_path(os.getenv("SHARED_DIR", "./shared"))

DOCKER_IMAGE = os.getenv("DOCKER_IMAGE", "python:3.13-slim")

CONTAINER_WORKSPACE_DIR = os.getenv("CONTAINER_WORKSPACE_DIR", "/workspace")

CONTAINER_SHARED_DIR = os.getenv("CONTAINER_SHARED_DIR", "/shared")
