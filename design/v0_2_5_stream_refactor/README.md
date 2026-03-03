# v0.2.5 流式处理重构

## 概述

重构 `agent_manager.py` 中的 `stream_chat` 和 `stream_resume_interrupt` 方法，使用 LangGraph 原生流模式简化代码。

## 设计目标

1. **使用 LangGraph 原生能力** - 使用 `messages` + `updates` 组合
2. **最小化自定义代码** - 只封装必要的业务逻辑
3. **统一数据格式** - 全部使用 `subgraphs=True`
4. **清晰的责任分离** - 流处理 vs 业务逻辑

## LangGraph 原生流模式

> ⚠️ **重要**: 基于 `tests/test_langgraph_stream_format.py` 实测结果，详见 [00_actual_test_results.md](./00_actual_test_results.md)

| 模式 | 可用性 | 说明 | 用途 |
|------|--------|------|------|
| `messages` | ✅ | LLM token 流 | 实时输出内容 |
| `updates` | ✅ | 状态更新 + 工具 + `__interrupt__` | 工具事件、中断检测 |
| `values` | ✅ | 完整 state | 调试 |
| `tools` | ❌ | 不可用（返回 0 chunks）| - |

**推荐配置**: `stream_mode=["messages", "updates"]`

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
│           │      "updates"              │   (tools 模式不可用)  │
│           │    ],                       │                       │
│           │    subgraphs=True           │                       │
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

### 使用 `messages` + `updates` 组合

```python
# 所有模式都返回 tuple: (stream_mode: str, data: Any)
# subgraphs=True 时: (subgraph_path: tuple, stream_mode: str, data: Any)

async for subgraph_path, stream_mode, data in agent.astream(
    input,
    config=config,
    stream_mode=["messages", "updates"],
    subgraphs=True,
):
    if stream_mode == "messages":
        # data 是 tuple: (AIMessageChunk, metadata)
        if isinstance(data, tuple) and len(data) == 2:
            msg, metadata = data
            # 检测 tool_calls
            if hasattr(msg, 'tool_calls') and msg.tool_calls:
                for tc in msg.tool_calls:
                    if tc.get('name'):
                        yield formatter.make_tool_start_event(tc['name'])
            # 处理内容
            if hasattr(msg, 'content') and msg.content:
                yield formatter.make_content_event(str(msg.content))
    
    elif stream_mode == "updates":
        # data 是 dict: {"model": ..., "tools": ...}
        # 注意: data["tools"] 可能是 dict 而非 ToolMessage
        if "tools" in data:
            tool_data = data["tools"]
            if isinstance(tool_data, dict):
                tool_name = tool_data.get("name", "unknown")
            elif hasattr(tool_data, 'name'):
                tool_name = tool_data.name
            else:
                tool_name = "unknown"
            yield formatter.make_tool_end_event(tool_name)
        
        if "__interrupt__" in data:
            yield formatter.make_interrupt_event(data["__interrupt__"])
```

### 统一的错误处理

```python
# 工具异常会直接抛出，必须捕获
try:
    async for chunk in self._stream_one_cycle(...):
        yield chunk
except Exception as e:
    yield formatter.make_error_event(str(e))
    return
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
        yield formatter.make_interrupt_event(data)
```

## SSE 相关测试

测试文件 `tests/test_langgraph_stream_format.py` 覆盖以下场景：

| 测试项 | 说明 | 关键发现 |
|--------|------|---------|
| 错误处理 | 工具抛出异常 | 异常直接抛出，需 try/except |
| 中断恢复 | Command(resume=...) | 格式与正常流一致 |
| values state | state 累积 | 仅用于调试 |
| 并发重入 | 同 thread_id 并发 | 串行化执行，无异常 |
| 流取消 | 客户端断开 | checkpoint 正常保存 |
