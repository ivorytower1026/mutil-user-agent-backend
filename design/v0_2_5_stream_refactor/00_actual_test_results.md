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

---

## SSE 相关测试（2026-03-03 补充）

### 8. 错误处理格式

**工具异常会直接抛出，不在流中返回：**

```python
@tool
def error_tool(msg: str) -> str:
    raise ValueError(f"工具内部错误: {msg}")

# 调用时
async for stream_mode, data in agent.astream(...):
    ...  # 不会到达这里

# 异常直接抛出
# ValueError: 工具内部错误: xxx
```

**测试结果：**
- `messages` 模式：收到 9 个 chunks（工具调用前的 LLM 输出）
- `updates` 模式：收到 1 个 chunk（`{"model": {...}}`）
- **没有** `error` 键
- 异常直接抛出到调用方

**对设计的影响：**

```python
# ✅ 必须在 try/except 中捕获异常
async for chunk in stream_runner.run(...):
    yield chunk
# except 块中生成 SSE error 事件
except Exception as e:
    yield formatter.error(str(e))
```

### 9. 中断恢复后的流格式

**恢复后格式与正常流完全一致：**

```python
# 第一阶段：触发中断
async for stream_mode, data in agent.astream(..., interrupt_before=["tools"]):
    # data 包含 {"__interrupt__": [...]}
    ...

# 获取 snapshot
snapshot = await agent.aget_state(config)
# snapshot.next = ["tools"]

# 第二阶段：恢复执行
resume_command = Command(resume={"decisions": [{"type": "approve"}]})
async for stream_mode, data in agent.astream(resume_command, ...):
    # 格式与正常流完全一致！
    # messages: ("messages", (AIMessageChunk, metadata))
    # updates: ("updates", {"tools": ...})
    ...
```

**测试结果：**
- 第一阶段 chunks: 2 个（`model` → `__interrupt__`）
- 恢复后 chunks: 11 个（与正常 chat 相同格式）
- **无异常**

**对设计的影响：**
- `stream_chat` 和 `stream_resume` 可以共用 `AgentStreamRunner`
- 恢复逻辑只需构建正确的 `Command` 对象

### 10. values 模式 state 结构

**每次返回完整 state，messages 逐渐累积：**

```python
# Chunk 1: messages_count=1, [HumanMessage]
# Chunk 2: messages_count=2, [HumanMessage, AIMessage]
# Chunk 3: messages_count=3, [HumanMessage, AIMessage, ToolMessage]
# Chunk 4: messages_count=4, [HumanMessage, AIMessage, ToolMessage, AIMessage]
```

**对设计的影响：**
- 可用于调试，追踪 state 变化
- 生产环境不需要使用 `values` 模式

### 11. 并发/重入测试

**同一 thread_id 同时发起两个流：**

```python
# 两个并发请求
await asyncio.gather(
    run_stream1(),  # {"messages": [HumanMessage("北京天气")]}
    run_stream2(),  # {"messages": [HumanMessage("上海天气")]}
)

# 结果：两个都正常执行，无异常
# Stream 1: chunks=3
# Stream 2: chunks=4
```

**对设计的影响：**
- LangGraph 内部有锁/串行化机制
- 无需在后端额外处理并发
- **建议前端禁用重复请求**，避免用户困惑

### 12. 流取消测试

**客户端断开后 checkpoint 正常保存：**

```python
# 中途取消迭代
async for chunk in agent.astream(...):
    chunks_collected += 1
    if chunks_collected >= 3:
        break  # 模拟客户端断开

# 检查 checkpoint
snapshot = await agent.aget_state(config)
# snapshot.next = ["model"]  # 可恢复状态
# snapshot.values["messages"] = [HumanMessage(...)]  # 已保存

# 恢复执行
async for chunk in agent.astream({"messages": [...]}, config):
    ...  # 正常继续
```

**对设计的影响：**
- 客户端断开连接后，checkpoint 状态一致
- 可以正常恢复执行
- FastAPI `StreamingResponse` 断开时，迭代器会自动停止

---

## 更新后的设计建议

### 错误处理

```python
class AgentStreamRunner:
    async def run(self, ...) -> AsyncIterator[str]:
        try:
            async for chunk in self._stream_one_cycle(...):
                yield chunk
        except Exception as e:
            # 捕获工具异常，生成 SSE error 事件
            yield self.formatter.error(str(e))
```

### Resume 和 Chat 共用 Runner

```python
class AgentManager:
    async def stream_chat(self, ...):
        async for event in self.stream_runner.run(
            thread_id=thread_id,
            initial_input={"messages": messages},
            mode=mode,
        ):
            yield event

    async def stream_resume(self, ...):
        resume_command = ResumeCommandBuilder.build(...)
        async for event in self.stream_runner.run(
            thread_id=thread_id,
            initial_input=resume_command,  # Command 对象
            mode=mode,
        ):
            yield event
```

### 客户端断开处理

```python
# FastAPI 自动处理
@router.post("/chat/{thread_id}")
async def chat(...):
    return StreamingResponse(
        stream_events(),
        media_type="text/event-stream",
    )
# 客户端断开时，生成器迭代自动停止
# checkpoint 已保存，可恢复
```

---

## 完整测试结果汇总

| 测试项 | 结果 | 对设计的影响 |
|--------|------|-------------|
| 错误处理 | 异常直接抛出 | 需要 try/except 生成 SSE error |
| 中断恢复 | 格式与正常流一致 | Chat/Resume 共用 Runner |
| values state | messages 累积 | 仅用于调试 |
| 并发重入 | 串行化执行 | 前端禁用重复请求 |
| 流取消 | checkpoint 正常 | 可正常恢复 |
