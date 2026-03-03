# 前端实现指南 - 子代理支持

## 概述

后端已经完成子代理支持，现在需要前端实现：
1. 识别子代理事件
2. 实现可折叠的子代理UI
3. 支持历史消息回显

---

## 后端改动总结

### SSE 事件格式

#### 主代理事件（无变化）
```json
{
  "content": "Hello",
  "tool": "execute",
  "status": "running"
}
```

#### 子代理事件（新增字段）
```json
{
  "content": "Checking weather...",
  "tool": "get_weather",
  "status": "running",
  "namespace": ["tools:08478f5b-49db-3622-d864-8826a0431269"],
  "subagent_id": "08478f5b-49db-3622-d864-8826a0431269",
  "subagent_name": "weather_agent"
}
```

#### 历史消息格式

```json
{
  "role": "assistant",
  "content": "I'll check the weather",
  "is_subagent_call": true,
  "subagent_name": "weather_agent",
  "in_subagent": true
}
```

---

## 前端实现步骤

### 1. 类型定义

**文件**: `types/sse.ts` 或类似的类型文件

```typescript
export interface SSEEvent {
  // 消息事件
  content?: string;
  
  // 工具事件
  tool?: string;
  status?: 'running' | 'completed';
  todos?: Array<{content: string; status: string}>;
  
  // 中断事件
  info?: string;
  taskName?: string;
  data?: any;
  questions?: Array<{
    question: string;
    options: Array<{label: string; value: string}>;
  }>;
  
  // 子代理标识（新增）
  namespace?: string[];
  subagent_id?: string;
  subagent_name?: string;
}

export interface HistoryMessage {
  role: 'user' | 'assistant' | 'tool';
  content: string;
  toolCalls?: Array<{
    name: string;
    status: string;
    todos?: any[];
  }>;
  
  // 子代理标识（新增）
  is_subagent_call?: boolean;
  subagent_name?: string;
  in_subagent?: boolean;
}

export interface GroupedEvents {
  isSubagent: boolean;
  subagentId: string | null;
  subagentName: string | null;
  events: SSEEvent[];
}
```

### 2. 工具函数

**文件**: `utils/subagent.ts`

```typescript
/**
 * 判断是否为子代理事件
 */
export function isSubagentEvent(event: SSEEvent): boolean {
  return !!(event.namespace && event.namespace.length > 0);
}

/**
 * 提取子代理信息
 */
export function getSubagentInfo(event: SSEEvent) {
  if (!isSubagentEvent(event)) {
    return null;
  }
  
  return {
    id: event.subagent_id || null,
    name: event.subagent_name || 'Unknown Subagent',
    namespace: event.namespace || []
  };
}

/**
 * 按子代理分组事件
 */
export function groupBySubagent(events: SSEEvent[]): GroupedEvents[] {
  const groups: Map<string, GroupedEvents> = new Map();
  
  for (const event of events) {
    const isSubagent = isSubagentEvent(event);
    const subagentId = event.subagent_id || null;
    const subagentName = event.subagent_name || null;
    const groupKey = isSubagent ? `subagent-${subagentId}` : 'main';
    
    if (!groups.has(groupKey)) {
      groups.set(groupKey, {
        isSubagent,
        subagentId,
        subagentName,
        events: []
      });
    }
    
    groups.get(groupKey)!.events.push(event);
  }
  
  return Array.from(groups.values());
}

/**
 * 判断历史消息是否为子代理
 */
export function isSubagentHistoryMessage(message: HistoryMessage): boolean {
  return !!(message.is_subagent_call || message.in_subagent);
}
```

### 3. React 组件实现

**文件**: `components/SubagentMessage.tsx`

