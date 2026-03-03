# 子代理支持 - 实施计划

## 概述

本文档详细说明如何实施子代理支持功能，按照最小改动原则，分步骤进行修改。

---

## 前置准备

### 1. 确认当前环境

```bash
# 确认 DeepAgents 版本
uv pip list | grep deepagents

# 确认 LangGraph 版本
uv pip list | grep langgraph
```

### 2. 创建测试分支

```bash
git checkout -b feature/subagent-support
```

---

## 阶段 1：后端核心改动（P0）

### 步骤 1.1：修改 SSEFormatter

**文件**：`src/agent_utils/formatter.py`

**改动位置**：第 47-70 行

#### 1.1.1 扩展 make_content_event()

**当前代码（第 47-48 行）**：
```python
def make_content_event(self, content: str) -> str:
    return self.format(InternalEventType.CONTENT, {"content": content})
```

**修改为**：
```python
def make_content_event(
    self, 
    content: str, 
    namespace: list[str] | None = None,
    subagent_id: str | None = None
) -> str:
    data = {"content": content}
    if namespace:
        data["namespace"] = namespace
    if subagent_id:
        data["subagent_id"] = subagent_id
    return self.format(InternalEventType.CONTENT, data)
```

#### 1.1.2 扩展 make_tool_start_event()

**当前代码（第 50-54 行）**：
```python
def make_tool_start_event(self, tool: str, todos: list[dict] | None = None) -> str:
    data: dict = {"tool": tool, "status": "running"}
    if todos:
        data["todos"] = todos
    return self.format(InternalEventType.TOOL_START, data)
```

**修改为**：
```python
def make_tool_start_event(
    self, 
    tool: str, 
    todos: list[dict] | None = None,
    namespace: list[str] | None = None,
    subagent_id: str | None = None
) -> str:
    data: dict = {"tool": tool, "status": "running"}
    if todos:
        data["todos"] = todos
    if namespace:
        data["namespace"] = namespace
    if subagent_id:
        data["subagent_id"] = subagent_id
    return self.format(InternalEventType.TOOL_START, data)
```

#### 1.1.3 扩展 make_tool_end_event()

**当前代码（第 56-57 行）**：
```python
def make_tool_end_event(self, tool: str) -> str:
    return self.format(InternalEventType.TOOL_END, {"tool": tool, "status": "completed"})
```

**修改为**：
```python
def make_tool_end_event(
    self, 
    tool: str,
    namespace: list[str] | None = None,
    subagent_id: str | None = None
) -> str:
    data = {"tool": tool, "status": "completed"}
    if namespace:
        data["namespace"] = namespace
    if subagent_id:
        data["subagent_id"] = subagent_id
    return self.format(InternalEventType.TOOL_END, data)
```

#### 1.1.4 扩展 make_interrupt_event()

**当前代码（第 59-60 行）**：
```python
def make_interrupt_event(self, data: InterruptData) -> str:
    return self.format(InternalEventType.INTERRUPT, dict(data))
```

**修改为**：
```python
def make_interrupt_event(
    self, 
    data: InterruptData,
    namespace: list[str] | None = None,
    subagent_id: str | None = None
) -> str:
    event_data = dict(data)
    if namespace:
        event_data["namespace"] = namespace
    if subagent_id:
        event_data["subagent_id"] = subagent_id
    return self.format(InternalEventType.INTERRUPT, event_data)
```

---

### 步骤 1.2：修改 AgentStreamRunner

**文件**：`src/agent_utils/stream/runner.py`

#### 1.2.1 添加 namespace 解析辅助方法

**位置**：在 `__init__()` 方法后（约第 43 行）

**添加代码**：
```python
def _parse_namespace(self, subgraph_path: tuple) -> tuple[bool, str | None]:
    """
    解析 namespace，判断是否为子代理
    
    Args:
        subgraph_path: 从 astream 返回的 namespace 元组
        
    Returns:
        (is_subagent, subagent_id)
        - is_subagent: 是否为子代理
        - subagent_id: 子代理 ID（如果 is_subagent 为 True）
    """
    if not subgraph_path:
        return False, None
    
    # 检查是否有 "tools:" 前缀的 segment
    for segment in subgraph_path:
        if isinstance(segment, str) and segment.startswith("tools:"):
            # 提取 ID（例如 "tools:abc123" -> "abc123"）
            subagent_id = segment.split(":", 1)[1] if ":" in segment else segment
            return True, subagent_id
    
    return False, None
```

#### 1.2.2 修改 _stream_one_cycle()

