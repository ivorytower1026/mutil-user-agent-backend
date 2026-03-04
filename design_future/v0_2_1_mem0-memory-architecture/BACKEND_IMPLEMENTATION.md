# Mem0 记忆工具后端实现方案

> **版本**: v2.0 简化版  
> **更新日期**: 2026-03-04

## 实现概述

基于简化设计原则，实现6个核心记忆工具，自动注入user_id，禁止跨用户访问。

---

## 1. 修改 src/memory_manager.py

### 完整代码实现

```python
"""Memory Manager for Mem0 integration (Simplified Version)."""

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
    """Memory manager singleton for Mem0 integration (Simplified)."""

    _instance: "MemoryManager | None" = None
    _memory_client: Memory | None = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def init(self, db: Session):
        """Initialize mem0 client with database configuration."""
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
        """Get LLM config from database (reuse big role)."""
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
        """Get Embedding config from database (embedding role)."""
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
        """Reinitialize mem0 client (call when config changes)."""
        self._memory_client = None
        self.init(db)
        logger.info("[MemoryManager] Reinitialized with new config")

    def _extract_user_id(self, state: dict) -> str:
        """Extract user_id from tool state."""
        config = state.get("config", {})
        configurable = config.get("configurable", {})
        thread_id = configurable.get("thread_id")

        if not thread_id:
            return "default"

        user_id = thread_id[:36] if len(thread_id) > 37 else "default"
        return user_id

    def create_tools(self) -> list[BaseTool]:
        """Create memory tools list (6 tools)."""
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
        """Create add memory tool (text only)."""
        
        def add_memory(
            text: str,
            metadata: dict | None = None,
            state: Annotated[dict, InjectedState] = None,
        ) -> str:
            """
            Save a new memory (text only).
            
            Args:
                text: Text content to save
                metadata: Optional metadata
                state: Injected state (auto-injected)
            
            Returns:
                Save result (JSON)
            """
            user_id = self._extract_user_id(state)
            
            try:
                # Construct conversation format (Mem0 requires this)
                conversation = [{"role": "user", "content": text}]
                
                kwargs = {"user_id": user_id}
                
                if metadata:
                    kwargs["metadata"] = metadata
                
                result = self._memory_client.add(conversation, **kwargs)
                
                logger.info(
                    f"[MemoryManager] Added memory for user {user_id}: {text[:50]}"
                )
                
                return json.dumps(result, ensure_ascii=False, indent=2)
            
            except Exception as e:
                logger.exception(f"[MemoryManager] Failed to add memory: {e}")
                return json.dumps({"error": str(e)}, ensure_ascii=False)
        
        return StructuredTool.from_function(
            name="add_memory",
            description="""Save a new memory.

When to save:
- User preferences (programming languages, frameworks, tools)
- User background (job role, tech stack)
- Important facts (project info, configurations)

Examples:
- add_memory("User prefers Python for data analysis")
- add_memory("User is backend engineer using Java")

Note: Session-level memory is managed by LangGraph automatically.
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
            """
            Semantic search over existing memories.
            
            Args:
                query: Natural language query
                limit: Max results to return (default 5)
                state: Injected state (auto-injected)
            
            Returns:
                Memory list (JSON)
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
                    formatted.append({
                        "memory": m.get("memory"),
                        "score": m.get("score"),
                        "metadata": m.get("metadata"),
                    })
                
                logger.info(
                    f"[MemoryManager] Searched memories for user {user_id}: "
                    f"query='{query}', found={len(memories)}"
                )
                
                return json.dumps(formatted, ensure_ascii=False, indent=2)
            
            except Exception as e:
                logger.exception(f"[MemoryManager] Failed to search memories: {e}")
                return json.dumps({"error": str(e)}, ensure_ascii=False)
        
        return StructuredTool.from_function(
            name="search_memories",
            description="""Semantic search over existing memories.

When to search:
- User asks "what did I say about..."
- Need user background for decisions
- Continuing previous tasks

Examples:
- search_memories("programming language preference")
- search_memories("tech stack")
            """,
            func=search_memories,
        )

    def _create_get_memories_tool(self) -> BaseTool:
        """Create get memories tool (with pagination)."""
        
        def get_memories(
            page: int = 1,
            page_size: int = 10,
            state: Annotated[dict, InjectedState] = None,
        ) -> str:
            """
            List memories with pagination.
            
            Args:
                page: Page number (1-indexed, default 1)
                page_size: Items per page (default 10)
                state: Injected state (auto-injected)
            
            Returns:
                Memory list (JSON)
            """
            user_id = self._extract_user_id(state)
            
            try:
                results = self._memory_client.get_all(
                    user_id=user_id,
                    page=page,
                    page_size=page_size,
                )
                
                logger.info(
                    f"[MemoryManager] Listed memories for user {user_id}: "
                    f"page={page}, page_size={page_size}"
                )
                
                return json.dumps(results, ensure_ascii=False, indent=2)
            
            except Exception as e:
                logger.exception(f"[MemoryManager] Failed to list memories: {e}")
                return json.dumps({"error": str(e)}, ensure_ascii=False)
        
        return StructuredTool.from_function(
            name="get_memories",
            description="""List memories with pagination.

Use for browsing all memories. Use page and page_size for pagination.

Examples:
- get_memories()  # First page, 10 items
- get_memories(page=2, page_size=20)  # Second page, 20 items
            """,
            func=get_memories,
        )

    def _create_get_memory_tool(self) -> BaseTool:
        """Create get single memory tool (with ownership validation)."""
        
        def get_memory(
            memory_id: str,
            state: Annotated[dict, InjectedState] = None,
        ) -> str:
            """
            Get a single memory by ID (validates ownership).
            
            Args:
                memory_id: Memory ID to retrieve
                state: Injected state (auto-injected)
            
            Returns:
                Memory details (JSON)
            """
            user_id = self._extract_user_id(state)
            
            try:
                # Get memory
                memory = self._memory_client.get(memory_id)
                
                # Validate ownership
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
            description="""Get a single memory by ID.

Use when you know the exact memory_id (e.g., from search results).

Example:
- get_memory("mem_abc123")
            """,
            func=get_memory,
        )

    def _create_update_memory_tool(self) -> BaseTool:
        """Create update memory tool (with ownership validation)."""
        
        def update_memory(
            memory_id: str,
            text: str,
            state: Annotated[dict, InjectedState] = None,
        ) -> str:
            """
            Update memory text (validates ownership).
            
            Args:
                memory_id: Memory ID to update
                text: New text content
                state: Injected state (auto-injected)
            
            Returns:
                Update result (JSON)
            """
            user_id = self._extract_user_id(state)
            
            try:
                # Get memory to validate ownership
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
                
                # Update memory
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
            description="""Update memory text.

Use to correct or update existing memory. Validates ownership.

Example:
- update_memory("mem_abc123", "User prefers Python and JavaScript")
            """,
            func=update_memory,
        )

    def _create_delete_memory_tool(self) -> BaseTool:
        """Create delete memory tool (with ownership validation)."""
        
        def delete_memory(
            memory_id: str,
            state: Annotated[dict, InjectedState] = None,
        ) -> str:
            """
            Delete a memory (validates ownership).
            
            Args:
                memory_id: Memory ID to delete
                state: Injected state (auto-injected)
            
            Returns:
                Delete result (JSON)
            """
            user_id = self._extract_user_id(state)
            
            try:
                # Get memory to validate ownership
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
                
                # Delete memory
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
            description="""Delete a memory by ID.

Use to remove outdated or incorrect memories. Validates ownership.

Example:
- delete_memory("mem_abc123")
            """,
            func=delete_memory,
        )


_memory_manager: MemoryManager | None = None


def get_memory_manager() -> MemoryManager:
    """Get memory manager singleton."""
    global _memory_manager
    if _memory_manager is None:
        _memory_manager = MemoryManager()
    return _memory_manager
```

