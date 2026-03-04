# Mem0 记忆系统集成方案

> **重要说明**: 本方案仅实现User级长期记忆。Session级短期记忆由LangGraph Checkpointer自动管理,框架已内置完整支持。

## 📚 文档导航

- **后端集成方案**（本文档）- 后端架构设计和实现细节
- **[前端对接文档](./frontend-integration.md)** - 前端配置管理界面集成指南

## 一、架构概述

### 1.1 核心架构

```
┌─────────────────────────────────────────┐
│          AgentManager                    │
│  ┌───────────────────────────────────┐  │
│  │ System Prompt + Memory Tools      │  │
│  └───────────────────────────────────┘  │
└─────────────────────────────────────────┘
                ↓
┌─────────────────────────────────────────┐
│      MemoryManager (单例)                │
│  - 初始化 mem0 客户端                     │
│  - 创建记忆工具                           │
│  - 管理 Qdrant 配置                      │
└─────────────────────────────────────────┘
                ↓
┌─────────────────────────────────────────┐
│       Mem0 Memory (长期记忆)             │
│  - User 级（长期记忆）                    │
│  - Vector Store (Qdrant)                │
│  - Session级由LangGraph管理              │
└─────────────────────────────────────────┘
```

### 1.2 文件结构

```
backend/
├── src/
│   ├── memory_manager.py          # 【新增】记忆管理器
│   ├── agent_manager.py           # 【修改】集成记忆工具
│   └── config.py                  # 【修改】添加 mem0 配置
└── tests/
    └── test_memory_integration.py # 【新增】集成测试
```

## 二、记忆分层策略

### 2.1 长期记忆（User 级）

**特点**：
- 生命周期：永久（除非用户删除）
- 使用：只用 `user_id`
- 跨会话共享
- mem0 自动管理时间戳，检索时按相关性排序

**适用场景**：
- 用户偏好（编程语言、框架、工具）
- 工作背景、技术栈
- 重要项目信息、配置
- 团队约定、业务规则

**示例**：
```python
save_memory(
    content="用户偏好使用 Python 进行数据分析，常用 pandas 和 matplotlib",
    metadata={"category": "preference", "domain": "data_analysis"}
)
```

### 2.2 会话记忆（Session 级 - LangGraph管理）

**说明**：由LangGraph Checkpointer自动管理，无需Mem0实现

**特点**：
- 生命周期：单个会话（thread）
- 管理：LangGraph自动保存/恢复
- 用途：对话历史、工具调用记录、中断恢复

**实现方式**：
- 已在 `AgentManager` 中使用 `AsyncPostgresSaver`
- 每个thread的状态自动持久化
- 中断后可从checkpoint恢复

### 2.3 近期记忆

**实现方式**：利用 mem0 自动管理
- 长期记忆自带时间戳
- 检索时 mem0 自动按相关性排序（包含时间因素）
- 无需额外逻辑

## 三、记忆工具设计

### 3.1 工具列表

| 工具名 | 功能 | 参数 | 返回值 |
|--------|------|------|--------|
| `save_memory` | 保存记忆 | content, metadata | 保存结果 |
| `search_memory` | 检索记忆 | query, limit | 记忆列表 |
| `list_memories` | 列出记忆 | limit | 记忆列表 |
| `delete_memory` | 删除记忆 | memory_id | 成功/失败 |

### 3.2 save_memory 工具

**功能**：保存信息到记忆系统

**参数**：
- `content`: str - 要保存的内容（必需）
- `metadata`: dict | None - 元数据（可选）

**行为**：
1. Agent 判断信息是否值得保存为长期记忆
2. Mem0 自动进行：
   - LLM 提取关键信息
   - 冲突检测（是否需要更新已有记忆）
   - 决策处理（ADD/UPDATE/DELETE/NONE）
   - 向量化并存储

