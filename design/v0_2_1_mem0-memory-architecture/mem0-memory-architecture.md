# Mem0 长期/短期记忆架构研究

## 概述

Mem0 是一个为 AI 应用提供记忆层的开源框架，通过分层存储和智能检索实现长期和短期记忆管理。

## 记忆分层架构

### 四层记忆模型

| 层级 | 生命周期 | 类型 | 用途 | 特点 |
|------|----------|------|------|------|
| **Conversation** | 单次响应 | 短期 | 工具调用、中间计算、chain-of-thought | 响应结束后丢失 |
| **Session** | 分钟~小时 | 短期 | 多步骤任务流程、onboarding、debugging | 需手动清理 |
| **User** | 周~永久 | 长期 | 用户偏好、账户状态、合规信息 | 需用户授权 |
| **Organization** | 全局配置 | 长期 | 共享FAQ、产品目录、策略 | 需管理员维护 |

### 短期记忆 vs 长期记忆

#### 短期记忆 (Short-term Memory)
- **对话历史 (Conversation History)** - 最近的对话轮次，保持时间顺序
- **工作记忆 (Working Memory)** - 临时状态，如工具输出、中间计算结果
- **注意力上下文 (Attention Context)** - 当前焦点的即时信息

#### 长期记忆 (Long-term Memory)
- **事实记忆 (Factual Memory)** - 用户偏好、账户详情、领域知识
- **情景记忆 (Episodic Memory)** - 过去交互的摘要、完成的任务
- **语义记忆 (Semantic Memory)** - 概念间的关系，支持推理

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
查询 → 向量化 → 多层检索 → 合并排序 → 返回结果
                     │
        ┌────────────┼────────────┐
        ↓            ↓            ↓
   User Memory  Session Memory  Conversation
   (长期-高优先) (短期-中优先)   (短期-低优先)
```

#### 检索优先级

1. **User Memory** - 用户级长期记忆，最高优先级
2. **Session Memory** - 会话级短期记忆，中等优先级
3. **Conversation History** - 最近对话，最低优先级

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

### 短期记忆使用 (Session)

```python
# 添加会话级短期记忆
memory.add(
    "我正在规划一个去巴黎的旅行",
    user_id="john",
    session_id="trip-planning-2025"  # 启用短期记忆
)

# 会话内检索
results = memory.search(
    "旅行计划",
    user_id="john",
    session_id="trip-planning-2025"
)

# 会话结束后清理
memory.reset(user_id="john", session_id="trip-planning-2025")
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
- 只实现了 User 级长期记忆
- 未启用 Session 级短期记忆

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
    
    def add_conversation_memory(
        self,
        messages: list,
        user_id: str,
        thread_id: str
    ):
        """添加对话记忆（短期+长期）"""
        return self.memory.add(
            messages,
            user_id=user_id,
            session_id=thread_id  # 使用 thread_id 作为 session_id
        )
    
    def get_relevant_memories(
        self,
        query: str,
        user_id: str,
        thread_id: str | None = None,
        limit: int = 5
    ) -> list:
        """检索相关记忆"""
        return self.memory.search(
            query,
            user_id=user_id,
            session_id=thread_id,
            limit=limit
        )
    
    def clear_session(self, user_id: str, thread_id: str):
        """清理会话记忆"""
        # 删除该 session 的短期记忆
        self.memory.delete_all(user_id=user_id, session_id=thread_id)
    
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

1. **记忆隔离**: 使用 `user_id` + `session_id` 组合确保记忆隔离
2. **及时清理**: 会话结束后清理短期记忆，避免存储膨胀
3. **元数据利用**: 使用 `metadata` 标记记忆类型、来源、重要性
4. **检索优化**: 合理设置 `limit` 参数，平衡召回率和响应速度
5. **版本管理**: 使用 `memory_id` 追踪记忆版本，支持回滚

## 参考资料

- [Mem0 官方文档](https://docs.mem0.ai)
- [Mem0 GitHub](https://github.com/mem0ai/mem0)
- [Memory Types 文档](https://docs.mem0.ai/core-concepts/memory-types)
