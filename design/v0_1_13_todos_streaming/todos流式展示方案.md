# DeepAgents TodoList 流式展示方案

> 版本: v0.1.13
> 日期: 2026-02-18
> 状态: 已完成

## 背景

DeepAgents 内置 `TodoListMiddleware`，提供 `write_todos` 工具，Agent 可以用它在执行复杂任务时进行任务规划和追踪。我们需要在前端实时展示这些 todos，让用户了解 Agent 的执行进度。

## DeepAgents TodoList 机制

### 核心特性
- **内置工具**: `write_todos` - Agent 调用此工具更新任务列表
- **状态管理**: todos 存储在 agent state 中
- **任务状态**: `pending`、`in_progress`、`completed`

### 数据结构
```python
todos = [
    {"content": "分析用户需求", "status": "completed"},
    {"content": "编写代码实现", "status": "in_progress"},
    {"content": "运行测试验证", "status": "pending"},
]
```

## 实现方案

### 方案选择

`write_todos` 是一个工具调用，与其他工具（如 `execute`、`write_file`）类似。通过 `tool/start` 和 `tool/end` 事件来传递 todos 数据，而不是单独的 `todos_updated` 事件。

**优势**：
- 与现有工具调用机制一致
- 历史记录可持久化（存储在 tool_calls 中）
- 刷新页面后可从历史记录恢复

### 技术实现

#### 后端改动

**1. `src/agent_utils/formatter.py`**

修改 `make_tool_start_event` 支持 todos 参数，修改 `_format_tool_update` 捕获 `write_todos` 工具调用：

```python
def make_tool_start_event(self, tool: str, todos: list[dict] | None = None) -> str:
    data: dict = {"tool": tool, "status": "running"}
    if todos:
        data["todos"] = todos
    return self.format(InternalEventType.TOOL_START, data)

def _format_tool_update(self, data: dict) -> str | None:
    for key, value in data.items():
        if key == "__interrupt__":
            continue
        
        if isinstance(value, dict):
            if "input" in value and "output" not in value:
                if key == "write_todos":
                    todos = value.get("input", {}).get("todos", [])
                    return self.sse.make_tool_start_event(key, todos)
                return self.sse.make_tool_start_event(key)
        # ...
```

**2. `src/agent_utils/session.py`**

修改 `get_history` 提取 AI 消息中的 `tool_calls`，如果是 `write_todos`，将参数作为 `todos` 字段返回：

```python
async def get_history(self, thread_id: str) -> dict:
    # ...
    if role == "assistant" and hasattr(msg, "tool_calls") and msg.tool_calls:
        tool_calls_data = []
        for tc in msg.tool_calls:
            tc_name = getattr(tc, "name", "") if hasattr(tc, "name") else tc.get("name", "")
            tc_args = getattr(tc, "args", {}) if hasattr(tc, "args") else tc.get("args", {})
            
            tool_call_entry = {
                "name": tc_name,
                "status": "completed"
            }
            
            if tc_name == "write_todos" and "todos" in tc_args:
                tool_call_entry["todos"] = tc_args["todos"]
            
            tool_calls_data.append(tool_call_entry)
        
        if tool_calls_data:
            formatted_msg["toolCalls"] = tool_calls_data
```

#### 前端改动

**1. `types/chat.ts`**

ToolCall 接口添加 `todos` 字段：

```typescript
export interface ToolCall {
  id: string
  name: string
  status: 'running' | 'completed'
  timestamp: Date
  todos?: Todo[]
}
```

**2. `stores/chat.ts`**

- `addToolCall` 支持接收 todos 参数
- `loadHistory` 正确映射 toolCalls 和 todos

**3. `composables/useChatStream.ts`**

`tool/start` 事件处理时传递 todos：

```typescript
case 'tool/start':
  if (event.tool) {
    chatStore.addToolCall({
      name: event.tool,
      todos: event.todos
    })
  }
  break
```

**4. `components/chat/ToolCallCard.vue`**

当 `toolCall.name === "write_todos"` 时，渲染 TodoListCard：

```vue
<template>
  <div v-if="isWriteTodos && toolCall.todos" class="tool-call-card">
    <TodoListCard :todos="toolCall.todos" />
  </div>
  <div v-else class="tool-call-card" :class="statusClass">
    <!-- 普通工具显示 -->
  </div>
</template>
```

**5. `components/chat/TodoListCard.vue`**

任务列表卡片组件，显示任务进度。

### SSE 事件格式

当 Agent 调用 `write_todos` 工具时，前端收到：

```
event: tool/start
data: {"tool":"write_todos","status":"running","todos":[{"content":"分析需求","status":"completed"},{"content":"编写代码","status":"in_progress"}]}

```

### 展示效果

```
┌─────────────────────────────────┐
│ 📋 任务计划           1/3      │
├─────────────────────────────────┤
│ ✅ 分析需求                      │
│ 🔄 编写代码                      │
│ ○ 测试验证                       │
└─────────────────────────────────┘
```

## 文件修改清单

### 后端
| 文件 | 修改内容 |
|------|----------|
| `src/agent_utils/formatter.py` | `make_tool_start_event` 支持 todos，`_format_tool_update` 捕获 write_todos |
| `src/agent_utils/session.py` | `get_history` 提取 tool_calls 中的 write_todos 数据 |

### 前端
| 文件 | 修改内容 |
|------|----------|
| `types/chat.ts` | ToolCall 接口添加 todos 字段 |
| `stores/chat.ts` | addToolCall 支持 todos，loadHistory 映射 toolCalls |
| `composables/useChatStream.ts` | tool/start 事件传递 todos |
| `components/chat/ToolCallCard.vue` | write_todos 渲染 TodoListCard |
| `components/chat/TodoListCard.vue` | 新建任务列表卡片组件 |

## 验证方式

1. 启动服务后，发送一个复杂任务（如"帮我创建一个完整的 Python 项目"）
2. 观察 SSE 事件流，应该能看到 `tool/start` 事件包含 `todos` 数据
3. 前端应该显示任务列表卡片，实时更新任务状态
4. 刷新页面后，历史记录中应该能看到之前的任务列表

## 注意事项

1. `write_todos` 是 DeepAgents 内置工具，Agent 会自动在需要时调用
2. todos 数据通过 tool/start 事件传递，与其他工具调用一致
3. 历史记录通过 tool_calls 持久化，刷新页面后可恢复