**关键代码**：
```python
def _create_save_memory_tool(self) -> BaseTool:
    """创建保存记忆工具"""
    def save_memory(
        content: str,
        metadata: dict | None = None,
        state: Annotated[dict, InjectedState] = None,
    ) -> str:
        """
        保存信息到长期记忆系统
        
        Args:
            content: 要保存的内容
            metadata: 可选的元数据
            state: 注入的状态（自动获取）
        
        Returns:
            保存结果
        """
        # 从 state 中提取 user_id
        user_id = self._extract_user_id(state)
        
        try:
            kwargs = {
                "content": content,
                "user_id": user_id,
            }
            
            # 添加元数据
            if metadata:
                kwargs["metadata"] = metadata
            
            # 调用 mem0 保存
            result = self._memory_client.add(**kwargs)
            
            logger.info(
                f"[MemoryManager] Saved memory: {content[:50]}"
            )
            
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
```

### 3.3 search_memory 工具

**功能**：检索相关记忆

**参数**：
- `query`: str - 查询内容（必需）
- `limit`: int - 返回数量（默认 5）

**行为**：
1. 向量化查询
2. 向量检索（User级长期记忆）
3. 按相关性排序返回（mem0 自动管理）

**关键代码**：
```python
def _create_search_memory_tool(self) -> BaseTool:
    """创建检索记忆工具"""
    def search_memory(
        query: str,
        limit: int = 5,
        state: Annotated[dict, InjectedState] = None,
    ) -> str:
        """
        检索相关记忆
        
        Args:
            query: 查询内容
            limit: 返回数量（默认 5）
            state: 注入的状态（自动获取）
        
        Returns:
            记忆列表（JSON 格式）
        """
        user_id = self._extract_user_id(state)
        
        try:
            results = self._memory_client.search(
                query=query,
                user_id=user_id,
                limit=limit,
            )
            
            # 格式化返回
            memories = results.get("results", [])
            formatted = []
            for m in memories:
                formatted.append({
                    "memory": m.get("memory"),
                    "score": m.get("score"),
                    "metadata": m.get("metadata"),
                })
            
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
```

### 3.4 list_memories 和 delete_memory 工具

**list_memories**: 列出用户的所有记忆
```python
def list_memories(
    limit: int = 10,
    state: Annotated[dict, InjectedState] = None,
) -> str:
    """列出所有记忆"""
    user_id = self._extract_user_id(state)
    
    results = self._memory_client.get_all(user_id=user_id, limit=limit)
    return json.dumps(results, ensure_ascii=False, indent=2)
```

**delete_memory**: 删除特定记忆
```python
def delete_memory(
    memory_id: str,
    state: Annotated[dict, InjectedState] = None,
) -> str:
    """删除记忆"""
    user_id = self._extract_user_id(state)
    
    self._memory_client.delete(memory_id)
    return f"记忆 {memory_id} 已删除"
```

## 四、MemoryManager 核心实现

### 4.1 类结构

```python
# src/memory_manager.py

from typing import Any
from mem0 import Memory
from langchain_core.tools import BaseTool, StructuredTool
from langchain_core.tools import InjectedState
from typing import Annotated
import json
from sqlalchemy.orm import Session

from src.config import settings
from src.llm_manager import get_llm_manager
from src.database import SessionLocal
from src.utils.get_logger import get_logger

logger = get_logger("memory-manager")


class MemoryManager:
    """记忆管理器单例"""
    
    _instance: "MemoryManager | None" = None
    _memory_client: Memory | None = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def init(self, db: Session):
        """
        初始化 mem0 客户端
        
        Args:
            db: 数据库会话，用于获取模型配置
        """
        # 从数据库获取LLM和Embedding配置
        llm_config = self._get_llm_config(db)
        embedding_config = self._get_embedding_config(db)
        
        # Qdrant配置（暂时使用环境变量，未来可扩展到数据库）
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
        从数据库获取Mem0的LLM配置（复用big角色）
        
        Args:
            db: 数据库会话
            
        Returns:
            Mem0 LLM配置字典
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
                    **config.extra_params
                }
            }
        
        # Fallback到环境变量
        logger.warning("[MemoryManager] LLM config not found in DB, using fallback")
        return self._get_fallback_llm_config()
    
    def _get_embedding_config(self, db: Session) -> dict:
        """
        从数据库获取Embedding配置（embedding角色）
        
        Args:
            db: 数据库会话
            
        Returns:
            Mem0 Embedding配置字典
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
                }
            }
        
        # Fallback到环境变量
        logger.warning("[MemoryManager] Embedding config not found in DB, using fallback")
        return self._get_fallback_embedding_config()
    
    def _get_fallback_llm_config(self) -> dict:
        """获取fallback LLM配置（从环境变量）"""
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
        """获取fallback Embedding配置（从环境变量）"""
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
        重新初始化mem0客户端（配置变更时调用）
        
        Args:
            db: 数据库会话
        """
        self._memory_client = None
        self.init(db)
        logger.info("[MemoryManager] Reinitialized with new config")
    
    def _extract_user_id(self, state: dict) -> str:
        """从 state 中提取 user_id"""
        config = state.get("config", {})
        configurable = config.get("configurable", {})
        thread_id = configurable.get("thread_id")
        
        if not thread_id:
            return "default"
        
        # thread_id 格式: {user_id}-{uuid}
        user_id = thread_id[:36] if len(thread_id) > 37 else "default"
        return user_id
    
    def create_tools(self) -> list[BaseTool]:
        """创建记忆工具列表"""
        return [
            self._create_save_memory_tool(),
            self._create_search_memory_tool(),
            self._create_list_memories_tool(),
            self._create_delete_memory_tool(),
        ]
    
    def get_memory_client(self) -> Memory:
        """获取 mem0 客户端"""
        if not self._memory_client:
            raise RuntimeError("MemoryManager not initialized")
        return self._memory_client


def get_memory_manager() -> MemoryManager:
    """获取记忆管理器单例"""
    return MemoryManager()
```

