# DeepAgents 子代理支持 - 最小改动方案

## 问题背景

当前系统的 `/chat` 和 `/resume` 接口返回的流式数据中，DeepAgents 的子代理输出与主代理输出混在一起，前端无法区分。同时 `/history` 接口返回的历史数据也没有子代理信息，导致前端无法实现子代理消息的折叠展示。

### 核心问题

1. **流式输出**：子代理的 token、工具调用等信息没有标识，前端无法识别
2. **历史记录**：checkpoint 中没有 namespace 信息，无法区分主/子代理消息
3. **前端对接**：需要明确的数据格式，便于实现子代理折叠 UI

---

## 技术分析

### DeepAgents 子代理输出格式

根据 LangGraph 文档和代码分析，当使用 `subgraphs=True` 时：

**流式输出格式（三元组）**：
```python
async for subgraph_path, stream_mode, data in agent.astream(..., subgraphs=True):
    # subgraph_path: tuple - 标识 agent 层级
    # stream_mode: str - "messages" 或 "updates"
    # data: Any - 实际数据
```

**Namespace 格式**：
- `()` = 主 agent
- `("tools:abc123",)` = 子 agent（task 工具调用 ID 为 abc123）
- `("tools:abc123", "model_request:def456")` = 子 agent 内部节点

**当前代码现状**：
- ✅ 已在 `runner.py:112` 使用 `subgraphs=True`
- ✅ 已获取 `subgraph_path` 参数
- ❌ 但在 `_handle_messages()` 和 `_handle_updates()` 中**完全忽略**了它
- ❌ 所有事件都当作主 agent 事件发送，前端无法区分

---

## 解决方案

### 方案概述

**核心思路**：在流式输出中添加 namespace 标识，前端根据 namespace 区分主/子代理并实现折叠功能。

**改动范围**：
- ✅ 只修改应用层代码（`agent_utils/`）
- ✅ 不修改 DeepAgents 或 LangGraph 框架
- ✅ 向后兼容（现有前端不受影响）

**最小改动原则**：
- 只添加 namespace 相关字段
- 保持现有事件格式不变
- 主代理事件不添加额外字段

---

## 详细设计

### 1. SSE 事件格式扩展

#### 当前格式

```json
// 普通消息
event: messages/partial
data: {"content": "Hello"}

// 工具开始
event: tool/start
data: {"tool": "execute", "status": "running"}

// 工具结束
event: tool/end
data: {"tool": "execute", "status": "completed"}
```

#### 新格式（支持子代理）

```json
// 主代理消息（无变化，向后兼容）
event: messages/partial
data: {"content": "Hello"}

// 子代理消息（新增字段）
event: messages/partial
data: {
  "content": "I'm checking the weather...",
  "namespace": ["tools:abc123"],
  "subagent_id": "abc123"
}

// 子代理工具调用（新增字段）
event: tool/start
data: {
  "tool": "get_weather",
  "status": "running",
  "namespace": ["tools:abc123"],
  "subagent_id": "abc123"
}

// 子代理中断（新增字段）
event: interrupt
data: {
  "info": "正在执行命令: ls",
  "taskName": "执行命令",
  "data": {...},
  "namespace": ["tools:abc123"],
  "subagent_id": "abc123"
}
```

**字段说明**：
- `namespace`: 数组，namespace 路径（从 subgraph_path 转换）
- `subagent_id`: 字符串，子代理 ID（从 namespace 中提取，便于前端使用）

---

### 2. 代码实现

#### 2.1 修改 SSEFormatter

**文件**：`src/agent_utils/formatter.py`

**改动**：扩展 4 个 `make_*_event()` 方法，添加可选的 `namespace` 和 `subagent_id` 参数

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

**影响范围**：4 个方法，约 20 行代码

---

#### 2.2 修改 AgentStreamRunner

**文件**：`src/agent_utils/stream/runner.py`

**改动 2.2.1**：添加 namespace 解析辅助方法

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

**改动 2.2.2**：修改 `_stream_one_cycle()` 传递 subgraph_path

```python
# 当前（第112-124行）
async for subgraph_path, stream_mode, data in self.agent.astream(...):
    if stream_mode == "messages":
        for chunk in self._handle_messages(data):
            yield chunk
    elif stream_mode == "updates":
        for chunk in self._handle_updates(data, mode):
            yield chunk

# 修改为
async for subgraph_path, stream_mode, data in self.agent.astream(...):
    if stream_mode == "messages":
        for chunk in self._handle_messages(subgraph_path, data):
            yield chunk
    elif stream_mode == "updates":
        for chunk in self._handle_updates(subgraph_path, data, mode):
            yield chunk
```

**改动 2.2.3**：修改 `_handle_messages()` 接收并使用 subgraph_path