---

## 2. 更新 System Prompt

修改 `src/agent_manager.py` 中的 `MEMORY_SYSTEM_PROMPT`:

```python
MEMORY_SYSTEM_PROMPT = """
# 记忆系统使用指南

你拥有一个智能记忆系统，可以保存和检索信息。合理使用记忆系统能让你更好地服务用户。

## 可用工具

1. **add_memory** - 保存新记忆
2. **search_memories** - 语义搜索记忆
3. **get_memories** - 列出记忆（支持分页）
4. **get_memory** - 获取单个记忆（通过ID）
5. **update_memory** - 更新记忆内容
6. **delete_memory** - 删除记忆

## 何时保存记忆

保存以下信息为长期记忆，这些信息会跨会话保留：

1. **用户偏好**
   - 喜欢的编程语言、框架、工具
   - 代码风格偏好
   - 工作习惯

2. **用户背景**
   - 职业角色
   - 技术栈
   - 项目领域

3. **重要事实**
   - 项目配置信息
   - 团队约定
   - 业务规则

示例：
- add_memory("用户偏好使用 Python 做数据分析")
- add_memory("用户是后端工程师，技术栈为 Java")

## 何时检索记忆

在以下情况下，主动检索记忆：

1. **用户询问过往信息**
   - "我之前说过我喜欢什么语言？"
   - search_memories("编程语言偏好")

2. **需要上下文做决策**
   - 选择技术方案时，参考用户偏好
   - search_memories("技术栈")

3. **浏览所有记忆**
   - get_memories()  # 第一页
   - get_memories(page=2)  # 第二页

## 记忆管理原则

1. **质量优于数量** - 只保存有价值的信息
2. **及时更新** - 用户纠正信息时，update_memory
3. **主动检索** - 需要决策时主动查询
4. **保持准确** - 过时信息用 delete_memory 删除

## 注意事项

1. **隐私保护** - 不要保存敏感信息
2. **避免冗余** - 不要重复保存相同信息
3. **性能考虑** - 检索时设置合理的limit

注：会话级短期记忆由 LangGraph 自动管理，无需手动保存。
"""
```