### 4.2 关键方法说明

**init(db: Session)**: 初始化mem0客户端
- 输入: 数据库会话
- 行为: 
  1. 从数据库获取`big`角色的LLM配置
  2. 从数据库获取`embedding`角色的Embedding配置
  3. 构建mem0配置并初始化客户端
  4. 如果数据库配置不存在，自动fallback到环境变量

**_get_llm_config(db: Session)**: 获取LLM配置
- 输入: 数据库会话
- 输出: Mem0 LLM配置字典
- 逻辑: 
  1. 调用LLMManager获取`big`角色的激活配置
  2. 转换为Mem0格式
  3. 失败时返回fallback配置

**_get_embedding_config(db: Session)**: 获取Embedding配置
- 输入: 数据库会话
- 输出: Mem0 Embedding配置字典
- 逻辑: 
  1. 调用LLMManager获取`embedding`角色的激活配置
  2. 转换为Mem0格式
  3. 失败时返回fallback配置

**reinit(db: Session)**: 重新初始化
- 用途: 配置变更后重新加载
- 调用时机: LLM或Embedding配置激活时

**_extract_user_id**: 从工具的 state 中提取用户ID
- 输入: InjectedState 注入的 state 字典
- 输出: user_id
- 逻辑: thread_id 格式为 `{user_id}-{uuid}`，取前 36 字符为 user_id

**create_tools**: 创建 4 个记忆工具
- 使用 `StructuredTool.from_function` 包装函数
- 通过 `InjectedState` 自动注入 state
- 提供详细的 description 引导 Agent

## 五、System Prompt 设计

### 5.1 记忆使用指南