**当前代码（第 112-124 行）**：
```python
async for subgraph_path, stream_mode, data in self.agent.astream(
    current_input,
    config=config,
    stream_mode=["messages", "updates"],
    subgraphs=True,
):
    if stream_mode == "messages":
        for chunk in self._handle_messages(data):
            yield chunk
    
    elif stream_mode == "updates":
        for chunk in self._handle_updates(data, mode):
            yield chunk
```

**修改为**：
```python
async for subgraph_path, stream_mode, data in self.agent.astream(
    current_input,
    config=config,
    stream_mode=["messages", "updates"],
    subgraphs=True,
):
    if stream_mode == "messages":
        for chunk in self._handle_messages(subgraph_path, data):
            yield chunk
    
    elif stream_mode == "updates":
        for chunk in self._handle_updates(subgraph_path, data, mode):
            yield chunk
```

**改动说明**：
- 在调用 `_handle_messages()` 和 `_handle_updates()` 时传递 `subgraph_path` 参数

#### 1.2.3 修改 _handle_messages()

**当前方法签名（第 126 行）**：
```python
def _handle_messages(self, data: Any) -> list[StreamChunk]:
```

**修改为**：
```python
def _handle_messages(self, subgraph_path: tuple, data: Any) -> list[StreamChunk]:
    """
    Handle messages stream - LLM token and tool_calls
    
    Args:
        subgraph_path: Namespace tuple from subgraphs=True
        data: (AIMessageChunk, metadata: dict)
    """
    chunks = []
    
    # 解析 namespace
    is_subagent, subagent_id = self._parse_namespace(subgraph_path)
    namespace = list(subgraph_path) if subgraph_path else None
    
    if isinstance(data, tuple) and len(data) == 2:
        msg, metadata = data
        
        # 只处理 AIMessageChunk，跳过 ToolMessage
        msg_type = type(msg).__name__
        if msg_type == 'ToolMessage':
            return chunks
        
        if hasattr(msg, 'tool_calls') and msg.tool_calls:
            for tc in msg.tool_calls:
                if isinstance(tc, dict):
                    name = tc.get('name', '')
                    args = tc.get('args', {})
                    if name:
                        self._state.last_tool_name = name
                        self._state.last_tool_args = args if isinstance(args, dict) else {}
                        # write_todos 不在这里发送，在 updates 模式中发送
                        if name != 'write_todos':
                            chunks.append(StreamChunk(
                                event=self.formatter.make_tool_start_event(
                                    name,
                                    namespace=namespace,
                                    subagent_id=subagent_id
                                )
                            ))
        
        if hasattr(msg, 'content') and msg.content:
            content = msg.content
            if isinstance(content, str) and content:
                # 过滤掉内部系统消息
                if not self._is_internal_message(content):
                    chunks.append(StreamChunk(
                        event=self.formatter.make_content_event(
                            content,
                            namespace=namespace,
                            subagent_id=subagent_id
                        )
                    ))
    
    return chunks
```

**改动说明**：
- 添加 `subgraph_path` 参数
- 在方法开始处解析 namespace
- 在所有 `make_*_event()` 调用中传递 namespace 参数

#### 1.2.4 修改 _handle_updates()

**当前方法签名（第 182 行）**：
```python
def _handle_updates(self, data: dict, mode: str) -> list[StreamChunk]:
```

**修改为**：
```python
def _handle_updates(self, subgraph_path: tuple, data: dict, mode: str) -> list[StreamChunk]:
    """
    Handle updates stream - tool events and interrupts
    
    Args:
        subgraph_path: Namespace tuple from subgraphs=True
        data: {"agent": ..., "tools": ..., "__interrupt__": ...}
        mode: "build" or "plan"
    """
    chunks = []
    
    if not isinstance(data, dict):
        return chunks
    
    # 解析 namespace
    is_subagent, subagent_id = self._parse_namespace(subgraph_path)
    namespace = list(subgraph_path) if subgraph_path else None
    
    # 处理 model 更新 - 获取完整的 tool_calls 信息（包含 write_todos 的 todos）
    if "model" in data:
        model_data = data["model"]
        if isinstance(model_data, dict) and "messages" in model_data:
            for msg in model_data.get("messages", []):
                if hasattr(msg, "tool_calls") and msg.tool_calls:
                    for tc in msg.tool_calls:
                        if isinstance(tc, dict):
                            name = tc.get("name", "")
                            if name == "write_todos":
                                args = tc.get("args", {})
                                todos = args.get("todos", []) if isinstance(args, dict) else []
                                self._state.last_tool_name = name
                                self._state.last_tool_args = args if isinstance(args, dict) else {}
                                chunks.append(StreamChunk(
                                    event=self.formatter.make_tool_start_event(
                                        name,
                                        todos,
                                        namespace=namespace,
                                        subagent_id=subagent_id
                                    )
                                ))
    
    if "tools" in data:
        tool_data = data["tools"]
        if isinstance(tool_data, dict):
            tool_name = tool_data.get("name", self._state.last_tool_name or "unknown")
        elif hasattr(tool_data, 'name'):
            tool_name = tool_data.name
        else:
            tool_name = self._state.last_tool_name or "unknown"
        chunks.append(StreamChunk(
            event=self.formatter.make_tool_end_event(
                tool_name,
                namespace=namespace,
                subagent_id=subagent_id
            )
        ))
    
    if "__interrupt__" in data:
        interrupt_chunk = self._handle_interrupt(subgraph_path, data, mode)
        if interrupt_chunk.event or interrupt_chunk.auto_resume or interrupt_chunk.auto_reject:
            chunks.append(interrupt_chunk)
    
    return chunks
```