```tsx
import React, { useState } from 'react';
import { SSEEvent } from '@/types/sse';

interface SubagentMessageProps {
  id: string | null;
  name: string | null;
  events: SSEEvent[];
  collapsible?: boolean;
  defaultCollapsed?: boolean;
}

export const SubagentMessage: React.FC<SubagentMessageProps> = ({
  id,
  name,
  events,
  collapsible = true,
  defaultCollapsed = true
}) => {
  const [collapsed, setCollapsed] = useState(defaultCollapsed);
  
  return (
    <div className="subagent-message">
      <div 
        className="subagent-header"
        onClick={() => collapsible && setCollapsed(!collapsed)}
      >
        <div className="header-left">
          <span className="subagent-icon">🤖</span>
          <span className="subagent-title">
            {name || 'Subagent'}
            {id && <span className="subagent-id">#{id.slice(0, 8)}</span>}
          </span>
          <span className="event-count">
            ({events.length} 个事件)
          </span>
        </div>
        {collapsible && (
          <span className="collapse-icon">
            {collapsed ? '▶' : '▼'}
          </span>
        )}
      </div>
      
      {!collapsed && (
        <div className="subagent-content">
          {events.map((event, index) => (
            <EventRenderer key={index} event={event} />
          ))}
        </div>
      )}
    </div>
  );
};

// 事件渲染器
const EventRenderer: React.FC<{ event: SSEEvent }> = ({ event }) => {
  if (event.content) {
    return <div className="message-content">{event.content}</div>;
  }
  
  if (event.tool && event.status === 'running') {
    return (
      <div className="tool-start">
        <span className="icon">⏳</span>
        <span>正在执行: {event.tool}</span>
      </div>
    );
  }
  
  if (event.tool && event.status === 'completed') {
    return (
      <div className="tool-end">
        <span className="icon">✅</span>
        <span>完成: {event.tool}</span>
      </div>
    );
  }
  
  if (event.info) {
    return (
      <div className="interrupt">
        <span className="icon">⏸️</span>
        <span>{event.info}</span>
      </div>
    );
  }
  
  return null;
};
```

**文件**: `components/MessageList.tsx`

```tsx
import React from 'react';
import { SSEEvent } from '@/types/sse';
import { groupBySubagent } from '@/utils/subagent';
import { SubagentMessage } from './SubagentMessage';

interface MessageListProps {
  events: SSEEvent[];
}

export const MessageList: React.FC<MessageListProps> = ({ events }) => {
  const grouped = groupBySubagent(events);
  
  return (
    <div className="message-list">
      {grouped.map((group, index) => (
        group.isSubagent ? (
          <SubagentMessage
            key={group.subagentId || index}
            id={group.subagentId}
            name={group.subagentName}
            events={group.events}
            collapsible={true}
            defaultCollapsed={false}
          />
        ) : (
          <MainMessage key={index} events={group.events} />
        )
      ))}
    </div>
  );
};

// 主代理消息组件
const MainMessage: React.FC<{ events: SSEEvent[] }> = ({ events }) => {
  return (
    <div className="main-message">
      {events.map((event, index) => (
        <EventRenderer key={index} event={event} />
      ))}
    </div>
  );
};
```

### 4. 历史消息支持

**文件**: `components/HistoryMessageList.tsx`

```tsx
import React from 'react';
import { HistoryMessage } from '@/types/sse';
import { isSubagentHistoryMessage } from '@/utils/subagent';

interface HistoryMessageListProps {
  messages: HistoryMessage[];
}

export const HistoryMessageList: React.FC<HistoryMessageListProps> = ({ messages }) => {
  return (
    <div className="history-message-list">
      {messages.map((message, index) => (
        isSubagentHistoryMessage(message) ? (
          <HistorySubagentMessage 
            key={index}
            message={message}
          />
        ) : (
          <HistoryMainMessage 
            key={index}
            message={message}
          />
        )
      ))}
    </div>
  );
};

const HistorySubagentMessage: React.FC<{ message: HistoryMessage }> = ({ message }) => {
  const [collapsed, setCollapsed] = useState(true);
  
  return (
    <div className="history-subagent-message">
      <div 
        className="subagent-header"
        onClick={() => setCollapsed(!collapsed)}
      >
        <span className="icon">🤖</span>
        <span>{message.subagent_name || 'Subagent'}</span>
        <span className="collapse-icon">{collapsed ? '▶' : '▼'}</span>
      </div>
      
      {!collapsed && (
        <div className="subagent-content">
          {message.content && <div>{message.content}</div>}
          {message.toolCalls && message.toolCalls.map((tc, i) => (
            <div key={i} className="tool-call">
              {tc.name}: {tc.status}
            </div>
          ))}
        </div>
      )}
    </div>
  );
};
```

### 5. 样式

**文件**: `styles/subagent.css`