```python
# src/agent_manager.py

MEMORY_SYSTEM_PROMPT = """
# 记忆系统使用指南

你拥有一个智能记忆系统，可以保存和检索信息。合理使用记忆系统能让你更好地服务用户。

## 何时保存记忆

保存以下信息为长期记忆，这些信息会跨会话保留：

1. **用户偏好**
   - 喜欢的编程语言、框架、工具
   - 代码风格偏好（缩进、命名规范等）
   - 工作习惯（喜欢详细解释还是简洁输出）

2. **用户背景**
   - 职业角色（前端/后端/全栈/数据科学家等）
   - 技术栈（Spring、Django、React、Vue 等）
   - 项目领域（电商、金融、AI、物联网等）

3. **重要事实**
   - 项目配置信息（数据库连接、API 端点）
   - 团队约定（Git 分支策略、代码审查流程）
   - 业务规则（折扣计算、用户权限）

示例：
- 用户说"我喜欢用 TypeScript" → save_memory("用户偏好使用 TypeScript", {"category": "preference"})
- 用户说"我是后端工程师，主要用 Java" → save_memory("用户是后端工程师，技术栈为 Java", {"category": "background"})

## 何时检索记忆

在以下情况下，主动调用 search_memory 检索相关信息：

1. **用户询问过往信息**
   - "我之前说过我喜欢什么语言？"
   - "我的技术栈是什么？"

2. **需要上下文做决策**
   - 选择技术方案时，参考用户偏好
   - 编写代码时，遵循用户的代码风格
   - 解释概念时，根据用户背景调整深度

示例：
- 用户问"我应该用哪个框架？" → search_memory("技术栈 框架偏好")
- 用户说"继续" → search_memory("任务进度 当前任务")

## 记忆管理原则

1. **质量优于数量**
   - 只保存真正有价值的信息
   - 避免保存临时性、易变的信息

2. **及时更新**
   - 当用户纠正信息时，保存新版本
   - Mem0 会自动处理冲突检测和更新

3. **主动检索**
   - 不要等用户提醒才去查记忆
   - 在需要决策时，主动参考用户偏好

## 注意事项

1. **隐私保护**
   - 不要保存敏感信息（密码、密钥、个人隐私）
   - 如果不确定，先询问用户

2. **避免冗余**
   - 不要重复保存相同信息
   - Mem0 会自动去重，但你应该有意识避免

3. **上下文相关性**
   - 保存时添加 metadata，方便后续检索
   - 使用有意义的标签（category、task、domain 等）

4. **性能考虑**
   - 不要过度频繁调用记忆工具
   - 检索时设置合理的 limit（默认 5）

注：会话级短期记忆（如当前任务进度、临时计算结果）由 LangGraph 自动管理，无需手动保存。
"""
```

### 5.2 集成到 AgentManager

```python
# src/agent_manager.py

DEFAULT_SYSTEM_PROMPT = f"""
用户的工作目录在/workspace中，若无明确要求，请在/workspace目录【及子目录】下执行操作,
当你不明确用户需求时，可以调用提问工具向用户提问(可以同时提多个问题)，这个提问工具最多调用两次
优先尝试使用已有的skill完成任务。
你有子agent时，优先尝试使用子agent处理专门的任务。
现在的时间是{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

{MEMORY_SYSTEM_PROMPT}
"""
```

## 六、集成步骤

### 6.1 修改文件清单

#### src/config.py
添加 Qdrant 向量数据库配置（仅此部分使用环境变量）

#### src/memory_manager.py（新增）
实现 MemoryManager 类，从数据库获取模型配置

#### src/agent_manager.py
1. 导入 MemoryManager 和 SessionLocal
2. 在 `__init__` 中初始化 MemoryManager
3. 在 `init` 方法中调用 `memory_manager.init(db)`
4. 在 `_build_agent` 中添加记忆工具
5. 更新 DEFAULT_SYSTEM_PROMPT

#### src/database.py
无需修改（复用现有的 LlmConfig 表）

### 6.2 集成代码示例

```python
# src/agent_manager.py

from src.memory_manager import get_memory_manager
from src.database import SessionLocal

class AgentManager:
    def __init__(self):
        # ... 现有代码 ...
        self.memory_manager = get_memory_manager()
    
    async def init(self):
        # ... 现有代码 ...
        
        # 初始化记忆管理器（传入db session获取配置）
        with SessionLocal() as db:
            self.memory_manager.init(db)
        
        await self._build_agent()
    
    async def _build_agent(self):
        # ... 现有代码 ...
        
        # 获取记忆工具
        memory_tools = self.memory_manager.create_tools()
        
        # 合并所有工具
        all_tools = mcp_tools + memory_tools
        
        # 创建 agent
        self.compiled_agent = create_deep_agent(
            model=big_llm,
            backend=lambda runtime: get_thread_backend(
                self._get_thread_id(runtime) or "default"
            ),
            checkpointer=self.checkpointer,
            tools=all_tools,  # 包含记忆工具
            # ... 其他参数 ...
        )
```

## 七、配置设计

### 7.1 config.py 添加（仅Qdrant配置）

```python
# src/config.py

class Settings(BaseSettings):
    # ... 现有配置 ...
    
    # Mem0 Qdrant 向量数据库配置
    MEM0_COLLECTION_NAME: str = "multi_agent_memory"
    MEM0_QDRANT_HOST: str = "localhost"
    MEM0_QDRANT_PORT: int = 6333
```

