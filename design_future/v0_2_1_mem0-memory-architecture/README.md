# Mem0 记忆系统设计方案 v0.2.1

> **版本**: v0.2.1  
> **更新日期**: 2026-03-04  
> **状态**: 设计完成，待实施

## 📋 方案概述

本方案为 Multi-tenant AI Agent Platform 集成 Mem0 长期记忆系统，实现用户级跨会话记忆功能。

**核心特性**：
- ✅ User级长期记忆（Mem0实现）
- ✅ Session级短期记忆（LangGraph内置）
- ✅ 动态模型配置（数据库管理）
- ✅ 配置热更新（无需重启）
- ✅ 统一管理界面（复用LLM配置）

## 📚 文档索引

### 1. 架构研究
- **[mem0-memory-architecture.md](./mem0-memory-architecture.md)** - Mem0技术架构和原理研究
  - 记忆分层模型
  - 技术实现原理
  - 代码使用示例
  - 最佳实践

### 2. 后端集成方案
- **[integration-plan.md](./integration-plan.md)** - 后端详细设计和实现指南
  - 架构设计
  - 记忆分层策略
  - 工具设计
  - 配置管理
  - 集成步骤
  - 技术要点
  - 测试计划

### 3. 前端对接文档
- **[frontend-integration.md](./frontend-integration.md)** - 前端配置管理界面集成指南
  - LLM配置管理界面复用
  - Embedding配置创建和管理
  - 配置切换流程
  - 代码示例（React/Vue）
  - API接口汇总

## 🎯 核心架构

```
┌─────────────────────────────────────────┐
│          AgentManager                    │
│  - System Prompt + Memory Tools         │
└─────────────────────────────────────────┘
                ↓
┌─────────────────────────────────────────┐
│      MemoryManager (单例)                │
│  - init(db): 从数据库获取配置            │
│  - reinit(db): 配置热更新                │
│  - create_tools(): 创建记忆工具          │
└─────────────────────────────────────────┘
                ↓
┌─────────────────────────────────────────┐
│       LlmConfig (数据库表)               │
│  - role="big": 主模型                    │
│  - role="flash": 快速模型                │
│  - role="embedding": Embedding模型       │
└─────────────────────────────────────────┘
                ↓
┌─────────────────────────────────────────┐
│       Mem0 + Qdrant                     │
│  - User级长期记忆                        │
│  - 向量存储和检索                        │
└─────────────────────────────────────────┘
```

## 🔄 记忆分层

| 层级 | 生命周期 | 实现方式 | 用途 |
|------|----------|----------|------|
| **Session** | 会话周期 | LangGraph Checkpointer | 对话历史、工作状态 |
| **User** | 永久 | Mem0 + Qdrant | 用户偏好、技术栈、项目信息 |
| **Organization** | 全局 | Mem0 + Qdrant | 共享知识库、产品策略 |

## 🔧 关键技术点

### 1. 配置动态获取
- 从数据库 `LlmConfig` 表获取模型配置
- 支持 `role="embedding"` 配置
- 自动 fallback 到环境变量

### 2. 配置热更新
- 激活配置时自动重新初始化 MemoryManager
- 无需重启服务
- 已保存的记忆数据不丢失

### 3. 工具上下文传递
- 使用 `InjectedState` 自动注入 state
- 从 `thread_id` 提取 `user_id`
- 实现用户记忆隔离

### 4. 记忆冲突处理
- Mem0 内置冲突检测
- 自动判断 ADD/UPDATE/DELETE
- 无需手动管理版本

## 📦 实施计划

### Phase 1: 基础集成（1-2天）
- [x] 设计方案文档
- [ ] 创建 `src/memory_manager.py`
- [ ] 添加 Qdrant 配置
- [ ] 初始化 Embedding 配置
- [ ] 集成到 AgentManager
- [ ] 添加配置热更新逻辑
- [ ] 编写基础测试

### Phase 2: Prompt优化（1天）
- [ ] 测试不同场景
- [ ] 调优 System Prompt
- [ ] 添加使用示例

