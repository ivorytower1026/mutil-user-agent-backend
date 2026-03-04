"""Memory Manager for Mem0 integration."""

import json
from typing import Annotated

from langchain_core.tools import BaseTool, StructuredTool
from mem0 import Memory
from sqlalchemy.orm import Session
from langgraph.prebuilt import InjectedState
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
        config = llm_manager.get_active_config("flash", db)

        if config:
            logger.info(f"[MemoryManager] Using DB LLM config: {config.name}")
            return {
                "provider": "vllm",
                "config": {
                    "model": config.model_name,
                    "vllm_base_url": config.base_url,
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
            self._create_add_memory_tool(),
            self._create_search_memories_tool(),
            self._create_get_memories_tool(),
            self._create_get_memory_tool(),
            self._create_update_memory_tool(),
            self._create_delete_memory_tool(),
        ]

    def get_memory_client(self) -> Memory:
        """Get mem0 client instance."""
        if not self._memory_client:
            raise RuntimeError("MemoryManager not initialized")
        return self._memory_client

    def _create_add_memory_tool(self) -> BaseTool:
        """Create add memory tool."""

        def add_memory(
            text: str,
            metadata: dict | None = None,
            state: Annotated[dict, InjectedState] = None,
        ) -> str:
            """Save new memory."""
            user_id = self._extract_user_id(state)

            try:
                conversation = [{"role": "user", "content": text}]

                kwargs: dict = {"user_id": user_id}

                if metadata:
                    kwargs["metadata"] = metadata

                result = self._memory_client.add(conversation, **kwargs)

                logger.info(f"[MemoryManager] Added memory for user {user_id}: {text[:50]}")

                return json.dumps(result, ensure_ascii=False, indent=2)

            except Exception as e:
                logger.exception(f"[MemoryManager] Failed to add memory: {e}")
                return json.dumps({"error": str(e)}, ensure_ascii=False)

        return StructuredTool.from_function(
            name="add_memory",
            description="""保存信息到长期记忆系统。

            参数:
            - text (str, 必需): 要保存的记忆内容
            - metadata (dict, 可选): 元数据字典，如 {"category": "preference"}

            何时保存长期记忆:
            - 用户明确表达的个人偏好（编程语言、框架、工具）
            - 用户的工作背景、技术栈
            - 重要的项目信息、配置
            - 跨会话有价值的信息

            正确示例:
            - add_memory(text="用户喜欢使用 Python 做数据分析", metadata={"category": "preference"})
            - add_memory(text="用户是后端工程师，技术栈为 Java", metadata={"category": "background"})
            - add_memory(text="用户叫大熊")  # metadata 可选

            错误示例（不要这样调用）:
            - add_memory("用户喜欢Python", '{"category": "preference"}')  ❌ metadata 不能是字符串
            - add_memory("用户喜欢Python", "category=preference")  ❌ 不是字典格式

            注: 会话级短期记忆由LangGraph自动管理，无需手动保存
            """,
        func=add_memory,
        )

    def _create_search_memories_tool(self) -> BaseTool:
        """Create search memories tool."""

        def search_memories(
            query: str,
            limit: int = 5,
            state: Annotated[dict, InjectedState] = None,
        ) -> str:
            """Search memories (auto filter by current user)."""
            user_id = self._extract_user_id(state)

            try:

                results = self._memory_client.search(
                    query=query,
                    user_id=user_id,
                    limit=limit,
                )

                logger.info(
                    f"[MemoryManager] Searched memories for user {user_id}: "
                    f"query='{query}', found={len(results.get('results', []))}"
                )

                return json.dumps(results, ensure_ascii=False, indent=2)

            except Exception as e:
                logger.exception(f"[MemoryManager] Failed to search memories: {e}")
                return json.dumps({"error": str(e)}, ensure_ascii=False)

        return StructuredTool.from_function(
            name="search_memories",
            description="""检索相关记忆。

何时检索记忆:
- 用户询问"我之前说过..."、"我的偏好是..."
- 需要了解用户背景来做决策
- 继续之前的任务，需要上下文

示例:
- search_memories("用户的编程语言偏好")
- search_memories("技术栈")
        """,
            func=search_memories,
        )

    def _create_get_memories_tool(self) -> BaseTool:
        """Create get memories tool."""

        def get_memories(
            page: int = 1,
            page_size: int = 10,
            state: Annotated[dict, InjectedState] = None,
        ) -> str:
            """List memories (auto filter by current user, supports pagination)."""
            user_id = self._extract_user_id(state)

            try:

                results = self._memory_client.get_all(
                    user_id=user_id,
                    page=page,
                    page_size=page_size,
                )

                logger.info(
                    f"[MemoryManager] Got memories for user {user_id}: "
                    f"page={page}, page_size={page_size}"
                )

                return json.dumps(results, ensure_ascii=False, indent=2)

            except Exception as e:
                logger.exception(f"[MemoryManager] Failed to get memories: {e}")
                return json.dumps({"error": str(e)}, ensure_ascii=False)

        return StructuredTool.from_function(
            name="get_memories",
            description="列出用户的所有长期记忆（支持分页）。",
            func=get_memories,
        )

    def _create_get_memory_tool(self) -> BaseTool:
        """Create get single memory tool."""

        def get_memory(
            memory_id: str,
            state: Annotated[dict, InjectedState] = None,
        ) -> str:
            """Get single memory (validates ownership)."""
            user_id = self._extract_user_id(state)

            try:
                memory = self._memory_client.get(memory_id)

                memory_user_id = memory.get("user_id")
                if memory_user_id != user_id:
                    logger.warning(
                        f"[MemoryManager] User {user_id} attempted to access "
                        f"memory {memory_id} owned by {memory_user_id}"
                    )
                    return json.dumps(
                        {"error": "Memory not found or access denied"},
                        ensure_ascii=False
                    )

                logger.info(
                    f"[MemoryManager] Got memory {memory_id} for user {user_id}"
                )

                return json.dumps(memory, ensure_ascii=False, indent=2)

            except Exception as e:
                logger.exception(f"[MemoryManager] Failed to get memory: {e}")
                return json.dumps({"error": str(e)}, ensure_ascii=False)

        return StructuredTool.from_function(
            name="get_memory",
            description="获取单个记忆详情。",
            func=get_memory,
        )

    def _create_update_memory_tool(self) -> BaseTool:
        """Create update memory tool."""

        def update_memory(
            memory_id: str,
            text: str,
            state: Annotated[dict, InjectedState] = None,
        ) -> str:
            """Update memory content (validates ownership)."""
            user_id = self._extract_user_id(state)

            try:
                memory = self._memory_client.get(memory_id)

                memory_user_id = memory.get("user_id")
                if memory_user_id != user_id:
                    logger.warning(
                        f"[MemoryManager] User {user_id} attempted to update "
                        f"memory {memory_id} owned by {memory_user_id}"
                    )
                    return json.dumps(
                        {"error": "Memory not found or access denied"},
                        ensure_ascii=False
                    )

                result = self._memory_client.update(memory_id=memory_id, text=text)

                logger.info(
                    f"[MemoryManager] Updated memory {memory_id} for user {user_id}"
                )

                return json.dumps(result, ensure_ascii=False, indent=2)

            except Exception as e:
                logger.exception(f"[MemoryManager] Failed to update memory: {e}")
                return json.dumps({"error": str(e)}, ensure_ascii=False)

        return StructuredTool.from_function(
            name="update_memory",
            description="更新记忆内容。",
            func=update_memory,
        )

    def _create_delete_memory_tool(self) -> BaseTool:
        """Create delete memory tool."""

        def delete_memory(
            memory_id: str,
            state: Annotated[dict, InjectedState] = None,
        ) -> str:
            """Delete memory (validates ownership)."""
            user_id = self._extract_user_id(state)

            try:
                memory = self._memory_client.get(memory_id)

                memory_user_id = memory.get("user_id")
                if memory_user_id != user_id:
                    logger.warning(
                        f"[MemoryManager] User {user_id} attempted to delete "
                        f"memory {memory_id} owned by {memory_user_id}"
                    )
                    return json.dumps(
                        {"error": "Memory not found or access denied"},
                        ensure_ascii=False
                    )

                self._memory_client.delete(memory_id)

                logger.info(
                    f"[MemoryManager] Deleted memory {memory_id} for user {user_id}"
                )

                return json.dumps(
                    {"success": True, "message": f"Memory {memory_id} deleted"},
                    ensure_ascii=False
                )

            except Exception as e:
                logger.exception(f"[MemoryManager] Failed to delete memory: {e}")
                return json.dumps({"error": str(e)}, ensure_ascii=False)

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