**说明**：
- Qdrant配置使用环境变量（基础设施配置）
- LLM和Embedding配置从数据库获取（动态可配置）

### 7.2 .env 文件添加

```bash
# Mem0 Qdrant 配置
MEM0_COLLECTION_NAME=multi_agent_memory
MEM0_QDRANT_HOST=localhost
MEM0_QDRANT_PORT=6333
```

### 7.3 数据库初始化 Embedding 配置

在部署时需要初始化一条 `role="embedding"` 的配置记录：

**方式1：通过管理界面（推荐）**

前端调用 `/api/admin/llm/configs` 接口创建配置，详见《前端对接文档》。

**方式2：通过初始化脚本**

```python
# scripts/init_embedding_config.py

from src.database import SessionLocal
from src.llm_manager import get_llm_manager

def init_embedding_config():
    llm_manager = get_llm_manager()
    
    with SessionLocal() as db:
        config = llm_manager.create_config(
            db=db,
            name="qwen3-embedding-0.6b",
            provider="openai",
            base_url="http://192.168.110.44:8008/v1",
            api_key="dummy-key",
            model_name="Qwen3-Embedding-0.6B",
            role="embedding",  # 关键：指定角色为embedding
            display_name="Qwen3 Embedding 0.6B",
            description="Embedding模型用于向量化文本",
            temperature=0,  # embedding通常temperature=0
            max_tokens=512,
            extra_params={"embedding_dims": 1024},  # 向量维度
            activate=True  # 激活此配置
        )
        
        print(f"Created embedding config: {config.id}")

if __name__ == "__main__":
    init_embedding_config()
```

### 7.4 配置说明

**LlmConfig表复用**：
- `role="big"`: 主模型（Agent推理、Mem0 LLM）
- `role="flash"`: 快速模型（快速响应）
- `role="embedding"`: Embedding模型（Mem0向量化）

**extra_params 字段**：
- `embedding_dims`: 向量维度（必需，用于Qdrant配置）
- 其他自定义参数

**切换配置流程**：
1. 创建新的embedding配置
2. 调用激活接口 `/api/admin/llm/configs/{config_id}/activate`
3. 后端自动重新初始化MemoryManager
4. 新配置立即生效

## 八、实施计划

### Phase 1: 基础集成（1-2 天）

**目标**：实现基本的记忆功能

**任务**：
1. 创建 `src/memory_manager.py`
2. 在 `config.py` 中添加 Qdrant 配置
3. 初始化数据库 Embedding 配置（`role="embedding"`）
4. 在 `agent_manager.py` 中集成记忆工具
5. 在 `api/admin.py` 中添加配置热更新逻辑
6. 编写基础测试 `tests/test_memory_integration.py`

**验证标准**：
- Agent 可以调用 save_memory 保存信息
- Agent 可以调用 search_memory 检索信息
- 配置从数据库正确加载
- 切换配置后MemoryManager自动重初始化
- 检索结果按相关性排序

### Phase 2: Prompt 优化（1 天）

**目标**：优化 System Prompt，让 Agent 更智能地使用记忆

**任务**：
1. 测试 Agent 在不同场景下的记忆使用
2. 根据测试结果调优 MEMORY_SYSTEM_PROMPT
3. 添加更多使用示例

**验证标准**：
- Agent 能主动保存用户偏好
- Agent 能在需要时主动检索记忆
- Agent 能正确区分短期/长期记忆

### Phase 3: 高级功能（可选，2-3 天）

**目标**：增强记忆管理能力

**任务**：
1. 实现记忆管理 API（查看、删除记忆）
2. 添加记忆统计功能
3. 实现记忆导出/导入功能

**验证标准**：
- 用户可以查看和管理自己的记忆
- 记忆数据可以导出备份

## 九、技术要点

### 9.1 工具上下文传递

**问题**：工具函数无法直接访问 user_id

**解决方案**：使用 `InjectedState`
```python
from langchain_core.tools import InjectedState
from typing import Annotated

def save_memory(
    content: str,
    metadata: dict | None = None,
    state: Annotated[dict, InjectedState] = None,  # 自动注入
) -> str:
    # 从 state 提取 user_id
    user_id = extract_user_id(state)
    # ...
```