**改动说明**：
- 添加 `subgraph_path` 参数
- 在方法开始处解析 namespace
- 在所有 `make_*_event()` 调用中传递 namespace 参数
- 在调用 `_handle_interrupt()` 时传递 `subgraph_path`

#### 1.2.5 修改 _handle_interrupt()

**当前方法签名（第 232 行）**：
```python
def _handle_interrupt(self, data: dict, mode: str) -> StreamChunk:
```

**修改为**：
```python
def _handle_interrupt(self, subgraph_path: tuple, data: dict, mode: str) -> StreamChunk:
    """Handle interrupt event"""
    interrupt_list = data.get("__interrupt__", [])
    if not interrupt_list:
        return StreamChunk()
    
    # 解析 namespace
    is_subagent, subagent_id = self._parse_namespace(subgraph_path)
    namespace = list(subgraph_path) if subgraph_path else None
    
    interrupt = interrupt_list[0]
    requests = interrupt.value.get("action_requests", [])
    if not requests:
        return StreamChunk()
    
    request = requests[0]
    tool_name = request.get("name", "")
    
    if tool_name in AUTO_APPROVE_TOOLS:
        if mode == "build":
            return StreamChunk(auto_resume=True)
        else:
            # plan 模式下自动拒绝，让 LLM 继续运行并友好提示用户
            return StreamChunk(auto_reject=True)
    
    return StreamChunk(
        event=self.formatter.make_interrupt_event(
            {
                "info": self._format_interrupt_info(request),
                "taskName": TASK_DISPLAY_NAMES.get(tool_name, tool_name) or tool_name,
                "data": sanitize_for_json(interrupt.value),
                "questions": self._parse_questions(request.get("args", {}).get("questions")),
            },
            namespace=namespace,
            subagent_id=subagent_id
        )
    )
```

**改动说明**：
- 添加 `subgraph_path` 参数
- 在方法开始处解析 namespace
- 在 `make_interrupt_event()` 调用中传递 namespace 参数

---

### 步骤 1.3：测试验证

#### 1.3.1 创建测试用例

**文件**：`tests/test_subagent_namespace.py`

```python
"""
测试子代理 namespace 传递
运行: uv run python -m tests.test_subagent_namespace
"""

import asyncio
from langchain_core.messages import HumanMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import MemorySaver
from deepagents import create_deep_agent
from deepagents.middleware.subagents import SubAgent
from src.config import flash_llm

@tool
def get_weather(city: str) -> str:
    """获取城市天气"""
    return f"{city}的天气: 晴朗, 25°C"

async def test_namespace():
    """测试子代理 namespace 识别"""
    
    # 创建子代理
    weather_subagent: SubAgent = {
        "name": "weather_agent",
        "description": "天气查询子代理",
        "system_prompt": "你是一个天气查询助手",
        "tools": [get_weather],
    }
    
    checkpointer = MemorySaver()
    
    agent = create_deep_agent(
        model=flash_llm,
        backend=None,
        checkpointer=checkpointer,
        tools=[],
        subagents=[weather_subagent],
    )
    
    config = {"configurable": {"thread_id": "test-namespace"}}
    
    print("\n>>> 测试子代理 namespace 传递")
    print("-" * 40)
    
    namespaces = []
    async for subgraph_path, stream_mode, data in agent.astream(
        {"messages": [HumanMessage(content="北京天气如何？")]},
        config=config,
        stream_mode=["messages", "updates"],
        subgraphs=True,
    ):
        namespaces.append(subgraph_path)
    
    # 分析结果
    main_namespaces = [ns for ns in namespaces if not ns]
    subagent_namespaces = [ns for ns in namespaces if ns and any(
        s.startswith("tools:") for s in ns
    )]
    
    print(f"Total chunks: {len(namespaces)}")
    print(f"Main agent chunks: {len(main_namespaces)}")
    print(f"Subagent chunks: {len(subagent_namespaces)}")
    
    if subagent_namespaces:
        sample = subagent_namespaces[0]
        print(f"\nSample subagent namespace: {sample}")
        
        # 提取 subagent_id
        for segment in sample:
            if isinstance(segment, str) and segment.startswith("tools:"):
                subagent_id = segment.split(":", 1)[1]
                print(f"Extracted subagent_id: {subagent_id}")
    
    assert len(subagent_namespaces) > 0, "应该有子代理事件"
    print("\n✅ 测试通过！")

if __name__ == "__main__":
    asyncio.run(test_namespace())
```