```python
# 当前（第126行）
def _handle_messages(self, data: Any) -> list[StreamChunk]:

# 修改为
def _handle_messages(self, subgraph_path: tuple, data: Any) -> list[StreamChunk]:
    """Handle messages stream - LLM token and tool_calls"""
    chunks = []
    
    # 解析 namespace
    is_subagent, subagent_id = self._parse_namespace(subgraph_path)
    namespace = list(subgraph_path) if subgraph_path else None
    
    if isinstance(data, tuple) and len(data) == 2:
        msg, metadata = data
        
        # 跳过 ToolMessage
        msg_type = type(msg).__name__
        if msg_type == 'ToolMessage':
            return chunks
        
        # 处理 tool_calls
        if hasattr(msg, 'tool_calls') and msg.tool_calls:
            for tc in msg.tool_calls:
                if isinstance(tc, dict):
                    name = tc.get('name', '')
                    args = tc.get('args', {})
                    if name:
                        self._state.last_tool_name = name
                        self._state.last_tool_args = args if isinstance(args, dict) else {}
                        if name != 'write_todos':
                            chunks.append(StreamChunk(
                                event=self.formatter.make_tool_start_event(
                                    name, 
                                    namespace=namespace,
                                    subagent_id=subagent_id
                                )
                            ))
        
        # 处理内容
        if hasattr(msg, 'content') and msg.content:
            content = msg.content
            if isinstance(content, str) and content:
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

**改动 2.2.4**：修改 `_handle_updates()` 接收并使用 subgraph_path

```python
# 当前（第182行）
def _handle_updates(self, data: dict, mode: str) -> list[StreamChunk]:

# 修改为
def _handle_updates(self, subgraph_path: tuple, data: dict, mode: str) -> list[StreamChunk]:
    """Handle updates stream - tool events and interrupts"""
    chunks = []
    
    if not isinstance(data, dict):
        return chunks
    
    # 解析 namespace
    is_subagent, subagent_id = self._parse_namespace(subgraph_path)
    namespace = list(subgraph_path) if subgraph_path else None
    
    # 处理 model 更新（write_todos）
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
    
    # 处理 tools 节点
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
    
    # 处理中断
    if "__interrupt__" in data:
        interrupt_chunk = self._handle_interrupt(subgraph_path, data, mode)
        if interrupt_chunk.event or interrupt_chunk.auto_resume or interrupt_chunk.auto_reject:
            chunks.append(interrupt_chunk)
    
    return chunks
```

**改动 2.2.5**：修改 `_handle_interrupt()` 接收并使用 subgraph_path

```python
# 当前（第232行）
def _handle_interrupt(self, data: dict, mode: str) -> StreamChunk:

# 修改为
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

**影响范围**：
- 添加 1 个辅助方法
- 修改 4 个现有方法签名和实现
- 约 80 行代码改动

---

### 3. 历史记录支持（可选）

**文件**：`src/agent_utils/session.py`

**策略**：通过 tool_calls 中的 "task" 工具推断子代理调用

```python
# 在 get_history() 中添加（第100行后）
if role == "assistant" and hasattr(msg, "tool_calls") and msg.tool_calls:
    for tc in msg.tool_calls:
        tc_dict = tc if isinstance(tc, dict) else tc.__dict__
        if tc_dict.get("name") == "task":  # DeepAgents 的子代理调用工具
            formatted_msg["is_subagent_call"] = True
            formatted_msg["subagent_name"] = tc_dict.get("args", {}).get("name", "unknown")
            break
```

**限制**：
- ⚠️ 只能识别子代理调用点，无法获取子代理内部消息
- ⚠️ 依赖 DeepAgents 内部实现（"task" 工具名）
- ⚠️ 推断可能不准确

**建议**：作为阶段2可选实现

---

## 前端对接指南

### 1. TypeScript 类型定义

```typescript
interface SSEEvent {
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
  questions?: Array<{question: string; options: Array<{label: string; value: string}>}>;
  
  // 子代理标识（新增）
  namespace?: string[];      // namespace 路径
  subagent_id?: string;      // 子代理 ID
}

interface GroupedEvents {
  isSubagent: boolean;
  subagentId: string | null;
  events: SSEEvent[];
}
```

### 2. 识别子代理事件

```typescript
function isSubagentEvent(event: SSEEvent): boolean {
  return !!(event.namespace && event.namespace.length > 0);
}

function getSubagentId(event: SSEEvent): string | null {
  return event.subagent_id || null;
}

function getSubagentNamespace(event: SSEEvent): string[] {
  return event.namespace || [];
}
```

### 3. 事件分组

