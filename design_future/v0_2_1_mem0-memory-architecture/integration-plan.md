# Mem0 记忆系统集成方案

> **重要说明**: 本方案仅实现User级长期记忆。Session级短期记忆由LangGraph Checkpointer自动管理,框架已内置完整支持。

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

from src.config import settings
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
    
    def init(self):
        """初始化 mem0 客户端"""
        config = {
            "vector_store": {
                "provider": "qdrant",
                "config": {
                    "collection_name": settings.MEM0_COLLECTION_NAME,
                    "host": settings.MEM0_QDRANT_HOST,
                    "port": settings.MEM0_QDRANT_PORT,
                    "embedding_model_dims": settings.MEM0_EMBEDDING_DIMS,
                },
            },
            "llm": {
                "provider": "openai",
                "config": {
                    "model": settings.MEM0_LLM_MODEL,
                    "openai_api_key": settings.ZHIPUAI_API_KEY,
                    "openai_api_base": settings.ZHIPUAI_API_BASE,
                    "temperature": 0,
                },
            },
            "embedder": {
                "provider": "openai",
                "config": {
                    "model": settings.MEM0_EMBEDDING_MODEL,
                    "api_key": settings.MEM0_EMBEDDING_API_KEY,
                    "openai_base_url": settings.MEM0_EMBEDDING_BASE_URL,
                    "embedding_dims": settings.MEM0_EMBEDDING_DIMS,
                },
            },
        }
        
        self._memory_client = Memory.from_config(config)
        logger.info("[MemoryManager] Initialized mem0 client")
    
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
添加 Mem0 配置项

#### src/memory_manager.py（新增）
实现 MemoryManager 类

#### src/agent_manager.py
1. 导入 MemoryManager
2. 在 `__init__` 中初始化 MemoryManager
3. 在 `_build_agent` 中添加记忆工具
4. 更新 DEFAULT_SYSTEM_PROMPT

### 6.2 集成代码示例

```python
# src/agent_manager.py

from src.memory_manager import get_memory_manager

class AgentManager:
    def __init__(self):
        # ... 现有代码 ...
        self.memory_manager = get_memory_manager()
    
    async def init(self):
        # ... 现有代码 ...
        
        # 初始化记忆管理器
        self.memory_manager.init()
        
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

### 7.1 config.py 添加

```python
# src/config.py

class Settings(BaseSettings):
    # ... 现有配置 ...
    
    # Mem0 配置
    MEM0_COLLECTION_NAME: str = "multi_agent_memory"
    MEM0_QDRANT_HOST: str = "localhost"
    MEM0_QDRANT_PORT: int = 6333
    MEM0_EMBEDDING_DIMS: int = 1024
    
    # Mem0 LLM 配置（复用现有 LLM）
    MEM0_LLM_MODEL: str = "glm-5"
    
    # Mem0 Embedding 配置
    MEM0_EMBEDDING_MODEL: str = "Qwen3-Embedding-0.6B"
    MEM0_EMBEDDING_API_KEY: str = "dummy-key"
    MEM0_EMBEDDING_BASE_URL: str = "http://192.168.110.44:8008/v1"
```

### 7.2 .env 文件添加

```bash
# Mem0 配置
MEM0_COLLECTION_NAME=multi_agent_memory
MEM0_QDRANT_HOST=localhost
MEM0_QDRANT_PORT=6333
MEM0_EMBEDDING_DIMS=1024

MEM0_LLM_MODEL=glm-5

MEM0_EMBEDDING_MODEL=Qwen3-Embedding-0.6B
MEM0_EMBEDDING_API_KEY=dummy-key
MEM0_EMBEDDING_BASE_URL=http://192.168.110.44:8008/v1
```

## 八、实施计划

### Phase 1: 基础集成（1-2 天）

**目标**：实现基本的记忆功能

**任务**：
1. 创建 `src/memory_manager.py`
2. 在 `config.py` 中添加 Mem0 配置
3. 在 `agent_manager.py` 中集成记忆工具
4. 编写基础测试 `tests/test_memory_integration.py`

**验证标准**：
- Agent 可以调用 save_memory 保存信息
- Agent 可以调用 search_memory 检索信息
- 短期记忆和长期记忆隔离正确
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

## 十二、参考资料

- [Mem0 官方文档](https://docs.mem0.ai)
- [Mem0 GitHub](https://github.com/mem0ai/mem0)
- [LangChain Tools 文档](https://python.langchain.com/docs/modules/tools/)
- [InjectedState 文档](https://python.langchain.com/docs/modules/tools/tools_as_functions/#injecting-state)
- [Qdrant 向量数据库](https://qdrant.tech/)
