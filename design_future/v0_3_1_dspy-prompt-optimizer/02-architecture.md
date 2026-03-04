# 架构设计

> **版本**: v0.3.1  
> **更新日期**: 2026-03-04

## 1. 系统架构

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        Multi-tenant AI Agent Platform                    │
│                        + DSPy Prompt Optimizer                           │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                      API Layer (FastAPI)                         │   │
│  │  ┌───────────────┐  ┌───────────────┐  ┌───────────────┐       │   │
│  │  │ /api/chat     │  │ /api/admin    │  │ /api/prompt-  │       │   │
│  │  │               │  │               │  │ optimizer     │       │   │
│  │  └───────────────┘  └───────────────┘  └───────────────┘       │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                    │                                    │
│                                    ▼                                    │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                    Prompt Optimizer Layer                        │   │
│  │  ┌───────────────┐  ┌───────────────┐  ┌───────────────┐       │   │
│  │  │ PromptOptimizer│  │ DataExtractor │  │ Metrics       │       │   │
│  │  │ (DSPy)        │  │               │  │               │       │   │
│  │  └───────────────┘  └───────────────┘  └───────────────┘       │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                    │                                    │
│                                    ▼                                    │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                    Agent Manager Layer                           │   │
│  │  ┌───────────────┐  ┌───────────────┐  ┌───────────────┐       │   │
│  │  │ AgentManager  │  │ AgentConfig   │  │ DeepAgents    │       │   │
│  │  │ (LangGraph)   │  │ Manager       │  │               │       │   │
│  │  └───────────────┘  └───────────────┘  └───────────────┘       │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                    │                                    │
│                                    ▼                                    │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                    Data Layer (PostgreSQL)                       │   │
│  │  ┌───────────────┐  ┌───────────────┐  ┌───────────────┐       │   │
│  │  │ Thread        │  │ AgentConfig   │  │ Optimization  │       │   │
│  │  │ (Checkpoints) │  │ Model         │  │ History       │       │   │
│  │  └───────────────┘  └───────────────┘  └───────────────┘       │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 2. 核心模块设计

### 2.1 PromptOptimizer

```python
class PromptOptimizer:
    """
    DSPy-based prompt optimizer using BootstrapFewShot.
    
    职责：
    - 配置 DSPy LLM (智谱AI)
    - 运行 BootstrapFewShot 优化
    - 返回优化后的 few-shot 示例
    """
    
    def __init__(self):
        self._configure_dspy()
    
    def optimize(self, current_prompt, training_examples, **kwargs):
        """运行优化流程"""
        pass
    
    def apply_optimization(self, agent_name, demos):
        """应用优化结果到 agent 配置"""
        pass
```

### 2.2 TrainingDataExtractor

```python
class TrainingDataExtractor:
    """
    从历史对话中提取训练数据。
    
    职责：
    - 查询 Thread 表获取历史对话
    - 从 LangGraph checkpoint 提取消息
    - 筛选成功对话构建训练集
    """
    
    def extract_successful_threads(self, limit, min_turns):
        """提取成功的对话作为训练数据"""
        pass
    
    def _extract_messages_from_checkpoint(self, thread_id):
        """从 checkpoint 提取消息"""
        pass
```

### 2.3 Metrics

```python
def create_agent_metric(threshold: float = 0.7):
    """
    创建 agent 响应评估指标。
    
    评估维度：
    - 响应完整性
    - 响应相关性
    - 错误检测
    - 期望输出匹配度
    """
    def metric(example, prediction, trace):
        # 评估逻辑
        return score  # 0-1
    return metric
```

---

## 3. 数据流

### 3.1 优化流程

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          Prompt 优化数据流                               │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  1. API 请求                                                            │
│     POST /api/prompt-optimizer/optimize                                 │
│     { "agent_name": "main", "sample_size": 50 }                         │
│                    │                                                    │
│                    ▼                                                    │
│  2. 获取当前配置                                                         │
│     AgentConfigManager.get_config(agent_name)                           │
│     → system_prompt                                                     │
│                    │                                                    │
│                    ▼                                                    │
│  3. 提取训练数据                                                         │
│     TrainingDataExtractor.extract_successful_threads()                  │
│     → [Example(user_input, response), ...]                             │
│                    │                                                    │
│                    ▼                                                    │
│  4. 运行 DSPy 优化                                                      │
│     PromptOptimizer.optimize(current_prompt, training_examples)        │
│     → { success, demos, score }                                        │
│                    │                                                    │
│                    ▼                                                    │
│  5. 应用优化结果                                                         │
│     PromptOptimizer.apply_optimization(agent_name, demos)              │
│     → 更新 AgentConfig                                                  │
│                    │                                                    │
│                    ▼                                                    │
│  6. 返回结果                                                            │
│     { "success": true, "demo_count": 4, "score": 0.85 }                │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 3.2 BootstrapFewShot 内部流程

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    BootstrapFewShot 内部流程                             │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  输入: trainset = [Example(...), Example(...), ...]                    │
│                                                                         │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │ 1. 准备 Teacher Model                                             │  │
│  │    teacher = student.deepcopy()                                   │  │
│  │    teacher.demos = labeled_examples[:max_labeled_demos]           │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                              │                                          │
│                              ▼                                          │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │ 2. Bootstrap 循环                                                 │  │
│  │    for example in trainset:                                       │  │
│  │        prediction = teacher(**example.inputs())                   │  │
│  │        if metric(example, prediction) >= threshold:               │  │
│  │            收集 trace → 提取 demo                                 │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                              │                                          │
│                              ▼                                          │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │ 3. 训练 Student Model                                             │  │
│  │    student.demos = bootstrapped_demos + labeled_demos             │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                              │                                          │
│                              ▼                                          │
│  输出: optimized_program with predictor.demos                          │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 4. 数据库设计