```typescript
function groupBySubagent(events: SSEEvent[]): GroupedEvents[] {
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

### 4. UI 组件设计

#### 4.1 消息列表组件

```typescript
function MessageList({ events }: { events: SSEEvent[] }) {
  const grouped = groupBySubagent(events);
  
  return (
    <div className="message-list">
      {grouped.map((group, index) => (
        group.isSubagent ? (
          <SubagentMessage
            key={group.subagentId || index}
            id={group.subagentId}
            events={group.events}
            collapsible={true}
            defaultCollapsed={true}
          />
        ) : (
          <MainMessage key={index} events={group.events} />
        )
      ))}
    </div>
  );
}
```

#### 4.2 子代理消息组件（可折叠）

```typescript
import { useState } from 'react';

interface SubagentMessageProps {
  id: string | null;
  events: SSEEvent[];
  collapsible: boolean;
  defaultCollapsed: boolean;
}

function SubagentMessage({ 
  id, 
  events, 
  collapsible, 
  defaultCollapsed 
}: SubagentMessageProps) {
  const [collapsed, setCollapsed] = useState(defaultCollapsed);
  
  return (
    <div className="subagent-message">
      <div 
        className="subagent-header"
        onClick={() => collapsible && setCollapsed(!collapsed)}
      >
        <div className="header-left">
          <Icon name="bot" className="subagent-icon" />
          <span className="subagent-title">
            子代理 {id ? `#${id.slice(0, 8)}` : ''}
          </span>
          <span className="event-count">
            ({events.length} 个事件)
          </span>
        </div>
        {collapsible && (
          <Icon 
            name={collapsed ? "chevron-right" : "chevron-down"} 
            className="collapse-icon"
          />
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
}
```

#### 4.3 主代理消息组件

```typescript
function MainMessage({ events }: { events: SSEEvent[] }) {
  return (
    <div className="main-message">
      {events.map((event, index) => (
        <EventRenderer key={index} event={event} />
      ))}
    </div>
  );
}
```

#### 4.4 事件渲染器

```typescript
function EventRenderer({ event }: { event: SSEEvent }) {
  if (event.content) {
    return <div className="message-content">{event.content}</div>;
  }
  
  if (event.tool && event.status === 'running') {
    return (
      <div className="tool-start">
        <Icon name="loader" spin />
        <span>正在执行: {event.tool}</span>
        {event.todos && <TodoList todos={event.todos} />}
      </div>
    );
  }
  
  if (event.tool && event.status === 'completed') {
    return (
      <div className="tool-end">
        <Icon name="check-circle" />
        <span>完成: {event.tool}</span>
      </div>
    );
  }
  
  if (event.info) {
    return (
      <div className="interrupt">
        <Icon name="pause-circle" />
        <span>{event.info}</span>
      </div>
    );
  }
  
  return null;
}
```

### 5. 样式建议

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
  width: 20px;
  height: 20px;
  color: #3b82f6;
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
  width: 16px;
  height: 16px;
  color: #64748b;
  transition: transform 0.2s;
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
```

---

## 测试计划

### 测试 1：验证 namespace 传递

**创建测试文件**：`tests/test_subagent_namespace.py`

**测试内容**：
- 创建带子代理的 agent
- 运行 astream 并收集 namespace
- 验证能正确识别子代理 namespace

**预期结果**：
- 能获取到子代理的 namespace（例如 `("tools:abc123",)`）
- 能正确提取 subagent_id

### 测试 2：验证 SSE 事件格式

**创建测试文件**：`tests/test_subagent_sse.py`

**测试内容**：
- 通过 AgentManager 发送消息
- 收集 SSE 事件
- 验证子代理事件包含 `namespace` 和 `subagent_id` 字段
- 验证主代理事件不包含这些字段

**预期结果**：
- 子代理事件格式正确
- 主代理事件格式保持不变
- 向后兼容

### 测试 3：端到端测试

**测试内容**：
- 配置一个带子代理的 agent
- 通过前端发送消息
- 验证前端能正确识别和折叠子代理消息

---

## 实施检查清单

### 阶段 1：核心功能（P0）

- [ ] 修改 `src/agent_utils/formatter.py`
  - [ ] 扩展 `make_content_event()`
  - [ ] 扩展 `make_tool_start_event()`
  - [ ] 扩展 `make_tool_end_event()`
  - [ ] 扩展 `make_interrupt_event()`
  
- [ ] 修改 `src/agent_utils/stream/runner.py`
  - [ ] 添加 `_parse_namespace()` 辅助方法
  - [ ] 修改 `_stream_one_cycle()` 传递 subgraph_path
  - [ ] 修改 `_handle_messages()` 使用 namespace
  - [ ] 修改 `_handle_updates()` 使用 namespace
  - [ ] 修改 `_handle_interrupt()` 使用 namespace
  
- [ ] 测试验证
  - [ ] 运行 namespace 传递测试
  - [ ] 运行 SSE 事件格式测试
  - [ ] 手动测试子代理消息显示

### 阶段 2：前端对接（P1）

- [ ] 前端实现
  - [ ] 添加 SSEEvent 类型定义
  - [ ] 实现 `isSubagentEvent()` 判断函数
  - [ ] 实现 `groupBySubagent()` 分组函数
  - [ ] 实现 `SubagentMessage` 可折叠组件
  - [ ] 实现消息列表组件
  - [ ] 添加子代理样式
  
- [ ] 测试
  - [ ] 测试子代理识别
  - [ ] 测试折叠/展开功能
  - [ ] 测试样式显示

### 阶段 3：历史记录支持（P2，可选）

- [ ] 修改 `src/agent_utils/session.py`
  - [ ] 在 `get_history()` 中推断子代理
  
- [ ] 测试
  - [ ] 测试历史记录加载

---

## 风险评估

### 风险 1：向后兼容性

**风险等级**：低

**缓解措施**：
- ✅ 只在子代理事件中添加 `namespace` 和 `subagent_id`
- ✅ 主代理事件格式不变
- ✅ 现有前端不受影响（忽略新字段）

### 风险 2：性能影响

**风险等级**：极低

**评估**：
- ✅ 只增加简单的字符串判断和列表转换
- ✅ 不影响流式输出性能
- ✅ 前端分组操作复杂度 O(n)

### 风险 3：历史记录不完整

**风险等级**：中

**限制**：
- ⚠️ Checkpoint 没有 namespace 信息
- ⚠️ 只能通过推断识别子代理调用点
- ⚠️ 无法获取子代理内部消息详情

**缓解措施**：
- 阶段1只实现流式输出支持
- 阶段3可选实现历史记录推断
- 在文档中明确说明限制

### 风险 4：DeepAgents 版本兼容性

**风险等级**：低

**依赖**：
- 依赖 DeepAgents 使用 "tools:" 前缀的 namespace 格式
- 依赖 "task" 工具名称（用于历史记录推断）

**缓解措施**：
- ✅ 基于 LangGraph 官方文档的实现
- ✅ 使用标准的 subgraphs=True 接口
- 在文档中注明 DeepAgents 版本要求

---

## 预估工作量

| 任务 | 预估时间 | 优先级 |
|------|---------|--------|
| 修改 formatter.py | 30分钟 | P0 |
| 修改 runner.py | 1小时 | P0 |
| 创建测试用例 | 1小时 | P0 |
| 运行测试验证 | 30分钟 | P0 |
| 前端类型定义和工具函数 | 30分钟 | P1 |
| 前端组件实现 | 1.5小时 | P1 |
| 前端样式和测试 | 1小时 | P1 |
| 修改 session.py（可选） | 30分钟 | P2 |
| 文档编写 | 30分钟 | P2 |

**总计**：
- 核心功能（阶段1）：3小时
- 前端对接（阶段2）：3小时
- 历史记录（阶段3，可选）：30分钟

---

## 成功标准

### 功能标准

- ✅ 子代理的 token 流能正确标识 namespace
- ✅ 子代理的工具调用能正确标识 namespace
- ✅ 子代理的中断事件能正确标识 namespace
- ✅ 主代理事件格式保持不变
- ✅ 前端能正确识别子代理事件
- ✅ 前端能实现子代理消息的折叠/展开

### 质量标准

- ✅ 所有测试用例通过
- ✅ 代码符合项目规范
- ✅ 无性能回归
- ✅ 向后兼容

### 文档标准

- ✅ 代码注释清晰
- ✅ API 文档更新
- ✅ 前端对接指南完整

---

## 总结

### 核心改动

1. **传递 namespace**：从 `astream()` 到 `_handle_*()` 方法
2. **解析 namespace**：判断是否为子代理，提取 ID
3. **添加到事件**：在 SSE 事件中添加 `namespace` 和 `subagent_id` 字段
4. **前端识别**：根据 `namespace` 字段区分主/子代理

### 改动文件

- `src/agent_utils/formatter.py`（4个方法）
- `src/agent_utils/stream/runner.py`（5个方法）
- `src/agent_utils/session.py`（可选，1个方法）

### 代码量

- 后端改动：约 100 行
- 前端改动：约 200 行
- 测试代码：约 150 行

### 关键优势

- ✅ 不修改框架代码
- ✅ 向后兼容
- ✅ 改动量小
- ✅ 易于测试和验证
- ✅ 前端实现简单
- ✅ 清晰的升级路径

---

## 参考资料

- [LangGraph Streaming - Stream subgraph outputs](https://docs.langchain.com/oss/python/langgraph/streaming)
- [DeepAgents - Subagents](https://docs.langchain.com/oss/python/deepagents/subagents)
- [DeepAgents - Namespaces](https://docs.langchain.com/oss/python/deepagents/streaming/overview)
