# v0.1.3 前端 SSE 集成方案

## 概述

本文档描述 Vue 前端如何集成新的 SSE 流式输出格式。

---

## SSE 格式

### 新格式（官方风格）

```
event: messages/partial
data: {"content": "你"}

event: messages/partial
data: {"content": "好"}

event: tool/start
data: {"tool": "execute", "input": {"command": "ls"}}

event: tool/end
data: {"tool": "execute", "output": {"result": "file1.txt\nfile2.txt"}}

event: interrupt
data: {"info": "需要确认执行命令"}

event: end
data: {}
```

### 事件类型映射

| event | 说明 | data 结构 |
|-------|------|-----------|
| `messages/partial` | LLM token 流 | `{"content": "xxx"}` 或 `{"is_final": true}` |
| `tool/start` | 工具调用开始 | `{"tool": "name", "input": {...}}` |
| `tool/end` | 工具调用结束 | `{"tool": "name", "output": {...}}` |
| `interrupt` | HITL 中断 | `{"info": "..."}` |
| `updates` | 状态更新 | `{"data": {...}}` |
| `error` | 错误 | `{"message": "..."}` |
| `end` | 流结束 | `{}` |

---

## Vue Composable 实现

### 1. useSSE.ts - SSE 解析核心

```typescript
// composables/useSSE.ts
import { ref, type Ref } from 'vue'

export interface SSEEvent {
  event: string
  data: Record<string, any>
}

export interface SSEOptions {
  onContent?: (content: string) => void
  onContentFinal?: () => void
  onToolStart?: (tool: string, input: Record<string, any>) => void
  onToolEnd?: (tool: string, output: Record<string, any>) => void
  onInterrupt?: (info: string) => void
  onUpdate?: (data: Record<string, any>) => void
  onError?: (message: string) => void
  onEnd?: () => void
}

export function useSSE() {
  const isConnected = ref(false)
  const error = ref<string | null>(null)

  function parseSSE(text: string): SSEEvent[] {
    const events: SSEEvent[] = []
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

  async function streamRequest(
    url: string,
    options: RequestInit,
    callbacks: SSEOptions
  ): Promise<void> {
    isConnected.value = true
    error.value = null
    let buffer = ''

    try {
      const response = await fetch(url, options)
      
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`)
      }

      const reader = response.body!.getReader()
      const decoder = new TextDecoder()

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const events = parseSSE(buffer)
        
        // 保留未完成的行
        const lastNewline = buffer.lastIndexOf('\n')
        buffer = lastNewline >= 0 ? buffer.slice(lastNewline + 1) : buffer

        for (const { event, data } of events) {
          handleEvent(event, data, callbacks)
        }
      }

      // 处理剩余 buffer
      if (buffer.trim()) {
        const events = parseSSE(buffer)
        for (const { event, data } of events) {
          handleEvent(event, data, callbacks)
        }
      }
    } catch (e) {
      error.value = (e as Error).message
      callbacks.onError?.(error.value)
    } finally {
      isConnected.value = false
      callbacks.onEnd?.()
    }
  }

  function handleEvent(
    event: string,
    data: Record<string, any>,
    callbacks: SSEOptions
  ): void {
    switch (event) {
      case 'messages/partial':
        if (data.content) {
          callbacks.onContent?.(data.content)
        } else if (data.is_final) {
          callbacks.onContentFinal?.()
        }
        break
      
      case 'tool/start':
        callbacks.onToolStart?.(data.tool, data.input || {})
        break
      
      case 'tool/end':
        callbacks.onToolEnd?.(data.tool, data.output || {})
        break
      
      case 'interrupt':
        callbacks.onInterrupt?.(data.info)
        break
      
      case 'updates':
        callbacks.onUpdate?.(data.data || data)
        break
      
      case 'error':
        callbacks.onError?.(data.message)
        break
      
      case 'end':
        callbacks.onEnd?.()
        break
    }
  }

  return {
    isConnected,
    error,
    streamRequest,
    parseSSE,
  }
}
```

### 2. useChat.ts - 聊天功能封装

```typescript
// composables/useChat.ts
import { ref, computed } from 'vue'
import { useSSE } from './useSSE'

export interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  timestamp: number
}

export interface ToolCall {
  tool: string
  input: Record<string, any>
  output?: Record<string, any>
  status: 'running' | 'done'
}

export interface ChatOptions {
  baseUrl: string
  getToken: () => string | null
}

export function useChat(options: ChatOptions) {
  const { baseUrl, getToken } = options
  const { streamRequest, isConnected, error } = useSSE()

  // State
  const messages = ref<Message[]>([])
  const currentContent = ref('')
  const currentToolCalls = ref<ToolCall[]>([])
  const interruptInfo = ref<string | null>(null)
  const threadId = ref<string | null>(null)
  const isLoading = computed(() => isConnected.value)

  // Generate unique ID
  function generateId(): string {
    return `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`
  }

  // Create new thread
  async function createThread(): Promise<string> {
    const token = getToken()
    if (!token) throw new Error('No authentication token')

    const response = await fetch(`${baseUrl}/sessions`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
    })

    if (!response.ok) throw new Error('Failed to create session')
    
    const data = await response.json()
    threadId.value = data.thread_id
    messages.value = []
    return data.thread_id
  }

  // Send message
  async function sendMessage(content: string): Promise<void> {
    // Add user message
    messages.value.push({
      id: generateId(),
      role: 'user',
      content,
      timestamp: Date.now(),
    })

    // Ensure thread exists
    if (!threadId.value) {
      await createThread()
    }

    // Reset state
    currentContent.value = ''
    currentToolCalls.value = []
    interruptInfo.value = null

    const token = getToken()
    
    await streamRequest(
      `${baseUrl}/chat/${threadId.value}`,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ message: content }),
      },
      {
        onContent: (text) => {
          currentContent.value += text
        },
        onContentFinal: () => {
          // Save assistant message when final
          if (currentContent.value) {
            messages.value.push({
              id: generateId(),
              role: 'assistant',
              content: currentContent.value,
              timestamp: Date.now(),
            })
            currentContent.value = ''
          }
        },
        onToolStart: (tool, input) => {
          currentToolCalls.value.push({
            tool,
            input,
            status: 'running',
          })
        },
        onToolEnd: (tool, output) => {
          const call = currentToolCalls.value.find(
            (c) => c.tool === tool && c.status === 'running'
          )
          if (call) {
            call.output = output
            call.status = 'done'
          }
        },
        onInterrupt: (info) => {
          interruptInfo.value = info
          // Save current content before interrupt
          if (currentContent.value) {
            messages.value.push({
              id: generateId(),
              role: 'assistant',
              content: currentContent.value,
              timestamp: Date.now(),
            })
            currentContent.value = ''
          }
        },
        onError: (msg) => {
          console.error('Chat error:', msg)
        },
      }
    )

    // Save any remaining content
    if (currentContent.value) {
      messages.value.push({
        id: generateId(),
        role: 'assistant',
        content: currentContent.value,
        timestamp: Date.now(),
      })
      currentContent.value = ''
    }
  }

  // Resume interrupt
  async function resume(action: 'continue' | 'cancel'): Promise<void> {
    if (!threadId.value) return

    interruptInfo.value = null
    currentContent.value = ''
    currentToolCalls.value = []

    const token = getToken()

    await streamRequest(
      `${baseUrl}/resume/${threadId.value}`,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ action }),
      },
      {
        onContent: (text) => {
          currentContent.value += text
        },
        onContentFinal: () => {
          if (currentContent.value) {
            messages.value.push({
              id: generateId(),
              role: 'assistant',
              content: currentContent.value,
              timestamp: Date.now(),
            })
            currentContent.value = ''
          }
        },
        onToolStart: (tool, input) => {
          currentToolCalls.value.push({
            tool,
            input,
            status: 'running',
          })
        },
        onToolEnd: (tool, output) => {
          const call = currentToolCalls.value.find(
            (c) => c.tool === tool && c.status === 'running'
          )
          if (call) {
            call.output = output
            call.status = 'done'
          }
        },
        onInterrupt: (info) => {
          interruptInfo.value = info
        },
        onEnd: () => {
          if (currentContent.value) {
            messages.value.push({
              id: generateId(),
              role: 'assistant',
              content: currentContent.value,
              timestamp: Date.now(),
            })
            currentContent.value = ''
          }
        },
      }
    )
  }

  // Clear chat
  function clearChat(): void {
    messages.value = []
    currentContent.value = ''
    currentToolCalls.value = []
    interruptInfo.value = null
    threadId.value = null
  }

  return {
    // State
    messages,
    currentContent,
    currentToolCalls,
    interruptInfo,
    threadId,
    isLoading,
    error,
    
    // Actions
    createThread,
    sendMessage,
    resume,
    clearChat,
  }
}
```

---

## Vue 组件示例

### ChatPanel.vue

```vue
<script setup lang="ts">
import { ref } from 'vue'
import { useChat } from '@/composables/useChat'

