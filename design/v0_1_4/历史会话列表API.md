# 历史会话列表 API

## 四件套分析

### 现象（实际）

- 用户每次进入应用只能创建新对话（`POST /sessions`），无法查看或继续历史对话
- LangGraph 的 checkpoint 数据已存储在 PostgreSQL 中，但无法按用户维度查询
- 现有 API 只有：创建会话、聊天、恢复中断、获取单个会话状态/历史
- 缺少「按用户列出所有会话」的能力

### 意图（期望）

- 用户可以看到自己的历史会话列表
- 用户可以选择继续某个历史会话
- 会话有标题便于识别
- 标题实时显示，无需刷新
- 支持分页，避免一次性加载过多数据

### 情境（环境约束）

- **数据层**：已有 LangGraph checkpoint 表，thread_id 格式为 `{user_id}-{uuid}`
- **标题存储**：新建 `threads` 表存储标题等元数据
- **现有依赖**：SQLAlchemy、PostgreSQL、AsyncPostgresSaver
- **标题生成**：已有 LLM 实例可复用
- **SSE 通道**：已有 `POST /chat/{thread_id}` 的 SSE 流式响应

### 边界（明确不做）

- 不实现会话删除的软删除/回收站
- 不实现会话搜索功能
- 不实现会话置顶/归档
- 不实现会话分享
- 不兼容历史数据（现有会话不在列表中显示）

---

## 实现方案

### 数据库模型

新增 `threads` 表：

```sql
CREATE TABLE threads (
    thread_id VARCHAR(100) PRIMARY KEY,
    user_id VARCHAR(50) NOT NULL,
    title VARCHAR(20),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_threads_user_id ON threads(user_id);
```

### API 设计

#### GET /sessions

获取当前用户的会话列表。

**请求参数：**

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| page | int | 1 | 页码 |
| page_size | int | 20 | 每页数量（最大100） |

**响应：**

```json
{
  "threads": [
    {
      "thread_id": "user123-abc...",
      "title": "Python数据分析",
      "created_at": "2026-02-14T10:00:00",
      "message_count": 5,
      "status": "idle"
    }
  ],
  "total": 1
}
```

---

## 标题实时推送方案

### 架构设计

```
┌─────────────────┐     ┌─────────────────┐
│   Agent Task    │     │   Title Task    │
│  (stream output)│     │  (LLM generate) │
└────────┬────────┘     └────────┬────────┘
         │                       │
         ▼                       ▼
    ┌─────────────────────────────────┐
    │         asyncio.Queue           │
    └────────────────┬────────────────┘
                     │
                     ▼
    ┌─────────────────────────────────┐
    │   Main Loop (yield to SSE)      │
    └─────────────────────────────────┘
```

**核心思路**：Agent 输出和标题生成是两个**完全独立**的并行任务，通过 `asyncio.Queue` 统一输出到 SSE 流。

### SSE 事件类型

| 事件名 | 说明 | 数据格式 |
|--------|------|----------|
| `messages/partial` | AI 回复内容片段 | `{"content": "你好"}` |
| `tool/start` | 工具调用开始 | `{"tool": "execute", "input": {...}}` |
| `tool/end` | 工具调用结束 | `{"tool": "execute", "output": {...}}` |
| `interrupt` | 需要人工确认 | `{"info": "...", "taskName": "..."}` |
| `title_updated` | **新增** 标题更新 | `{"title": "Python数据分析"}` |
| `end` | 流结束 | `{}` |
| `error` | 错误 | `{"message": "..."}` |

### SSE 事件时序示例

```
event: messages/partial    ← Agent 开始输出
data: {"content": "你好"}

event: messages/partial
data: {"content": "，我是"}

event: title_updated       ← 标题生成完成（随时插入，不等待 Agent）
data: {"title": "问候对话"}

event: messages/partial
data: {"content": "AI助手"}

event: end                 ← Agent 和标题都完成
data: {}
```

### 后端代码实现