```css
/* 子代理消息容器 */
.subagent-message,
.history-subagent-message {
  margin: 12px 0;
  margin-left: 24px;
  border-left: 3px solid #3b82f6;
  background: #f8fafc;
  border-radius: 8px;
  overflow: hidden;
}

/* 子代理头部 */
.subagent-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  cursor: pointer;
  background: #eff6ff;
  border-bottom: 1px solid #dbeafe;
  transition: background 0.2s;
}

.subagent-header:hover {
  background: #dbeafe;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 8px;
}

.subagent-icon {
  font-size: 18px;
}

.subagent-title {
  font-weight: 600;
  color: #1e40af;
}

.subagent-id {
  font-size: 0.875rem;
  color: #64748b;
  margin-left: 4px;
}

.event-count {
  font-size: 0.875rem;
  color: #64748b;
}

.collapse-icon {
  font-size: 12px;
  color: #64748b;
}

/* 子代理内容 */
.subagent-content {
  padding: 12px 16px;
  background: #ffffff;
}

/* 主代理消息 */
.main-message {
  margin: 12px 0;
}

/* 消息内容 */
.message-content {
  padding: 8px 0;
  line-height: 1.6;
}

/* 工具执行 */
.tool-start,
.tool-end {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  border-radius: 6px;
  font-size: 0.875rem;
  margin: 8px 0;
}

.tool-start {
  background: #fef3c7;
  color: #92400e;
}

.tool-end {
  background: #d1fae5;
  color: #065f46;
}

/* 中断 */
.interrupt {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 16px;
  background: #fee2e2;
  border-left: 4px solid #ef4444;
  border-radius: 6px;
  color: #991b1b;
}

/* 历史消息列表 */
.history-message-list {
  max-height: 600px;
  overflow-y: auto;
}
```

---

## 实施步骤

### 第1步：类型定义（15分钟）
- 更新 `types/sse.ts`
- 添加子代理相关字段

### 第2步：工具函数（15分钟）
- 创建 `utils/subagent.ts`
- 实现识别和分组函数

### 第3步：组件实现（1小时）
- 创建 `SubagentMessage` 组件
- 更新 `MessageList` 组件
- 创建 `HistoryMessageList` 组件

### 第4步：样式（30分钟）
- 添加 `styles/subagent.css`
- 调整布局和颜色

### 第5步：测试（30分钟）
- 测试流式输出的子代理识别
- 测试历史消息的子代理回显
- 测试折叠/展开功能

---

## 验收标准

### 功能验收
- [ ] 能正确识别子代理事件
- [ ] 子代理消息可折叠/展开
- [ ] 历史消息正确显示子代理
- [ ] 主代理消息不受影响

### UI 验收
- [ ] 子代理有明显视觉区分
- [ ] 折叠图标清晰可见
- [ ] 样式美观一致

### 性能验收
- [ ] 事件分组性能良好
- [ ] 大量事件时无卡顿

---

## 注意事项

1. **向后兼容**: 主代理事件格式不变，现有功能不受影响
2. **性能**: 使用 Map 进行分组，性能良好
3. **可访问性**: 添加适当的 ARIA 标签
4. **响应式**: 适配移动端显示

---

## 示例用法

```tsx
import { MessageList } from '@/components/MessageList';

function ChatPage() {
  const [events, setEvents] = useState<SSEEvent[]>([]);
  
  // 处理 SSE 事件
  const handleSSEEvent = (event: SSEEvent) => {
    setEvents(prev => [...prev, event]);
  };
  
  return (
    <div className="chat-page">
      <MessageList events={events} />
    </div>
  );
}
```

```tsx
import { HistoryMessageList } from '@/components/HistoryMessageList';

function HistoryPage() {
  const [messages, setMessages] = useState<HistoryMessage[]>([]);
  
  // 加载历史消息
  useEffect(() => {
    fetch('/api/history')
      .then(res => res.json())
      .then(data => setMessages(data.messages));
  }, []);
  
  return (
    <div className="history-page">
      <HistoryMessageList messages={messages} />
    </div>
  );
}
```

---

## 后端测试

运行测试验证后端功能：

```bash
# 测试 SSE 事件格式
uv run python -m tests.test_subagent_integration

# 测试 task 工具识别
uv run python -m tests.test_task_tool_simple
```

---

## 相关文档

- 设计文档: `design/v0_2_6_subagent_support/README.md`
- 识别方案: `design/v0_2_6_subagent_support/subagent-identification-update.md`
- 测试结果: `design/v0_2_6_subagent_support/test-results.md`