const props = defineProps<{
  threadId?: string
}>()

const {
  messages,
  currentContent,
  currentToolCalls,
  interruptInfo,
  isLoading,
  sendMessage,
  resume,
} = useChat({
  baseUrl: '/api',
  getToken: () => localStorage.getItem('token'),
})

const inputText = ref('')

async function handleSend() {
  if (!inputText.value.trim() || isLoading.value) return
  
  const message = inputText.value
  inputText.value = ''
  await sendMessage(message)
}

async function handleResume(action: 'continue' | 'cancel') {
  await resume(action)
}

function formatToolInput(input: Record<string, any>): string {
  if (typeof input === 'string') return input
  return JSON.stringify(input, null, 2)
}
</script>

<template>
  <div class="chat-panel">
    <!-- 消息列表 -->
    <div class="messages">
      <div
        v-for="msg in messages"
        :key="msg.id"
        :class="['message', msg.role]"
      >
        <div class="role">{{ msg.role === 'user' ? '👤' : '🤖' }}</div>
        <div class="content">{{ msg.content }}</div>
      </div>

      <!-- 流式输出中 -->
      <div v-if="currentContent" class="message assistant streaming">
        <div class="role">🤖</div>
        <div class="content">
          {{ currentContent }}<span class="cursor">▊</span>
        </div>
      </div>

      <!-- 工具调用 -->
      <div v-if="currentToolCalls.length > 0" class="tool-calls">
        <div
          v-for="(call, index) in currentToolCalls"
          :key="index"
          class="tool-call"
        >
          <div class="tool-header">
            <span class="tool-name">🔧 {{ call.tool }}</span>
            <span :class="['status', call.status]">
              {{ call.status === 'running' ? '⏳' : '✅' }}
            </span>
          </div>
          <pre v-if="call.input" class="tool-input">{{
            formatToolInput(call.input)
          }}</pre>
        </div>
      </div>

      <!-- 中断确认 -->
      <div v-if="interruptInfo" class="interrupt-panel">
        <div class="interrupt-info">⚠️ {{ interruptInfo }}</div>
        <div class="interrupt-actions">
          <button @click="handleResume('continue')" class="btn-continue">
            ✓ 继续
          </button>
          <button @click="handleResume('cancel')" class="btn-cancel">
            ✗ 取消
          </button>
        </div>
      </div>
    </div>

    <!-- 输入框 -->
    <div class="input-area">
      <input
        v-model="inputText"
        @keyup.enter="handleSend"
        :disabled="isLoading || !!interruptInfo"
        placeholder="输入消息..."
      />
      <button @click="handleSend" :disabled="isLoading || !!interruptInfo">
        {{ isLoading ? '发送中...' : '发送' }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.chat-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  max-width: 800px;
  margin: 0 auto;
}

.messages {
  flex: 1;
  overflow-y: auto;
  padding: 1rem;
}