**运行测试**：
```bash
uv run python -m tests.test_subagent_namespace
```

#### 1.3.2 创建 SSE 格式测试

**文件**：`tests/test_subagent_sse_format.py`

```python
"""
测试子代理 SSE 事件格式
运行: uv run python -m tests.test_subagent_sse_format
"""

import asyncio
import json
from langchain_core.messages import HumanMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import MemorySaver
from deepagents import create_deep_agent
from deepagents.middleware.subagents import SubAgent
from src.config import flash_llm
from src.agent_utils.formatter import SSEFormatter
from src.agent_utils.stream.runner import AgentStreamRunner

@tool
def get_weather(city: str) -> str:
    """获取城市天气"""
    return f"{city}的天气: 晴朗"

async def test_sse_format():
    """测试子代理 SSE 事件格式"""
    
    # 创建子代理
    weather_subagent: SubAgent = {
        "name": "weather_agent",
        "description": "天气查询子代理",
        "system_prompt": "你是天气查询助手",
        "tools": [get_weather],
    }
    
    checkpointer = MemorySaver()
    
    agent = create_deep_agent(
        model=flash_llm,
        backend=None,
        checkpointer=checkpointer,
        tools=[],
        subagents=[weather_subagent],
    )
    
    formatter = SSEFormatter()
    runner = AgentStreamRunner(agent, formatter)
    
    config = {"configurable": {"thread_id": "test-sse-format"}}
    
    print("\n>>> 测试子代理 SSE 事件格式")
    print("-" * 40)
    
    events = []
    async for sse_event in runner.run(
        thread_id="test-sse-format",
        initial_input={"messages": [HumanMessage(content="北京天气如何？")]},
        mode="build",
    ):
        # 解析 SSE 事件
        if sse_event.startswith("event: "):
            lines = sse_event.strip().split("\n")
            event_name = lines[0].split(": ", 1)[1]
            data_line = lines[1]
            data = json.loads(data_line.split("data: ", 1)[1])
            events.append({"event": event_name, "data": data})
    
    # 分析结果
    print(f"Total events: {len(events)}")
    
    subagent_events = [e for e in events if e["data"].get("namespace")]
    main_events = [e for e in events if not e["data"].get("namespace")]
    
    print(f"Main agent events: {len(main_events)}")
    print(f"Subagent events: {len(subagent_events)}")
    
    # 显示子代理事件示例
    if subagent_events:
        print(f"\n示例子代理事件:")
        sample = subagent_events[0]
        print(json.dumps(sample, indent=2, ensure_ascii=False))
    
    # 验证格式
    assert len(subagent_events) > 0, "应该有子代理事件"
    
    # 验证子代理事件包含必要字段
    for event in subagent_events:
        assert "namespace" in event["data"], "子代理事件应包含 namespace"
        assert isinstance(event["data"]["namespace"], list), "namespace 应为列表"
        
        if "subagent_id" in event["data"]:
            assert isinstance(event["data"]["subagent_id"], str), "subagent_id 应为字符串"
    
    print("\n✅ 测试通过！")

if __name__ == "__main__":
    asyncio.run(test_sse_format())
```

**运行测试**：
```bash
uv run python -m tests.test_subagent_sse_format
```

---

## 阶段 2：前端对接（P1）

### 步骤 2.1：类型定义

**文件**：前端项目中创建或更新类型文件

```typescript
// types/sse.ts

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
}

export interface GroupedEvents {
  isSubagent: boolean;
  subagentId: string | null;
  events: SSEEvent[];
}
```

### 步骤 2.2：工具函数

**文件**：`utils/subagent.ts`