### 9.2 记忆冲突处理

**问题**：用户纠正信息时，如何更新记忆？

**解决方案**：
- Mem0 内置冲突检测，会自动判断 ADD/UPDATE/DELETE
- 在 System Prompt 中引导 Agent 直接保存新信息即可
- 示例：用户说"其实我喜欢 JavaScript" → save_memory("用户偏好 JavaScript")

### 9.3 记忆检索相关性

**问题**：如何提高检索准确性？

**解决方案**：
1. 使用高质量的 Embedding 模型（Qwen3-Embedding）
2. 保存时添加有意义的 metadata
3. 检索时使用精确的查询词
4. 默认 limit=5，平衡召回率和性能

### 9.4 会话记忆管理

**策略**：完全依赖LangGraph
- LangGraph Checkpointer自动保存对话历史和状态
- 中断恢复由checkpointer自动处理
- 无需Mem0参与会话级记忆

### 9.5 配置动态获取

**问题**：如何动态管理LLM和Embedding配置？

**解决方案**：
1. **统一管理**：复用LlmConfig表，添加`role="embedding"`
2. **动态获取**：MemoryManager初始化时从数据库读取配置
3. **自动fallback**：数据库配置不存在时使用环境变量
4. **缓存机制**：LLMManager内部缓存，避免频繁查询数据库

**实现细节**：
```python
# 从数据库获取配置
llm_config = llm_manager.get_active_config("big", db)
embedding_config = llm_manager.get_active_config("embedding", db)

# 转换为Mem0格式
mem0_config = {
    "llm": {
        "provider": "openai",
        "config": {
            "model": llm_config.model_name,
            "openai_api_key": llm_config.api_key,
            "openai_api_base": llm_config.base_url,
            "temperature": llm_config.temperature,
            **llm_config.extra_params
        }
    },
    "embedder": {
        "provider": "openai",
        "config": {
            "model": embedding_config.model_name,
            "api_key": embedding_config.api_key,
            "openai_base_url": embedding_config.base_url,
            "embedding_dims": embedding_config.extra_params.get("embedding_dims", 1024),
        }
    }
}
```

### 9.6 配置热更新

**问题**：如何在不重启服务的情况下切换模型？

**解决方案**：
1. **激活配置API**：`POST /api/admin/llm/configs/{config_id}/activate`
2. **自动重初始化**：激活big或embedding角色时自动调用`memory_manager.reinit()`
3. **缓存失效**：LLMManager自动清除缓存

**实现代码**：
```python
# api/admin.py

@router.post("/llm/configs/{config_id}/activate")
def activate_llm_config(config_id: str, db: Session = Depends(get_db)):
    llm_manager = get_llm_manager()
    config = llm_manager.activate_config(config_id, db)
    
    if not config:
        raise HTTPException(status_code=404, detail="Config not found")
    
    # 如果是big或embedding角色，重新初始化MemoryManager
    if config.role in ["big", "embedding"]:
        from src.memory_manager import get_memory_manager
        from src.database import SessionLocal
        
        memory_manager = get_memory_manager()
        with SessionLocal() as db:
            memory_manager.reinit(db)
        
        logger.info(f"[Admin] MemoryManager reinitialized due to {config.role} config change")
    
    return {"message": "Config activated", "config_id": config_id}
```

**注意事项**：
- 重新初始化会重建mem0客户端，内存中的缓存会清空
- 已保存的向量数据不会丢失（存储在Qdrant中）
- 正在进行的会话不受影响（使用的是已初始化的客户端实例）

## 十、测试计划

### 10.1 单元测试

```python
# tests/test_memory_integration.py

def test_save_user_memory():
    """测试保存长期记忆"""
    # 1. 创建 MemoryManager
    # 2. 调用 save_memory
    # 3. 验证保存成功
    # 4. 调用 search_memory 验证能检索到

def test_search_memory():
    """测试检索记忆"""
    # 1. 保存多条记忆
    # 2. 调用 search_memory
    # 3. 验证按相关性排序

def test_memory_isolation():
    """测试记忆隔离（不同用户）"""
    # 1. 用户 A 保存记忆
    # 2. 用户 B 检索，验证无法看到 A 的记忆
```

### 10.2 集成测试