.message {
  display: flex;
  gap: 0.5rem;
  margin-bottom: 1rem;
  padding: 0.75rem;
  border-radius: 8px;
}

.message.user {
  background: #e3f2fd;
  margin-left: 2rem;
}

.message.assistant {
  background: #f5f5f5;
  margin-right: 2rem;
}

.message.streaming .content {
  color: #666;
}

.cursor {
  animation: blink 1s infinite;
}

@keyframes blink {
  0%, 50% { opacity: 1; }
  51%, 100% { opacity: 0; }
}

.role {
  font-size: 1.5rem;
}

.content {
  flex: 1;
  white-space: pre-wrap;
  word-break: break-word;
}

.tool-calls {
  margin: 1rem 0;
  padding: 0.5rem;
  background: #fff3e0;
  border-radius: 8px;
}

.tool-call {
  margin-bottom: 0.5rem;
}

.tool-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.tool-name {
  font-weight: bold;
}

.tool-input {
  margin: 0.5rem 0;
  padding: 0.5rem;
  background: #fff;
  border-radius: 4px;
  font-size: 0.875rem;
  overflow-x: auto;
}

.interrupt-panel {
  margin: 1rem 0;
  padding: 1rem;
  background: #ffebee;
  border-radius: 8px;
  border-left: 4px solid #f44336;
}

.interrupt-info {
  margin-bottom: 1rem;
}

.interrupt-actions {
  display: flex;
  gap: 1rem;
}

.btn-continue,
.btn-cancel {
  padding: 0.5rem 1rem;
  border: none;
  border-radius: 4px;
  cursor: pointer;
}

.btn-continue {
  background: #4caf50;
  color: white;
}

.btn-cancel {
  background: #f44336;
  color: white;
}

.input-area {
  display: flex;
  gap: 0.5rem;
  padding: 1rem;
  border-top: 1px solid #ddd;
}

.input-area input {
  flex: 1;
  padding: 0.75rem;
  border: 1px solid #ddd;
  border-radius: 4px;
}

.input-area button {
  padding: 0.75rem 1.5rem;
  background: #2196f3;
  color: white;
  border: none;
  border-radius: 4px;
  cursor: pointer;
}

.input-area button:disabled {
  background: #bbb;
  cursor: not-allowed;
}
</style>
```

---

## 使用示例

### App.vue

```vue
<script setup lang="ts">
import { ref } from 'vue'
import ChatPanel from '@/components/ChatPanel.vue'

const token = ref(localStorage.getItem('token'))
const showLogin = ref(!token.value)

async function login(username: string, password: string) {
  const response = await fetch('/api/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  })
  
  if (response.ok) {
    const data = await response.json()
    token.value = data.access_token
    localStorage.setItem('token', data.access_token)
    showLogin.value = false
  }
}
</script>

<template>
  <div class="app">
    <div v-if="showLogin" class="login">
      <!-- 登录表单 -->
    </div>
    <ChatPanel v-else />
  </div>
</template>
```

---

## API 端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/auth/login` | POST | 登录获取 JWT |
| `/api/auth/register` | POST | 注册用户 |
| `/api/sessions` | POST | 创建新会话 |
| `/api/chat/{thread_id}` | POST | 流式对话 (SSE) |
| `/api/resume/{thread_id}` | POST | 恢复中断 (SSE) |
| `/api/status/{thread_id}` | GET | 获取状态 |
| `/api/history/{thread_id}` | GET | 获取历史 |

---

## 注意事项

1. **Token 管理**：JWT token 需要在每次请求时通过 `Authorization: Bearer <token>` 传递

2. **SSE 连接**：使用 `fetch` + `ReadableStream` 而非 `EventSource`，因为需要 POST 请求

3. **中断处理**：收到 `interrupt` 事件后，需要用户确认才能继续

4. **错误处理**：监听 `error` 事件，显示错误信息

5. **重连机制**：目前未实现自动重连，可根据需要添加