```python
async def stream_chat(self, thread_id: str, message: str) -> AsyncIterator[str]:
    queue: asyncio.Queue[str | None] = asyncio.Queue()
    pending_count = 2  # agent_task + title_task
    
    with SessionLocal() as db:
        thread = db.query(Thread).filter(Thread.thread_id == thread_id).first()
        need_title = thread and thread.title is None
    
    async def agent_task():
        nonlocal pending_count
        try:
            handler, _ = init_langfuse()
            config = {"configurable": {"thread_id": thread_id}, "callbacks": [handler]}
            
            async for stream_mode, data in self.compiled_agent.astream(
                {"messages": [HumanMessage(content=message)]},
                config=config,
                stream_mode=["messages", "updates"],
            ):
                formatted = self._format_stream_data(stream_mode, data)
                if formatted:
                    await queue.put(formatted)
        except Exception as e:
            await queue.put(self._make_sse("error", {"message": str(e)}))
        finally:
            pending_count -= 1
            if pending_count == 0:
                await queue.put(None)  # 结束信号
    
    async def title_task():
        nonlocal pending_count
        if not need_title:
            pending_count -= 1
            return
        try:
            prompt = f"用5-10个字概括主题，只返回标题：{message[:100]}"
            response = await llm.ainvoke(prompt)
            title = response.content.strip()[:20]
            
            with SessionLocal() as db:
                thread = db.query(Thread).filter(Thread.thread_id == thread_id).first()
                if thread and thread.title is None:
                    thread.title = title
                    db.commit()
            
            await queue.put(self._make_sse("title_updated", {"title": title}))
        except Exception as e:
            print(f"[AgentManager] Title generation failed: {e}")
        finally:
            pending_count -= 1
            if pending_count == 0:
                await queue.put(None)
    
    # 启动并行任务
    asyncio.create_task(agent_task())
    asyncio.create_task(title_task())
    
    # 主循环：从队列读取并 yield
    while True:
        item = await queue.get()
        if item is None:
            break
        yield item
```

---

## 前端对接指南

### 1. 会话列表页

```typescript
// 获取会话列表
async function fetchSessions(page: number = 1) {
  const response = await fetch(`/api/sessions?page=${page}&page_size=20`, {
    headers: { 'Authorization': `Bearer ${token}` }
  });
  return response.json();
}

// 响应结构
interface ThreadListItem {
  thread_id: string;
  title: string | null;
  created_at: string;
  message_count: number;
  status: 'idle' | 'interrupted';
}

interface ThreadListResponse {
  threads: ThreadListItem[];
  total: number;
}
```

### 2. 聊天页 - SSE 事件处理

```typescript
class ChatSSEHandler {
  private eventSource: EventSource;
  
  constructor(threadId: string, token: string) {
    // 注意：EventSource 不支持自定义 header，需通过 URL 传 token
    // 或改用 fetch + ReadableStream
  }
  
  // 推荐：使用 fetch 方式
  async connect(threadId: string, message: string, token: string) {
    const response = await fetch(`/api/chat/${threadId}`, {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${token}`,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({ message })
    });
    
    const reader = response.body!.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';
      
      for (const line of lines) {
        this.parseSSELine(line);
      }
    }
  }
  
  private parseSSELine(line: string) {
    if (line.startsWith('event:')) {
      this.currentEvent = line.slice(6).trim();
    } else if (line.startsWith('data:')) {
      const data = JSON.parse(line.slice(5).trim());
      this.handleEvent(this.currentEvent, data);
    }
  }
  
  private currentEvent = '';
  
  private handleEvent(event: string, data: any) {
    switch (event) {
      case 'messages/partial':
        // 追加 AI 回复内容
        this.appendContent(data.content);
        break;
        
      case 'title_updated':
        // ⭐ 实时更新标题
        this.updateTitle(data.title);
        break;
        
      case 'interrupt':
        // 显示人工确认弹窗
        this.showInterruptDialog(data);
        break;
        
      case 'end':
        // 流结束
        this.onComplete();
        break;
        
      case 'error':
        this.showError(data.message);
        break;
    }
  }
  
  // 抽象方法，由组件实现
  abstract appendContent(content: string): void;
  abstract updateTitle(title: string): void;
  abstract showInterruptDialog(data: any): void;
  abstract onComplete(): void;
  abstract showError(message: string): void;
}
```

### 3. React 组件示例

```tsx
import { useState, useCallback } from 'react';

