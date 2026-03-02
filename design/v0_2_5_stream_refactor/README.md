# v0.2.5 流式处理重构

## 概述

重构 `agent_manager.py` 中的 `stream_chat` 和 `stream_resume_interrupt` 方法，使用 LangGraph 原生流模式简化代码。

## 设计目标

1. **使用 LangGraph 原生能力** - 利用 `tools` 流模式自动获取工具事件
2. **最小化自定义代码** - 只封装必要的业务逻辑
3. **统一数据格式** - 全部使用 `subgraphs=True`
4. **清晰的责任分离** - 流处理 vs 业务逻辑

## LangGraph 原生流模式

| 模式 | 说明 | 用途 |
|------|------|------|
| `messages` | LLM token 流 | 实时输出内容 |
| `updates` | 状态更新 + `__interrupt__` | 中断检测 |
| `tools` | 工具生命周期事件 | 自动获取 tool_start/tool_end |

## 架构设计

```
┌─────────────────────────────────────────────────────────────────┐
│                        AgentManager                              │
│  ┌─────────────────┐        ┌─────────────────────────────────┐ │
│  │  stream_chat()  │        │  stream_resume_interrupt()      │ │
│  └────────┬────────┘        └───────────────┬─────────────────┘ │
│           │                                 │                   │
│           └─────────────┬───────────────────┘                   │
│                         ▼                                       │
│           ┌─────────────────────────────┐                      │
│           │     AgentStreamRunner       │  封装 auto_resume     │
│           │                             │                       │
│           │  agent.astream(             │                       │
│           │    stream_mode=[            │                       │
│           │      "messages",            │ ← LangGraph 原生      │
│           │      "updates",             │                       │
│           │      "tools"                │                       │
│           │    ]                        │                       │
│           │  )                          │                       │
│           └─────────────┬───────────────┘                      │
│                         ▼                                       │
│           ┌─────────────────────────────┐                      │
│           │     SSEFormatter            │  简单的格式化         │
│           └─────────────────────────────┘                      │
└─────────────────────────────────────────────────────────────────┘

业务逻辑层（独立）:
┌─────────────────────────────────────────────────────────────────┐
│  ResumeCommandBuilder  -  构建恢复命令                          │
│  ModeHandler          -  处理 build/plan 模式差异               │
└─────────────────────────────────────────────────────────────────┘
```

## 文件变更

### 新增文件

| 文件 | 说明 | 行数 |
|------|------|------|
| `src/agent_utils/stream/__init__.py` | 模块入口 | ~10 |
| `src/agent_utils/stream/runner.py` | AgentStreamRunner - 封装 auto_resume | ~80 |
| `src/agent_utils/stream/formatter.py` | SSEFormatter - 从现有迁移 | ~60 |
| `src/agent_utils/resume_builder.py` | ResumeCommandBuilder | ~70 |

### 修改文件

| 文件 | 变更说明 |
|------|----------|
| `src/agent_manager.py` | 使用新组件，简化为 ~80 行 |
| `mutil-user-agent-front/src/api/sse.ts` | 合并重复代码 |

### 删除文件

| 文件 | 说明 |
|------|------|
| `src/agent_utils/interrupt.py` | 逻辑迁移到新模块 |
| `src/agent_utils/formatter.py` | 迁移到 stream/formatter.py |

## 详细设计

参见：
- [01_stream_runner.md](./01_stream_runner.md) - 流执行器（使用原生流模式）
- [02_resume_builder.md](./02_resume_builder.md) - 恢复命令构建器
- [03_agent_manager.md](./03_agent_manager.md) - AgentManager 重构
- [04_frontend_sse.md](./04_frontend_sse.md) - 前端 SSE 重构

## 实施步骤

| 步骤 | 任务 | 预计改动 |
|------|------|----------|
| 1 | 创建 `stream/` 模块 | 新建 ~150 行 |
| 2 | 创建 `resume_builder.py` | 新建 ~70 行 |
| 3 | 重构 `agent_manager.py` | 修改 ~100 行 |
| 4 | 删除旧代码 | 删除 ~350 行 |
| 5 | 重构前端 `sse.ts` | 修改 ~80 行 |
| 6 | 测试验证 | 运行测试 |

**预计净减少代码**: ~200 行

## 关键简化

### 使用 `tools` 流模式

```python
# 旧代码：手动解析工具事件
if "tools" in data:
    tools_data = data["tools"]
    if isinstance(tools_data, dict) and "messages" in tools_data:
        for msg in tools_data["messages"]:
            if hasattr(msg, 'name'):
                return self.formatter.tool_end(msg.name)

# 新代码：直接使用 tools 流
elif stream_mode == "tools":
    # data 是标准化的工具事件
    if data["event"] == "on_tool_start":
        yield formatter.tool_start(data["name"], data.get("args"))
    elif data["event"] == "on_tool_end":
        yield formatter.tool_end(data["name"])
```

### 统一的 auto_resume 处理

```python
# 中断检测和处理集中在一处
if stream_mode == "updates" and "__interrupt__" in data:
    tool_name = self._extract_tool_name(data)
    if tool_name in AUTO_APPROVE_TOOLS and mode == "build":
        auto_resume = True
        break
    else:
        yield formatter.interrupt(data)
```
