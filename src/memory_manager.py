"""Memory Manager for Mem0 integration."""

import json
from typing import Annotated

from langchain_core.tools import BaseTool, StructuredTool, InjectedState
from mem0 import Memory
from sqlalchemy.orm import Session

from src.config import settings
from src.llm_manager import get_llm_manager
from src.utils.get_logger import get_logger

logger = get_logger("memory-manager")


class MemoryManager:
    """Memory manager singleton for Mem0 integration."""

    _instance: "MemoryManager | None" = None
    _memory_client: Memory | None = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def init(self, db: Session):
        """
        Initialize mem0 client with database configuration.

        Args:
            db: Database session for fetching model configs
        """
        llm_config = self._get_llm_config(db)
        embedding_config = self._get_embedding_config(db)

        vector_store_config = {
            "provider": "qdrant",
            "config": {
                "collection_name": settings.MEM0_COLLECTION_NAME,
                "host": settings.MEM0_QDRANT_HOST,
                "port": settings.MEM0_QDRANT_PORT,
                "embedding_model_dims": embedding_config["config"]["embedding_dims"],
            },
        }

        config = {
            "vector_store": vector_store_config,
            "llm": llm_config,
            "embedder": embedding_config,
        }

        self._memory_client = Memory.from_config(config)
        logger.info("[MemoryManager] Initialized mem0 client with DB config")

    def _get_llm_config(self, db: Session) -> dict:
        """
        Get LLM config from database (reuse big role).

        Args:
            db: Database session

        Returns:
            Mem0 LLM config dict
        """
        llm_manager = get_llm_manager()
        config = llm_manager.get_active_config("big", db)

        if config:
            logger.info(f"[MemoryManager] Using DB LLM config: {config.name}")
            return {
                "provider": "openai",
                "config": {
                    "model": config.model_name,
                    "openai_api_key": config.api_key,
                    "openai_api_base": config.base_url,
                    "temperature": config.temperature,
                    "max_tokens": config.max_tokens or 2000,
                    **config.extra_params,
                },
            }

        logger.warning("[MemoryManager] LLM config not found in DB, using fallback")
        return self._get_fallback_llm_config()

    def _get_embedding_config(self, db: Session) -> dict:
        """
        Get Embedding config from database (embedding role).

        Args:
            db: Database session

        Returns:
            Mem0 Embedding config dict
        """
        llm_manager = get_llm_manager()
        config = llm_manager.get_active_config("embedding", db)

        if config:
            logger.info(f"[MemoryManager] Using DB Embedding config: {config.name}")
            return {
                "provider": "openai",
                "config": {
                    "model": config.model_name,
                    "api_key": config.api_key,
                    "openai_base_url": config.base_url,
                    "embedding_dims": config.extra_params.get("embedding_dims", 1024),
                },
            }

        logger.warning(
            "[MemoryManager] Embedding config not found in DB, using fallback"
        )
        return self._get_fallback_embedding_config()

    def _get_fallback_llm_config(self) -> dict:
        """Get fallback LLM config from environment variables."""
        return {
            "provider": "openai",
            "config": {
                "model": "glm-5",
                "openai_api_key": settings.ZHIPUAI_API_KEY,
                "openai_api_base": settings.ZHIPUAI_API_BASE,
                "temperature": 0,
            },
        }

    def _get_fallback_embedding_config(self) -> dict:
        """Get fallback Embedding config from environment variables."""
        return {
            "provider": "openai",
            "config": {
                "model": "Qwen3-Embedding-0.6B",
                "api_key": "dummy-key",
                "openai_base_url": "http://192.168.110.44:8008/v1",
                "embedding_dims": 1024,
            },
        }

    def reinit(self, db: Session):
        """
        Reinitialize mem0 client (call when config changes).

        Args:
            db: Database session
        """
        self._memory_client = None
        self.init(db)
        logger.info("[MemoryManager] Reinitialized with new config")

    def _extract_user_id(self, state: dict) -> str:
        """
        Extract user_id from tool state.

        Args:
            state: InjectedState dict

        Returns:
            user_id string
        """
        config = state.get("config", {})
        configurable = config.get("configurable", {})
        thread_id = configurable.get("thread_id")

        if not thread_id:
            return "default"

        user_id = thread_id[:36] if len(thread_id) > 37 else "default"
        return user_id

    def create_tools(self) -> list[BaseTool]:
        """Create memory tools list."""
        return [
            self._create_save_memory_tool(),
            self._create_search_memory_tool(),
            self._create_list_memories_tool(),
            self._create_delete_memory_tool(),
        ]

    def get_memory_client(self) -> Memory:
        """Get mem0 client instance."""
        if not self._memory_client:
            raise RuntimeError("MemoryManager not initialized")
        return self._memory_client

    def _create_save_memory_tool(self) -> BaseTool:
        """Create save memory tool."""

        def save_memory(
            content: str,
            metadata: dict | None = None,
            state: Annotated[dict, InjectedState] = None,
        ) -> str:
            """
            Save information to long-term memory.

            Args:
                content: Content to save
                metadata: Optional metadata
                state: Injected state (auto-injected)

            Returns:
                Save result message
            """
            user_id = self._extract_user_id(state)

            try:
                kwargs = {
                    "content": content,
                    "user_id": user_id,
                }

                if metadata:
                    kwargs["metadata"] = metadata

                result = self._memory_client.add(**kwargs)

                logger.info(f"[MemoryManager] Saved memory: {content[:50]}")

                return f"记忆已保存: {result}"

            except Exception as e:
                logger.exception(f"[MemoryManager] Failed to save memory: {e}")
                return f"保存失败: {str(e)}"

        return StructuredTool.from_function(
            name="save_memory",
            description="""保存信息到长期记忆系统。

何时保存长期记忆:
- 用户明确表达的个人偏好（编程语言、框架、工具）
- 用户的工作背景、技术栈
- 重要的项目信息、配置
- 跨会话有价值的信息

示例:
- save_memory("用户喜欢使用 Python 做数据分析", {"category": "preference"})
- save_memory("用户是后端工程师，技术栈为 Java", {"category": "background"})

注: 会话级短期记忆由LangGraph自动管理，无需手动保存
            """,
            func=save_memory,
        )

    def _create_search_memory_tool(self) -> BaseTool:
        """Create search memory tool."""

        def search_memory(
            query: str,
            limit: int = 5,
            state: Annotated[dict, InjectedState] = None,
        ) -> str:
            """
            Search relevant memories.

            Args:
                query: Query content
                limit: Number of results (default 5)
                state: Injected state (auto-injected)

            Returns:
                Memory list (JSON format)
            """
            user_id = self._extract_user_id(state)

            try:
                results = self._memory_client.search(
                    query=query,
                    user_id=user_id,
                    limit=limit,
                )

                memories = results.get("results", [])
                formatted = []
                for m in memories:
                    formatted.append(
                        {
                            "memory": m.get("memory"),
                            "score": m.get("score"),
                            "metadata": m.get("metadata"),
                        }
                    )

                logger.info(
                    f"[MemoryManager] Searched memory: query='{query}', found={len(memories)}"
                )

                return json.dumps(formatted, ensure_ascii=False, indent=2)

            except Exception as e:
                logger.exception(f"[MemoryManager] Failed to search memory: {e}")
                return f"检索失败: {str(e)}"

        return StructuredTool.from_function(
            name="search_memory",
            description="""检索相关记忆。

何时检索记忆:
- 用户询问"我之前说过..."、"我的偏好是..."
- 需要了解用户背景来做决策
- 继续之前的任务，需要上下文

示例:
- search_memory("用户的编程语言偏好")
- search_memory("技术栈")
        """,
            func=search_memory,
        )

    def _create_list_memories_tool(self) -> BaseTool:
        """Create list memories tool."""

        def list_memories(
            limit: int = 10,
            state: Annotated[dict, InjectedState] = None,
        ) -> str:
            """
            List all memories.

            Args:
                limit: Number of results (default 10)
                state: Injected state (auto-injected)

            Returns:
                Memory list (JSON format)
            """
            user_id = self._extract_user_id(state)

            try:
                results = self._memory_client.get_all(user_id=user_id, limit=limit)
                return json.dumps(results, ensure_ascii=False, indent=2)

            except Exception as e:
                logger.exception(f"[MemoryManager] Failed to list memories: {e}")
                return f"列出失败: {str(e)}"

        return StructuredTool.from_function(
            name="list_memories",
            description="列出用户的所有长期记忆。",
            func=list_memories,
        )

    def _create_delete_memory_tool(self) -> BaseTool:
        """Create delete memory tool."""

        def delete_memory(
            memory_id: str,
            state: Annotated[dict, InjectedState] = None,
        ) -> str:
            """
            Delete a specific memory.

            Args:
                memory_id: Memory ID to delete
                state: Injected state (auto-injected)

            Returns:
                Delete result message
            """
            try:
                self._memory_client.delete(memory_id)
                logger.info(f"[MemoryManager] Deleted memory: {memory_id}")
                return f"记忆 {memory_id} 已删除"

            except Exception as e:
                logger.exception(f"[MemoryManager] Failed to delete memory: {e}")
                return f"删除失败: {str(e)}"

        return StructuredTool.from_function(
            name="delete_memory",
            description="删除指定的长期记忆。",
            func=delete_memory,
        )


_memory_manager: MemoryManager | None = None


def get_memory_manager() -> MemoryManager:
    """Get memory manager singleton."""
    global _memory_manager
    if _memory_manager is None:
        _memory_manager = MemoryManager()
    return _memory_manager
