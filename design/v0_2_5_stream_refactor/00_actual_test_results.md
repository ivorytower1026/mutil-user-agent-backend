# 00. LangGraph 流格式实测结果

## 测试环境

- 测试时间: 2026-03-02
- 测试文件: `tests/test_langgraph_stream_format.py`
- LangGraph 版本: 1.0+

## 核心发现

### 1. 返回格式（所有模式）

**无论单模式还是多模式，都返回 tuple:**

```python
# stream_mode=['messages']
(stream_mode: str, data: Any)

# stream_mode=['messages', 'updates']
(stream_mode: str, data: Any)
```

- `stream_mode`: 字符串，如 "messages", "updates", "values", "debug"
- `data`: 实际数据，类型取决于模式

### 2. subgraphs=True 的格式

```python
(subgraph_path: tuple, stream_mode: str, data: Any)
```

- `subgraph_path`: 元组，表示子图路径
- `stream_mode`: 字符串
- `data`: 实际数据

示例：
```python
((), "messages", (AIMessageChunk(...), {"langgraph_node": "agent"}))
```

### 3. messages 模式

```python
("messages", (AIMessageChunk(...), {"langgraph_node": "agent"}))
```

- `data[0]`: AIMessageChunk 或其他消息类型
- `data[1]`: dict，包含元数据如 `langgraph_node`

### 4. updates 模式

```python
("updates", {"model": AIMessageChunk(...)})
("updates", {"tools": ToolMessage(...)})
```

- `data`: dict
- keys: "model", "tools" 等
- values: 消息对象

**chunk 数量**: 3 个（model -> tools -> model）

### 5. values 模式

```python
("values", {"messages": [...], ...state})
```

- `data`: dict，包含完整 state
- 包含 "messages" 键和其他 state 字段

**chunk 数量**: 4 个

### 6. tools 模式 - 不可用

```python
stream_mode=["tools"]
# 返回 0 个 chunks
```

**结论**: `tools` 流模式在 `create_react_agent` 中不产生输出，不能用于获取工具事件。

### 7. debug 模式

```python
("debug", {"timestamp": "...", "step": "...", "payload": {...}})
```

- `data`: dict，包含调试信息

## 对设计的影响

### ❌ 不能使用 tools 流模式

设计文档中假设的 `tools` 流模式不可用：
```python
# ❌ 这个不会产生任何输出
elif stream_mode == "tools":
    if data["event"] == "on_tool_start":
        ...
```

### ✅ 必须使用 updates 模式检测工具

工具事件仍然需要从 `updates` 模式中提取：

```python
# ✅ 正确方法
if stream_mode == "updates":
    if "tools" in data:
        tool_msg = data["tools"]
        if hasattr(tool_msg, 'name'):
            # 这是工具调用结束
            yield formatter.tool_end(tool_msg.name)
```

### ✅ tuple 解包格式

设计文档中的解包格式是正确的：

```python
# 无 subgraphs
async for stream_mode, data in agent.astream(...):
    ...

# 有 subgraphs
async for subgraph_path, stream_mode, data in agent.astream(..., subgraphs=True):
    ...
```

## 实际代码示例

### messages 模式处理

```python
async for stream_mode, data in agent.astream(
    input,
    config=config,
    stream_mode=["messages"],
    subgraphs=True,
):
    if stream_mode == "messages":
        if isinstance(data, tuple) and len(data) == 2:
            msg, metadata = data
            if hasattr(msg, 'content') and msg.content:
                yield formatter.content(str(msg.content))
```

### updates 模式处理

```python
async for stream_mode, data in agent.astream(
    input,
    config=config,
    stream_mode=["updates"],
    subgraphs=True,
):
    if stream_mode == "updates":
        # 工具调用
        if "tools" in data:
            tool_msg = data["tools"]
            if hasattr(tool_msg, 'name'):
                yield formatter.tool_end(tool_msg.name)
        
        # 中断
        if "__interrupt__" in data:
            yield formatter.interrupt(data["__interrupt__"])
        
        # LLM 消息
        if "model" in data:
            msg = data["model"]
            # 可能有部分内容
```

### 多模式组合

```python
async for stream_mode, data in agent.astream(
    input,
    config=config,
    stream_mode=["messages", "updates"],
    subgraphs=True,
):
    if stream_mode == "messages":
        # 处理 token 流
        ...
    elif stream_mode == "updates":
        # 处理工具和中断
        ...
```

## 推荐配置

### 方案 1: messages + updates（推荐）

```python
stream_mode=["messages", "updates"]
subgraphs=True
```

- `messages`: 获取实时 token 流
- `updates`: 获取工具调用和中断

### 方案 2: 仅 updates

```python
stream_mode=["updates"]
subgraphs=True
```

- 只获取完整事件，没有 token 流
- chunk 数量少（3个）

### 方案 3: messages + updates + values + debug

```python
stream_mode=["messages", "updates", "values", "debug"]
subgraphs=True
```

- 获取所有信息
- chunk 数量最多（143个）
- 用于调试

## 总结

| 模式 | 可用性 | 用途 | Chunk 数量 |
|------|--------|------|-----------|
| messages | ✅ | token 流 | 125 |
| updates | ✅ | 工具 + 中断 | 3 |
| values | ✅ | 完整 state | 4 |
| debug | ✅ | 调试信息 | 多 |
| tools | ❌ | 不可用 | 0 |

**关键结论**:
1. 不使用 `tools` 流模式
2. 从 `updates` 模式提取工具事件
3. 使用 `messages` 模式获取 token 流
4. `subgraphs=True` 增加 subgraph_path 维度