function ChatPage({ threadId, token }: { threadId: string; token: string }) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [title, setTitle] = useState<string | null>(null);
  const [isStreaming, setIsStreaming] = useState(false);
  
  const sendMessage = useCallback(async (content: string) => {
    setIsStreaming(true);
    
    const response = await fetch(`/api/chat/${threadId}`, {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${token}`,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({ message: content })
    });
    
    const reader = response.body!.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let currentEvent = '';
    let aiMessage = '';
    
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';
      
      for (const line of lines) {
        if (line.startsWith('event:')) {
          currentEvent = line.slice(6).trim();
        } else if (line.startsWith('data:')) {
          const data = JSON.parse(line.slice(5).trim());
          
          switch (currentEvent) {
            case 'messages/partial':
              aiMessage += data.content;
              // 实时更新 AI 消息
              setMessages(prev => {
                const updated = [...prev];
                const lastMsg = updated[updated.length - 1];
                if (lastMsg?.role === 'assistant') {
                  lastMsg.content = aiMessage;
                } else {
                  updated.push({ role: 'assistant', content: aiMessage });
                }
                return updated;
              });
              break;
              
            case 'title_updated':
              // ⭐ 实时更新页面标题
              setTitle(data.title);
              // 可选：同步更新侧边栏会话列表
              updateSidebarTitle(threadId, data.title);
              break;
              
            case 'end':
              setIsStreaming(false);
              break;
          }
        }
      }
    }
  }, [threadId, token]);
  
  return (
    <div>
      <h1>{title || '新对话'}</h1>
      {/* 消息列表 */}
      {/* 输入框 */}
    </div>
  );
}
```

### 4. 侧边栏会话列表同步

```typescript
// 全局状态管理（示例用 Zustand）
import { create } from 'zustand';

interface SessionStore {
  threads: ThreadListItem[];
  updateThreadTitle: (threadId: string, title: string) => void;
}

const useSessionStore = create<SessionStore>((set) => ({
  threads: [],
  updateThreadTitle: (threadId, title) =>
    set((state) => ({
      threads: state.threads.map((t) =>
        t.thread_id === threadId ? { ...t, title } : t
      )
    }))
}));

// 在 ChatPage 中调用
function updateSidebarTitle(threadId: string, title: string) {
  useSessionStore.getState().updateThreadTitle(threadId, title);
}
```

---

## 完整使用流程

```
1. 用户进入应用
   ↓
2. 前端调用 GET /sessions 获取会话列表
   ↓
3. 用户点击「新建」→ POST /sessions 创建会话
   ↓
4. 用户发送消息 → POST /chat/{thread_id} (SSE)
   ↓
5. SSE 推送 messages/partial（AI 回复）
   ↓
6. SSE 推送 title_updated（标题生成完成）⭐
   ↓
7. 前端实时更新页面标题和侧边栏
   ↓
8. SSE 推送 end（流结束）
```

---

## 修改清单

| 文件 | 改动内容 |
|------|----------|
| `src/database.py` | + `Thread` 模型 |
| `api/models.py` | + `ThreadListItem`, `ThreadListResponse` |
| `api/server.py` | + `GET /sessions` 端点 |
| `src/agent_manager.py` | 重构 `stream_chat`（双任务 + Queue），新增 `list_sessions` |

---

## 注意事项

1. **标题生成失败**：不影响聊天，前端显示"新对话"
2. **标题长度**：后端截断至 20 字，前端无需处理
3. **并发安全**：`pending_count` 确保两个任务都完成后才发送 `end` 事件
4. **历史数据**：不兼容，现有会话不在列表中显示