### 4.1 新增表: PromptOptimizationHistory

```sql
CREATE TABLE prompt_optimization_history (
    id VARCHAR(50) PRIMARY KEY,
    agent_name VARCHAR(64) NOT NULL,
    
    -- 优化配置
    optimizer_type VARCHAR(32) DEFAULT 'bootstrap',
    max_demos INTEGER,
    metric_threshold FLOAT,
    
    -- 优化结果
    demo_count INTEGER,
    score FLOAT,
    demos_data JSON,  -- 序列化的 few-shot 示例
    
    -- 状态
    is_applied BOOLEAN DEFAULT FALSE,
    applied_at TIMESTAMP,
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    INDEX idx_agent_name (agent_name),
    INDEX idx_created_at (created_at)
);
```

### 4.2 扩展表: AgentConfigModel

```python
# 可选：添加 demos 字段存储优化后的示例
class AgentConfigModel(Base):
    # ... 现有字段
    optimized_demos = Column(JSON, default=list)  # few-shot 示例
    last_optimized_at = Column(DateTime)
```

---

## 5. 配置管理

### 5.1 DSPy LLM 配置

```python
# src/prompt_optimizer/optimizer.py

def _configure_dspy(self):
    """配置 DSPy 使用智谱AI"""
    lm = dspy.LM(
        "openai/glm-5",  # 使用 OpenAI 兼容接口
        api_key=settings.ZHIPUAI_API_KEY,
        api_base=settings.ZHIPUAI_API_BASE,
    )
    dspy.configure(lm=lm)
```

### 5.2 优化参数配置

```python
# 默认优化参数
DEFAULT_OPTIMIZATION_CONFIG = {
    "max_bootstrapped_demos": 4,
    "max_labeled_demos": 8,
    "metric_threshold": 0.6,
    "sample_size": 50,
    "min_turns": 2,
}
```

---

## 6. 错误处理

### 6.1 异常类型

```python
class PromptOptimizationError(Exception):
    """Prompt 优化异常基类"""
    pass

class InsufficientDataError(PromptOptimizationError):
    """训练数据不足"""
    pass

class OptimizationFailedError(PromptOptimizationError):
    """优化过程失败"""
    pass

class ApplyOptimizationError(PromptOptimizationError):
    """应用优化失败"""
    pass
```

### 6.2 错误处理策略

| 错误类型 | 处理策略 |
|---------|---------|
| 训练数据不足 | 返回提示，建议积累更多数据 |
| LLM 调用失败 | 重试 3 次，记录日志 |
| 优化评分过低 | 返回警告，不自动应用 |
| 数据库写入失败 | 回滚事务，记录错误 |

---

## 7. 性能考虑

### 7.1 优化成本估算

| 参数 | 值 | 说明 |
|------|-----|------|
| 训练集大小 | 50 | 默认 sample_size |
| Bootstrap 轮数 | 1 | max_rounds |
| LLM 调用次数 | ~50-100 | 取决于成功率 |
| 预估成本 | $0.5-2 | 使用智谱AI |

### 7.2 缓存策略

```python
# 优化结果缓存
# - demos 序列化后存储在数据库
# - 避免重复优化相同的 agent 配置
# - 支持回滚到历史版本
```

### 7.3 异步优化

```python
# 对于大型优化任务，支持后台异步执行
@router.post("/optimize-async")
async def optimize_agent_prompt_async(request: OptimizeRequest):
    """异步优化（后台任务）"""
    task_id = create_background_task(optimize_task, request)
    return {"task_id": task_id, "status": "pending"}
```

---

## 8. 安全考虑

### 8.1 权限控制

- 只有管理员可以触发优化
- 优化结果需要审核才能应用到生产

### 8.2 数据隐私

- 训练数据仅来自当前用户的历史对话
- 不跨用户共享训练数据

### 8.3 优化频率限制

```python
# 防止过度调用 LLM
MAX_OPTIMIZATIONS_PER_DAY = 10
MAX_OPTIMIZATIONS_PER_AGENT_PER_DAY = 2
```