---

## 3. 测试代码

```python
# tests/test_memory_tools.py

def test_add_memory():
    """测试保存记忆"""
    # 保存简单文本
    result = add_memory(text="用户喜欢Python")
    assert "error" not in result
    
    # 保存带元数据的记忆
    result = add_memory(
        text="用户是后端工程师",
        metadata={"category": "background"}
    )
    assert "error" not in result

def test_search_memories():
    """测试搜索记忆"""
    # 先保存
    add_memory(text="用户偏好使用 Python")
    
    # 搜索
    results = search_memories(query="编程语言")
    assert len(results) > 0

def test_get_memories():
    """测试列出记忆"""
    # 获取第一页
    page1 = get_memories(page=1, page_size=10)
    assert "results" in page1
    
    # 获取第二页
    page2 = get_memories(page=2, page_size=10)
    assert page1 != page2

def test_ownership_validation():
    """测试所有权验证"""
    # 用户A保存记忆
    memory_a = add_memory(text="用户A的记忆")
    memory_id = memory_a["id"]
    
    # 用户B尝试访问（应该失败）
    # 这里需要模拟不同的user_id
    # result = get_memory(memory_id) with user_b
    # assert "error" in result
```

---

## 4. 部署步骤

1. **更新代码**
   ```bash
   # 替换 src/memory_manager.py
   # 更新 src/agent_manager.py 的 System Prompt
   ```

2. **重启服务**
   ```bash
   uv run python main.py
   ```

3. **测试工具**
   ```bash
   uv run python tests/test_memory_tools.py
   ```

---

## 5. 关键变更总结

### 工具变更
- ✅ `save_memory` → `add_memory` (只支持text)
- ✅ `search_memory` → `search_memories`
- ✅ `list_memories` → `get_memories` (支持分页)
- ✅ 新增 `get_memory` (带ownership验证)
- ✅ 新增 `update_memory` (带ownership验证)
- ✅ `delete_memory` (带ownership验证)

### 安全增强
- ✅ 所有工具自动注入user_id
- ✅ get/update/delete验证ownership
- ✅ 禁止跨用户访问
- ✅ 统一错误处理

### 简化设计
- ✅ 移除messages支持
- ✅ 移除复杂filters
- ✅ 移除向后兼容
- ✅ 统一JSON返回格式

---

**实现状态**: 设计完成，待编码  
**预计工期**: 1天