### Phase 3: 高级功能（可选，2-3天）
- [ ] 记忆管理 API
- [ ] 记忆统计功能
- [ ] 记忆导出/导入

### Phase 4: 前端集成（1天）
- [ ] 更新 LLM 配置管理界面
- [ ] 添加 Embedding 配置支持
- [ ] 添加初始化引导
- [ ] 测试配置切换

## 🚀 快速开始

### 1. 环境准备

```bash
# 安装依赖
uv add mem0ai qdrant-client

# 启动 Qdrant
docker run -p 6333:6333 qdrant/qdrant
```

### 2. 配置数据库

```bash
# 添加 Qdrant 配置到 .env
MEM0_COLLECTION_NAME=multi_agent_memory
MEM0_QDRANT_HOST=localhost
MEM0_QDRANT_PORT=6333
```

### 3. 初始化 Embedding 配置

**方式1：通过管理界面**
- 访问 `/admin/llm-configs`
- 创建 `role="embedding"` 的配置
- 激活配置

**方式2：通过脚本**
```python
# scripts/init_embedding_config.py
from src.database import SessionLocal
from src.llm_manager import get_llm_manager

llm_manager = get_llm_manager()
with SessionLocal() as db:
    llm_manager.create_config(
        db=db,
        name="qwen3-embedding-0.6b",
        provider="openai",
        base_url="http://192.168.110.44:8008/v1",
        api_key="dummy-key",
        model_name="Qwen3-Embedding-0.6B",
        role="embedding",
        temperature=0,
        max_tokens=512,
        extra_params={"embedding_dims": 1024},
        activate=True
    )
```

### 4. 测试记忆功能

```bash
# 启动服务
uv run python main.py

# 测试对话
curl -X POST http://localhost:8002/api/agent/chat \
  -H "Content-Type: application/json" \
  -d '{
    "thread_id": "test-001",
    "message": "我喜欢使用 Python 编程"
  }'
```

## 📊 性能考虑

### 向量检索优化
- 使用 Qdrant 高效向量索引
- 默认检索 top-5 结果
- 按相关性自动排序

### 配置缓存
- LLMManager 内部缓存模型实例
- 避免频繁查询数据库
- 配置变更时自动失效缓存

### 记忆管理
- 只保存有价值的长期记忆
- Mem0 自动去重和冲突处理
- 避免记忆数据膨胀

## 🔍 监控与日志

### 关键日志
```
[MemoryManager] Initialized mem0 client with DB config
[MemoryManager] Using DB LLM config: glm-5
[MemoryManager] Using DB Embedding config: qwen3-embedding-0.6b
[MemoryManager] Saved memory: 用户偏好使用 Python
[MemoryManager] Searched memory: query='编程语言', found=2
[MemoryManager] Reinitialized with new config
```

### 监控指标
- 记忆操作次数（save/search）
- 操作成功率
- 检索延迟
- 记忆数量

## ⚠️ 注意事项

### Embedding 维度兼容性
- 不同模型的向量维度可能不同
- 切换模型时注意兼容性
- 建议清空旧记忆或使用相同维度

### 配置切换影响
- 重新初始化会重建 mem0 客户端
- 内存缓存会清空
- 已保存的向量数据不丢失
- 正在进行的会话不受影响

### 隐私保护
- 不要保存敏感信息（密码、密钥）
- 遵守数据保护法规
- 提供记忆删除功能

## 📖 参考资料

- [Mem0 官方文档](https://docs.mem0.ai)
- [Mem0 GitHub](https://github.com/mem0ai/mem0)
- [Qdrant 文档](https://qdrant.tech/)
- [LangGraph Checkpointer](https://langchain-ai.github.io/langgraph/)

## 👥 维护者

- **后端**: Backend Team
- **前端**: Frontend Team
- **架构**: Architecture Team

---

**最后更新**: 2026-03-04  
**版本历史**: v0.2.1 - 简化Session级记忆，改为数据库配置管理
