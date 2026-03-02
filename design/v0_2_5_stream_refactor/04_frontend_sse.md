# 04. 前端 SSE 重构

## 概述

重构 `mutil-user-agent-front/src/api/sse.ts`，合并重复代码。

## 重构后的代码

```typescript
// src/api/sse.ts
import type { SSEEvent } from '@/types'
import type { AgentMode } from '@/types/chat'

const BASE_URL = import.meta.env.VITE_API_BASE_URL || ''

function getAuthHeaders(): Record<string, string> {
  const stored = sessionStorage.getItem('auth')
  if (!stored) return {}
  try {
    const { token } = JSON.parse(stored)
    return token ? { Authorization: `Bearer ${token}` } : {}
  } catch {
    return {}
  }
}

interface RawSSEEvent {
  event: string
  data: Record<string, unknown>
}

function parseEventBlock(block: string): RawSSEEvent | null {
  let event = ''
  let data = ''
  
  for (const line of block.split('\n')) {
    if (line.startsWith('event:')) {
      event = line.slice(6).trim()
    } else if (line.startsWith('data:')) {
      data = line.slice(5).trim()
    }
  }
  
  if (!event || !data) return null
  
  try {
    return { event, data: JSON.parse(data) }
  } catch {
    return null
  }
}

async function* parseSSEStream(
  stream: ReadableStream<Uint8Array>
): AsyncGenerator<RawSSEEvent> {
  const reader = stream.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  
  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      
      buffer += decoder.decode(value, { stream: true })
      
      const events = buffer.split('\n\n')
      buffer = events.pop() || ''
      
      for (const eventBlock of events) {
        const parsed = parseEventBlock(eventBlock)
        if (parsed) yield parsed
      }
    }
    
    if (buffer.trim()) {
      const parsed = parseEventBlock(buffer)
      if (parsed) yield parsed
    }
  } finally {
    reader.releaseLock()
  }
}

function mapToSSEEvent(raw: RawSSEEvent): SSEEvent {
  return {
    event: raw.event as SSEEvent['event'],
    content: raw.data.content as string | undefined,
    tool: raw.data.tool as string | undefined,
    status: raw.data.status as 'running' | 'completed' | undefined,
    info: raw.data.info as string | undefined,
    message: raw.data.message as string | undefined,
    data: raw.data.data as Record<string, unknown> | undefined,
    title: raw.data.title as string | undefined,
    questions: raw.data.questions as SSEEvent['questions'],
    todos: raw.data.todos as SSEEvent['todos'],
  }
}

async function* streamRequest<T extends object>(
  endpoint: string,
  body: T,
  signal?: AbortSignal
): AsyncGenerator<SSEEvent> {
  const response = await fetch(`${BASE_URL}${endpoint}`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...getAuthHeaders()
    },
    body: JSON.stringify(body),
    signal
  })
  
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}: ${await response.text()}`)
  }
  
  if (!response.body) {
    throw new Error('Response body is null')
  }
  
  for await (const raw of parseSSEStream(response.body)) {
    yield mapToSSEEvent(raw)
  }
}

// 导出的 API
export async function* streamChat(
  threadId: string,
  message: string,
  files?: string[],
  signal?: AbortSignal,
  mode: AgentMode = 'build'
): AsyncGenerator<SSEEvent> {
  yield* streamRequest(`/api/chat/${threadId}`, { message, files, mode }, signal)
}

export async function* streamResume(
  threadId: string,
  action: string,
  answers?: string[],
  signal?: AbortSignal,
  mode: AgentMode = 'build'
): AsyncGenerator<SSEEvent> {
  const body: { action: string; answers?: string[]; mode: AgentMode } = { action, mode }
  if (answers) body.answers = answers
  yield* streamRequest(`/api/resume/${threadId}`, body, signal)
}
```

## 变更对比

| 方面 | 旧代码 | 新代码 |
|------|--------|--------|
| 总行数 | ~180 行 | ~95 行 |
| 重复代码 | 两个函数各 ~60 行 | 共享 `streamRequest` |
| SSE 解析 | 内联 | `parseSSEStream` 函数 |

## 关键改进

1. **统一请求函数** - `streamRequest<T>` 泛型函数
2. **清晰解析流程** - `fetch → parseSSEStream → mapToSSEEvent`
3. **简化事件解析** - 使用 `split('\n\n')` 替代手动 buffer 处理