```python
def test_agent_with_memory():
    """测试 Agent 使用记忆的完整流程"""
    # 1. 用户首次对话，保存偏好
    # 2. 新会话，Agent 检索并应用偏好
    # 3. 验证 Agent 行为符合偏好
```

### 10.3 场景测试

1. **新用户场景**：无记忆，Agent 主动询问并保存
2. **老用户场景**：有记忆，Agent 主动应用偏好
3. **用户纠正**：更新记忆，验证冲突处理
4. **会话恢复**：测试LangGraph Checkpointer自动恢复功能

## 十一、监控与日志

### 11.1 关键日志

```python
# 保存记忆
logger.info(f"[MemoryManager] Saved {memory_type} memory: {content[:50]}")

# 检索记忆
logger.info(f"[MemoryManager] Searched memory: query='{query}', found={len(results)}")

# 错误日志
logger.exception(f"[MemoryManager] Failed to save memory: {e}")
```

### 11.2 监控指标（可选）

1. **记忆使用频率**
   - save_memory 调用次数
   - search_memory 调用次数
   - 成功率/失败率

2. **记忆质量**
   - 检索相关性（用户反馈）
   - 记忆冲突次数
   - 记忆更新次数

3. **性能指标**
   - 记忆操作延迟
   - 向量检索延迟

## 十二、架构变更总结

### 12.1 核心变更

**配置管理变更**：
- ❌ 删除：环境变量硬编码 LLM/Embedding 配置
- ✅ 新增：从数据库 `LlmConfig` 表动态获取配置
- ✅ 新增：支持 `role="embedding"` 的配置管理
- ✅ 新增：配置热更新机制（无需重启服务）

**MemoryManager 初始化变更**：
- `init()` → `init(db: Session)` （需要数据库会话）
- 新增 `_get_llm_config()` 从数据库获取 LLM 配置
- 新增 `_get_embedding_config()` 从数据库获取 Embedding 配置
- 新增 `reinit(db)` 支持配置热更新

**AgentManager 集成变更**：
```python
# 旧版本
self.memory_manager.init()

# 新版本
with SessionLocal() as db:
    self.memory_manager.init(db)
```

**配置激活变更**：
- 激活 `big` 或 `embedding` 角色配置时自动重新初始化 MemoryManager
- 添加在 `api/admin.py` 的 `activate_llm_config` 接口中

### 12.2 优势

✅ **统一管理**：所有模型配置（big/flash/embedding）在一个表中管理  
✅ **动态切换**：支持不重启服务切换 Embedding 模型  
✅ **配置复用**：复用现有的 LLMManager 和管理界面  
✅ **Fallback机制**：数据库配置失败时自动 fallback 到环境变量  
✅ **易于扩展**：未来可轻松添加更多角色（如 vision/audio）  
✅ **会话记忆**：LangGraph 自动管理，无需开发

### 12.3 前端配合

**前端需要做的事**：
1. 复用现有 LLM 配置管理界面
2. 添加 `role="embedding"` 的筛选和创建
3. 在 `extra_params` 中添加 `embedding_dims` 字段
4. 添加首次部署时的 Embedding 配置初始化引导

**详细说明**：见 [前端对接文档](./frontend-integration.md)

### 12.4 部署检查清单

**后端部署**：
- [ ] 添加 Qdrant 配置到 `.env` 文件
- [ ] 运行数据库迁移（如需）
- [ ] 初始化 Embedding 配置（`role="embedding"`）
- [ ] 测试记忆保存和检索功能
- [ ] 测试配置切换和热更新

**前端部署**：
- [ ] 更新 LLM 配置管理界面（支持 embedding 角色）
- [ ] 添加 Embedding 维度字段输入
- [ ] 添加首次部署引导提示
- [ ] 测试配置 CRUD 功能
- [ ] 测试配置激活功能

## 十三、参考资料

- [Mem0 官方文档](https://docs.mem0.ai)
- [Mem0 GitHub](https://github.com/mem0ai/mem0)
- [LangChain Tools 文档](https://python.langchain.com/docs/modules/tools/)
- [InjectedState 文档](https://python.langchain.com/docs/modules/tools/tools_as_functions/#injecting-state)
- [Qdrant 向量数据库](https://qdrant.tech/)
