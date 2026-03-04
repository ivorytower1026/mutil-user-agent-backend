# Mem0 长期记忆架构研究

## 概述

> **重要说明**: 本方案专注于User级长期记忆的实现。Session级短期记忆由LangGraph Checkpointer自动管理,无需Mem0实现。

Mem0 是一个为 AI 应用提供记忆层的开源框架,通过向量化存储和智能检索实现长期记忆管理。

## 记忆分层架构

### 记忆模型（简化版）

> **注**: Session级记忆由LangGraph自带管理,本项目仅需实现User级长期记忆

| 层级 | 生命周期 | 类型 | 用途 | 特点 |
|------|----------|------|------|------|
| **Session** | 会话周期 | 短期 | LangGraph Checkpointer自动管理 | 框架内置 |
| **User** | 永久 | 长期 | 用户偏好、技术栈、项目信息 | 需用户授权 |
| **Organization** | 全局 | 长期 | 共享知识库、产品策略 | 需管理员维护 |

### 记忆类型

#### 短期记忆 (Session Memory - LangGraph内置)
- **对话历史** - LangGraph Checkpointer自动保存
- **工作状态** - Agent执行中间状态自动管理
- **会话上下文** - 无需手动管理，框架自动处理

#### 长期记忆 (Long-term Memory - Mem0实现)
- **事实记忆 (Factual Memory)** - 用户偏好、技术栈、工作背景
- **情景记忆 (Episodic Memory)** - 重要交互记录、完成的任务
- **语义记忆 (Semantic Memory)** - 概念关系、领域知识

## 技术实现原理

### 核心组件

```
┌─────────────────────────────────────────────────────────────┐
│                      Memory Client                           │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │  LLM Layer  │  │ Embedder    │  │   Vector Store      │  │
│  │  (提取/决策) │  │ (向量化)     │  │   (Qdrant/Milvus)   │  │
│  └─────────────┘  └─────────────┘  └─────────────────────┘  │
│                                                              │
│  ┌─────────────────────────────────────────────────────┐    │
│  │              Graph Memory (可选)                      │    │
│  │              实体关系存储 (Neo4j/Kuzu)                │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

### 记忆添加流程 (Memory.add)

```
输入消息 → LLM提取事实 → 冲突检测 → 决策处理 → Embedding → 向量存储
                │              │           │
                ↓              ↓           ↓
           提取关键信息    检查重复/冲突   ADD/UPDATE/DELETE/NONE
```

#### 详细步骤

1. **信息提取**: LLM 分析对话内容，提取具有长期价值的关键信息
2. **冲突检测**: 对比新旧记忆，判断是否需要更新
3. **决策处理**:
   - `ADD` - 新记忆，直接添加
   - `UPDATE` - 更新已有记忆（合并或修改）
   - `DELETE` - 删除过时记忆
   - `NONE` - 无需操作
4. **向量化**: 将记忆文本转换为向量表示
5. **存储**: 存入向量数据库（Qdrant、Milvus等）

### 记忆检索流程 (Memory.search)

```
查询 → 向量化 → 向量检索 → 相关性排序 → 返回结果
                     │
                     ↓
              User Memory (长期记忆)
```

#### 检索策略

- **User Memory** - 用户级长期记忆，按向量相似度排序
- **Session Memory** - 由LangGraph Checkpointer管理，会话内自动保持

## 代码使用示例

### 基础配置

```python
from mem0 import Memory

config = {
    "vector_store": {
        "provider": "qdrant",
        "config": {
            "collection_name": "test",
            "host": "localhost",
            "port": 6333,
            "embedding_model_dims": 1024,
        },
    },
    "llm": {
        "provider": "openai",  # 或 vllm
        "config": {
            "model": "gpt-4",
            "temperature": 0,
        },
    },
    "embedder": {
        "provider": "openai",
        "config": {
            "model": "text-embedding-3-small",
            "embedding_dims": 1024,
        },
    },
}

memory = Memory.from_config(config)
```

### 长期记忆使用 (User)

```python
# 添加用户级长期记忆
memory.add(
    "我喜欢麻辣火锅",
    user_id="john"
    # 不指定 session_id，存储为长期记忆
)

# 跨会话检索
results = memory.search(
    "我的饮食偏好是什么",
    user_id="john"
)
```

### 组织级共享记忆

```python
# 添加组织级记忆
memory.add(
    "公司退款政策：7天内无理由退款",
    user_id="john",
    metadata={"org_id": "company_001", "type": "policy"}
)
```

## 当前项目集成方案

### 现有测试文件分析

文件位置: `backend/tests/test_mem0.py`

当前实现:
- 仅使用 `user_id` 参数
- 实现了 User 级长期记忆
- Session级记忆由LangGraph Checkpointer管理

### 建议改进

```python
from mem0 import Memory

# 初始化配置 (复用现有配置)
config = {
    "vector_store": {
        "provider": "qdrant",
        "config": {
            "collection_name": "multi_agent_memory",
            "host": "localhost",
            "port": 6333,
            "embedding_model_dims": 1024,
        },
    },
    "llm": {
        "provider": "vllm",
        "config": {
            "model": "Qwen3-VL-30B-A3B-Instruct",
            "vllm_base_url": "http://192.168.110.44:8001/v1",
            "temperature": 0,
            "max_tokens": 2000,
        },
    },
    "embedder": {
        "provider": "openai",
        "config": {
            "model": "Qwen3-Embedding-0.6B",
            "api_key": "dummy-key",
            "openai_base_url": "http://192.168.110.44:8008/v1",
            "embedding_dims": 1024,
        },
    },
}

memory = Memory.from_config(config)

# 封装记忆管理类
class AgentMemoryManager:
    def __init__(self, memory_client: Memory):
        self.memory = memory_client
    
    def add_memory(
        self,
        content: str,
        user_id: str,
        metadata: dict | None = None
    ):
        """添加长期记忆"""
        return self.memory.add(
            content,
            user_id=user_id,
            metadata=metadata
        )
    
    def search_memory(
        self,
        query: str,
        user_id: str,
        limit: int = 5
    ) -> list:
        """检索相关记忆"""
        return self.memory.search(
            query,
            user_id=user_id,
            limit=limit
        )
    
    def get_user_context(self, user_id: str) -> str:
        """获取用户长期上下文"""
        memories = self.memory.get_all(user_id=user_id)
        return "\n".join([m["memory"] for m in memories.get("results", [])])
```

## 架构对比

| 特性 | Mem0 | LangChain Memory | Google ADK |
|------|------|-------------------|------------|
| 短期记忆 | Session | short-term | Session |
| 长期记忆 | User | long-term (扩展) | Memory |
| 向量存储 | 多种支持 | 多种支持 | 内置 |
| 图关系 | 支持 (Graph) | 不支持 | 不支持 |
| 冲突处理 | LLM自动 | 手动 | 手动 |

## 最佳实践

1. **记忆隔离**: 使用 `user_id` 确保用户间记忆隔离
2. **元数据利用**: 使用 `metadata` 标记记忆类型、来源、重要性
3. **检索优化**: 合理设置 `limit` 参数，平衡召回率和响应速度
4. **版本管理**: 使用 `memory_id` 追踪记忆版本，支持回滚
5. **Session记忆**: 依赖LangGraph Checkpointer自动管理，无需手动处理

## 参考资料

- [Mem0 官方文档](https://docs.mem0.ai)
- [Mem0 GitHub](https://github.com/mem0ai/mem0)
- [Memory Types 文档](https://docs.mem0.ai/core-concepts/memory-types)
