# v0.1.3 SSE 格式迁移方案

## 概述

将 SSE 输出格式改为官方 LangGraph 格式，保持现有 FastAPI 架构。

---

## 四件套

### 1. 现象（实际现状）

| 组件 | 当前实现 |
|------|----------|
| **SSE 格式** | 自定义 `data: {"type": "content", ...}` |
| **前端** | 需要自己处理 SSE |

**问题**：
- SSE 格式非标准，前端无法使用官方 `@langchain/langgraph-sdk`
- 已出现重复输出等 bug

---

### 2. 意图（期望目标）

| 组件 | 迁移后 |
|------|--------|
| **SSE 格式** | 官方格式 `event: messages/partial\ndata: {...}` |
| **前端** | 可使用官方 SSE 解析逻辑 |

---

### 3. 情境（环境约束）

| 约束 | 说明 |
|------|------|
| **保留 FastAPI** | 不迁移到 LangGraph Server |
| **保留 Langfuse** | 继续使用 Langfuse tracing |
| **保留 Docker 沙箱** | 核心功能不变 |
| **保留 JWT 认证** | 认证逻辑不变 |

---

### 4. 边界（明确不做）

| 不做 | 原因 |
|------|------|
| 迁移到 LangGraph Server | Langfuse 集成困难 |
| 改动 API 端点 | 只改 SSE 格式 |

---

## SSE 格式对比

### 旧格式

```
data: {"type": "content", "content": "你"}

data: {"type": "tool_start", "tool": "execute"}

data: {"type": "done"}
```

### 新格式（官方）

```
event: messages/partial
data: {"content": "你"}

event: tool/start
data: {"tool": "execute", "input": {...}}

event: end
data: {}
```

---

## 事件映射

| 旧 type | 新 event | 说明 |
|---------|----------|------|
| `content` | `messages/partial` | LLM token 流 |
| `tool_start` | `tool/start` | 工具调用开始 |
| `tool_end` | `tool/end` | 工具调用结束 |
| `interrupt` | `interrupt` | 中断确认 |
| `update` | `updates` | 状态更新 |
| `error` | `error` | 错误 |
| `done` | `end` | 流结束 |

---

## 代码改动

### agent_manager.py

```python
def _make_sse(self, event_type: str, data: dict) -> str:
    event_name_map = {
        "content": "messages/partial",
        "tool_start": "tool/start",
        "tool_end": "tool/end",
        "interrupt": "interrupt",
        "update": "updates",
        "structured": "structured",
        "error": "error",
        "done": "end",
    }
    event_name = event_name_map.get(event_type, event_type)
    
    if event_type == "content":
        sanitized = self._convert_for_json(data)
    else:
        sanitized = self._sanitize_for_json(data)
    
    return f"event: {event_name}\ndata: {json.dumps(sanitized, ensure_ascii=False)}\n\n"
```

---

## 前端集成（Vue）

### SSE 解析示例

```typescript
function parseSSE(text: string): {event: string, data: any}[] {
  const events: {event: string, data: any}[] = []
  const lines = text.split('\n')
  let currentEvent = ''

  for (const line of lines) {
    if (line.startsWith('event:')) {
      currentEvent = line.slice(6).trim()
    } else if (line.startsWith('data:')) {
      const dataStr = line.slice(5).trim()
      try {
        const data = JSON.parse(dataStr)
        if (currentEvent) {
          events.push({ event: currentEvent, data })
          currentEvent = ''
        }
      } catch {
        // ignore parse error
      }
    }
  }

  return events
}

// 使用示例
async function streamChat(threadId: string, message: string) {
  const response = await fetch(`/api/chat/${threadId}`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${token}`
    },
    body: JSON.stringify({ message })
  })

  const reader = response.body!.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break

    buffer += decoder.decode(value, { stream: true })
    const events = parseSSE(buffer)
    
    for (const { event, data } of events) {
      switch (event) {
        case 'messages/partial':
          // 处理 LLM token
          console.log('Token:', data.content)
          break
        case 'tool/start':
          console.log('Tool start:', data.tool)
          break
        case 'tool/end':
          console.log('Tool end:', data.output)
          break
        case 'interrupt':
          console.log('Interrupt:', data.info)
          break
        case 'end':
          console.log('Stream ended')
          break
        case 'error':
          console.error('Error:', data.message)
          break
      }
    }
  }
}
```

---

## 测试验证

### 1. 启动服务

```bash
uv run python main.py
```

### 2. 测试 SSE 输出

```bash
# 登录获取 token
TOKEN=$(curl -s -X POST http://localhost:8003/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"test","password":"test123"}' | jq -r '.access_token')

# 创建 thread
THREAD_ID=$(curl -s -X POST http://localhost:8003/api/sessions \
  -H "Authorization: Bearer $TOKEN" | jq -r '.thread_id')

# 测试流式对话
curl -N -X POST "http://localhost:8003/api/chat/$THREAD_ID" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"message":"你好"}'
```

### 3. 预期输出

```
event: messages/partial
data: {"content": "你"}

event: messages/partial
data: {"content": "好"}

event: messages/partial
data: {"content": "！"}

event: end
data: {}

```

---

## 参考资料

- [LangGraph Streaming API](https://docs.langchain.com/langsmith/streaming)
- [LangChain SSE Format](https://docs.langchain.com/langsmith/sse)