```typescript
/**
 * 判断是否为子代理事件
 */
export function isSubagentEvent(event: SSEEvent): boolean {
  return !!(event.namespace && event.namespace.length > 0);
}

/**
 * 获取子代理 ID
 */
export function getSubagentId(event: SSEEvent): string | null {
  return event.subagent_id || null;
}

/**
 * 获取子代理 namespace
 */
export function getSubagentNamespace(event: SSEEvent): string[] {
  return event.namespace || [];
}

/**
 * 按子代理分组事件
 */
export function groupBySubagent(events: SSEEvent[]): GroupedEvents[] {
  const groups: Map<string, GroupedEvents> = new Map();
  
  for (const event of events) {
    const isSubagent = isSubagentEvent(event);
    const subagentId = getSubagentId(event);
    const groupKey = isSubagent ? `subagent-${subagentId}` : 'main';
    
    if (!groups.has(groupKey)) {
      groups.set(groupKey, {
        isSubagent,
        subagentId,
        events: []
      });
    }
    
    groups.get(groupKey)!.events.push(event);
  }
  
  return Array.from(groups.values());
}
```

### 步骤 2.3：组件实现

**文件**：`components/SubagentMessage.tsx`

```typescript
import React, { useState } from 'react';
import { SSEEvent } from '@/types/sse';

interface SubagentMessageProps {
  id: string | null;
  events: SSEEvent[];
  collapsible?: boolean;
  defaultCollapsed?: boolean;
}

export const SubagentMessage: React.FC<SubagentMessageProps> = ({
  id,
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
            子代理 {id ? `#${id.slice(0, 8)}` : ''}
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

### 步骤 2.4：样式文件

**文件**：`styles/subagent.css`

```css
/* 子代理消息容器 */
.subagent-message {
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

/* 消息内容 */
.message-content {
  padding: 8px 0;
  line-height: 1.6;
}
```

---

## 阶段 3：历史记录支持（P2，可选）

### 步骤 3.1：修改 get_history()

**文件**：`src/agent_utils/session.py`

**位置**：第 100 行后

**添加代码**：
```python
# 在 formatted_msg 构建后添加

# 检测子代理调用
if role == "assistant" and hasattr(msg, "tool_calls") and msg.tool_calls:
    for tc in msg.tool_calls:
        tc_dict = tc if isinstance(tc, dict) else tc.__dict__
        if tc_dict.get("name") == "task":  # DeepAgents 的子代理调用工具
            formatted_msg["is_subagent_call"] = True
            formatted_msg["subagent_name"] = tc_dict.get("args", {}).get("name", "unknown")
            break
```

---

## 验收标准

### 后端验收

- [ ] 代码改动完成，无语法错误
- [ ] 测试用例通过
  - [ ] `test_subagent_namespace.py` 通过
  - [ ] `test_subagent_sse_format.py` 通过
- [ ] 手动测试验证
  - [ ] 主代理消息不包含 namespace 字段
  - [ ] 子代理消息包含 namespace 和 subagent_id 字段
  - [ ] 子代理工具调用包含 namespace 字段
  - [ ] 子代理中断事件包含 namespace 字段

### 前端验收

- [ ] 类型定义完整
- [ ] 工具函数实现正确
- [ ] 组件渲染正常
  - [ ] 主代理消息正常显示
  - [ ] 子代理消息可折叠/展开
  - [ ] 样式显示正确
- [ ] 手动测试
  - [ ] 能正确识别子代理
  - [ ] 折叠/展开功能正常
  - [ ] 无性能问题

---

## 回滚计划

如果出现问题，可以快速回滚：

```bash
# 回滚代码
git checkout src/agent_utils/formatter.py
git checkout src/agent_utils/stream/runner.py

# 或者回滚整个分支
git checkout main
git branch -D feature/subagent-support
```

---

## 注意事项

1. **向后兼容**：主代理事件格式不变，现有前端不受影响
2. **性能影响**：极小，只增加简单的字符串判断
3. **测试覆盖**：确保所有场景都有测试用例
4. **文档更新**：更新 API 文档和前端对接指南

---

## 时间预估

| 阶段 | 任务 | 预估时间 |
|------|------|---------|
| 1.1 | 修改 formatter.py | 30分钟 |
| 1.2 | 修改 runner.py | 1小时 |
| 1.3 | 创建测试用例 | 1小时 |
| 1.4 | 运行测试验证 | 30分钟 |
| 2.1 | 前端类型定义 | 15分钟 |
| 2.2 | 前端工具函数 | 15分钟 |
| 2.3 | 前端组件实现 | 1小时 |
| 2.4 | 前端样式 | 30分钟 |
| 2.5 | 前端测试 | 30分钟 |
| 3 | 历史记录支持（可选） | 30分钟 |

**总计**：3-4 小时（不含可选部分）
