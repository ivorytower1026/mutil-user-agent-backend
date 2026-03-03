# 子代理识别方案 - 最终版（已验证）

## 测试验证结果 ✅

### 测试时间
2026-03-03 21:34

### 测试发现

#### 1. 普通工具调用
```
namespace: ()
tool_name: simple_calc
tool_args: {'expr': '5+3'}
```

#### 2. 主代理调用 task 工具（启动子代理）
```
namespace: ()
tool_name: task
tool_args: {
    'description': '查询北京当前的天气情况...',
    'subagent_type': 'weather_agent'  ← 子代理名称
}
```

#### 3. 子代理内部的工具调用
```
namespace: ('tools:08478f5b-49db-3622-d864-8826a0431269',)
tool_name: get_weather
tool_args: {'city': '北京'}
```

### 关键结论

**Namespace 规律**：
- 主代理调用 task 工具：namespace = `()` （空元组）
- 子代理内部的所有事件：namespace = `('tools:ID',)` （有前缀）

**识别方法**：
- 检测 `tool_name == 'task'` → 子代理调用
- 从 `tool_args['subagent_type']` 获取子代理名称（不是 'name' 字段！）
- 后续所有 `namespace = ('tools:ID',)` 的事件都属于该子代理

---

## 正确的识别方案

### 方案1：通过工具名称识别（推荐）

子代理通过特殊的 **`task` 工具**调用，可以在两个地方检测：

#### 检测点1：messages 模式的 tool_calls

```python
# 在 _handle_messages() 中
if hasattr(msg, 'tool_calls') and msg.tool_calls:
    for tc in msg.tool_calls:
        if isinstance(tc, dict):
            tool_name = tc.get('name', '')
            
            # 检查是否为子代理
            if tool_name == 'task':
                # 这是子代理调用！
                subagent_name = tc.get('args', {}).get('name', 'unknown')
                # 标记后续的所有事件都属于这个子代理
```

#### 检测点2：updates 模式的 model 节点

```python
# 在 _handle_updates() 中
if "model" in data:
    model_data = data["model"]
    if isinstance(model_data, dict) and "messages" in model_data:
        for msg in model_data.get("messages", []):
            if hasattr(msg, "tool_calls") and msg.tool_calls:
                for tc in msg.tool_calls:
                    if isinstance(tc, dict):
                        tool_name = tc.get("name", "")
                        if tool_name == "task":
                            # 这是子代理！
                            subagent_name = tc.get("args", {}).get("name")
```

---

## 实现策略（已验证）

### 策略：检测 task 工具 + Namespace 跟踪

**核心思路**：
1. 在主代理的 messages/updates 中检测到 `task` 工具调用（namespace = `()`）
2. 从 `tool_args['subagent_type']` 提取子代理名称
3. 记录当前处于"子代理模式"
4. 后续所有 `namespace = ('tools:ID',)` 的事件都标记为该子代理
5. 直到检测到 task 工具结束（返回主代理 namespace）

### 代码实现

#### 修改 RunnerState

```python
@dataclass
class RunnerState:
    last_tool_name: str = ""
    last_tool_args: dict = field(default_factory=dict)
    
    # 新增：子代理跟踪
    in_subagent: bool = False
    current_subagent_id: str | None = None
    current_subagent_name: str | None = None
    subagent_stack: list = field(default_factory=list)  # 支持嵌套子代理
```

#### 在 _handle_messages() 中检测

```python
def _handle_messages(self, subgraph_path: tuple, data: Any) -> list[StreamChunk]:
    chunks = []
    
    # 解析 namespace
    namespace = list(subgraph_path) if subgraph_path else None
    is_main_agent = not bool(subgraph_path)  # 主代理的 namespace 为空
    
    if isinstance(data, tuple) and len(data) == 2:
        msg, metadata = data
        msg_type = type(msg).__name__
        
        # 跳过 ToolMessage
        if msg_type == 'ToolMessage':
            # 检查是否是 task 工具的结束
            if self._state.in_subagent and hasattr(msg, 'name') and msg.name == 'task':
                # 子代理结束，弹出栈
                if self._state.subagent_stack:
                    self._state.subagent_stack.pop()
                    if not self._state.subagent_stack:
                        self._state.in_subagent = False
                        self._state.current_subagent_id = None
                        self._state.current_subagent_name = None
            return chunks
        
        # 检测子代理调用（在主代理中）
        if hasattr(msg, 'tool_calls') and msg.tool_calls:
            for tc in msg.tool_calls:
                if isinstance(tc, dict):
                    name = tc.get('name', '')
                    args = tc.get('args', {})
                    
                    if name:
                        self._state.last_tool_name = name
                        self._state.last_tool_args = args if isinstance(args, dict) else {}
                        
                        # 检查是否为子代理调用（只在主代理中检测）
                        if name == 'task' and is_main_agent:
                            # 进入子代理模式
                            self._state.in_subagent = True
                            subagent_name = args.get('subagent_type', 'unknown') if isinstance(args, dict) else 'unknown'
                            self._state.current_subagent_name = subagent_name
                            
                            # 压入栈（支持嵌套）
                            self._state.subagent_stack.append({
                                'id': None,  # 稍后在子代理事件中获取
                                'name': subagent_name
                            })
                        
                        # 不发送 task 工具的 tool/start 事件
                        if name != 'task' and name != 'write_todos':
                            # 确定是否在子代理内部
                            subagent_id = None
                            subagent_name = None
                            
                            if not is_main_agent and self._state.in_subagent:
                                # 从 namespace 提取 ID
                                for segment in subgraph_path:
                                    if isinstance(segment, str) and segment.startswith("tools:"):
                                        subagent_id = segment.split(":", 1)[1]
                                        self._state.current_subagent_id = subagent_id
                                        if self._state.subagent_stack:
                                            self._state.subagent_stack[-1]['id'] = subagent_id
                                        break
                                
                                subagent_name = self._state.current_subagent_name
                            
                            chunks.append(StreamChunk(
                                event=self.formatter.make_tool_start_event(
                                    name,
                                    namespace=namespace,
                                    subagent_id=subagent_id,
                                    subagent_name=subagent_name
                                )
                            ))
        
        # 处理内容
        if hasattr(msg, 'content') and msg.content:
            content = msg.content
            if isinstance(content, str) and content:
                if not self._is_internal_message(content):
                    # 判断是否在子代理内部
                    subagent_id = None
                    subagent_name = None
                    
                    if not is_main_agent and self._state.in_subagent:
                        # 从 namespace 提取 ID
                        for segment in subgraph_path:
                            if isinstance(segment, str) and segment.startswith("tools:"):
                                subagent_id = segment.split(":", 1)[1]
                                self._state.current_subagent_id = subagent_id
                                if self._state.subagent_stack:
                                    self._state.subagent_stack[-1]['id'] = subagent_id
                                break
                        
                        subagent_name = self._state.current_subagent_name
                    
                    chunks.append(StreamChunk(
                        event=self.formatter.make_content_event(
                            content,
                            namespace=namespace,
                            subagent_id=subagent_id,
                            subagent_name=subagent_name
                        )
                    ))
    
    return chunks
```

#### 在 _handle_updates() 中检测

```python
def _handle_updates(self, subgraph_path: tuple, data: dict, mode: str) -> list[StreamChunk]:
    chunks = []
    
    if not isinstance(data, dict):
        return chunks
    
    # 解析 namespace
    namespace = list(subgraph_path) if subgraph_path else None
    is_main_agent = not bool(subgraph_path)  # 主代理的 namespace 为空
    
    # 确定子代理信息
    subagent_id = None
    subagent_name = None
    
    if not is_main_agent and self._state.in_subagent:
        # 从 namespace 提取 ID
        for segment in subgraph_path:
            if isinstance(segment, str) and segment.startswith("tools:"):
                subagent_id = segment.split(":", 1)[1]
                self._state.current_subagent_id = subagent_id
                if self._state.subagent_stack:
                    self._state.subagent_stack[-1]['id'] = subagent_id
                break
        
        subagent_name = self._state.current_subagent_name
    
    # 处理 model 更新
    if "model" in data:
        model_data = data["model"]
        if isinstance(model_data, dict) and "messages" in model_data:
            for msg in model_data.get("messages", []):
                if hasattr(msg, "tool_calls") and msg.tool_calls:
                    for tc in msg.tool_calls:
                        if isinstance(tc, dict):
                            name = tc.get("name", "")
                            
                            # 检查是否为子代理调用（只在主代理中检测）
                            if name == "task" and is_main_agent:
                                args = tc.get("args", {})
                                self._state.in_subagent = True
                                self._state.current_subagent_name = args.get("subagent_type", "unknown")
                                
                                # 压入栈
                                self._state.subagent_stack.append({
                                    'id': None,
                                    'name': self._state.current_subagent_name
                                })
                            
                            # 处理 write_todos
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
                                        subagent_id=subagent_id,
                                        subagent_name=subagent_name
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
        
        # 不发送 task 工具的 tool/end 事件
        if tool_name != 'task':
            chunks.append(StreamChunk(
                event=self.formatter.make_tool_end_event(
                    tool_name,
                    namespace=namespace,
                    subagent_id=subagent_id,
                    subagent_name=subagent_name
                )
            ))
    
    # 处理中断
    if "__interrupt__" in data:
        interrupt_chunk = self._handle_interrupt(subgraph_path, data, mode)
        if interrupt_chunk.event or interrupt_chunk.auto_resume or interrupt_chunk.auto_reject:
            chunks.append(interrupt_chunk)
    
    return chunks
```

---

## SSE 事件格式（更新）

### 新增字段

```typescript
interface SSEEvent {
  content?: string;
  tool?: string;
  status?: string;
  
  // 子代理标识
  namespace?: string[];        // namespace 路径
  subagent_id?: string;        // 子代理 ID（从 namespace 提取）
  subagent_name?: string;      // 子代理名称（从 task 工具的 args.subagent_type 获取）
}
```

### 实际示例（基于测试）

#### 主代理调用普通工具
```json
{
  "tool": "simple_calc",
  "status": "running"
  // 没有 namespace 和 subagent 字段
}
```

#### 主代理调用 task 工具（内部，不显示）
```json
// 不发送此事件
{
  "tool": "task",
  "status": "running",
  "namespace": []  // 主代理 namespace 为空
}
```

#### 子代理内部的消息
```json
{
  "content": "Checking Beijing weather...",
  "namespace": ["tools:08478f5b-49db-3622-d864-8826a0431269"],
  "subagent_id": "08478f5b-49db-3622-d864-8826a0431269",
  "subagent_name": "weather_agent"
}
```

#### 子代理内部的工具调用
```json
{
  "tool": "get_weather",
  "status": "running",
  "namespace": ["tools:08478f5b-49db-3622-d864-8826a0431269"],
  "subagent_id": "08478f5b-49db-3622-d864-8826a0431269",
  "subagent_name": "weather_agent"
}
```

### 前端识别逻辑

```typescript
// 判断是否为子代理事件
function isSubagentEvent(event: SSEEvent): boolean {
  return !!(event.namespace && event.namespace.length > 0);
}

// 提取子代理信息
function getSubagentInfo(event: SSEEvent) {
  if (!isSubagentEvent(event)) {
    return null;
  }
  
  return {
    id: event.subagent_id,
    name: event.subagent_name || 'Unknown Subagent',
    namespace: event.namespace
  };
}
```

---

## 关键差异（已验证）

### 错误的假设（旧方案）

```python
# ❌ 错误：认为 tools: 前缀可以区分子代理
is_subagent = any(s.startswith("tools:") for s in subgraph_path)
```

### 正确的实现（已验证）

```python
# ✅ 正确：通过 task 工具识别（在主代理 namespace = ()）
if tool_name == 'task' and not subgraph_path:  # 主代理
    # 这是子代理调用
    self._state.in_subagent = True
    self._state.current_subagent_name = args.get('subagent_type')  # 注意：不是 'name'！

# 后续的 tools: namespace 事件都属于子代理
if subgraph_path and self._state.in_subagent:
    # 从 namespace 提取 ID
    subagent_id = extract_id_from_namespace(subgraph_path)
    subagent_name = self._state.current_subagent_name
```

---

## 测试验证数据

### 测试1：普通工具调用
```
namespace: ()
tool_name: simple_calc
tool_args: {'expr': '5+3'}
```

### 测试2：子代理调用

**Chunk 2** - 主代理调用 task 工具：
```
namespace: ()
tool_name: task
tool_args: {
    'description': '查询北京当前的天气情况，包括温度、天气状况、风力等信息',
    'subagent_type': 'weather_agent'  ← 子代理名称
}
```

**Chunk 5** - 子代理内部调用工具：
```
namespace: ('tools:08478f5b-49db-3622-d864-8826a0431269',)
tool_name: get_weather
tool_args: {'city': '北京'}
```

---

## 总结（已验证）

### 核心识别逻辑

1. **检测 task 工具**：在主代理的 tool_calls 中查找 `name == 'task'`（namespace = `()`）
2. **提取子代理信息**：从 `args['subagent_type']` 获取子代理名称（不是 'name' 字段！）
3. **标记子代理模式**：设置 `in_subagent = True`
4. **标记后续事件**：所有 `namespace = ('tools:ID',)` 的事件都添加子代理标识
5. **提取子代理 ID**：从 namespace 的 `tools:` 前缀中提取
6. **检测子代理结束**：ToolMessage 且 name == 'task'

### 改动范围

与原方案相比，主要改动：
- 添加 `subagent_name` 字段（SSE 事件）
- 在 RunnerState 中添加子代理跟踪状态
- 在 `_handle_messages()` 中检测 task 工具（只在主代理 namespace = `()`）
- 在 `_handle_updates()` 中检测 task 工具（只在主代理 namespace = `()`）
- 过滤 task 工具的 tool/start 和 tool/end 事件
- **关键**：从 `args['subagent_type']` 而不是 `args['name']` 获取子代理名称

---

## 注意事项

### 1. 不显示 task 工具

`task` 是内部工具，不应该显示给用户：
- 不发送 `task` 的 `tool/start` 事件
- 不发送 `task` 的 `tool/end` 事件
- 只显示子代理的名称和内部活动

### 2. 支持嵌套子代理

使用栈结构支持子代理嵌套：

```python
self._state.subagent_stack.append({
    'id': subagent_id,
    'name': subagent_name
})
```

### 3. 工具调用结束检测

通过 ToolMessage 检测子代理结束：

```python
if msg_type == 'ToolMessage':
    if hasattr(msg, 'name') and msg.name == 'task':
        # 子代理结束
        self._state.subagent_stack.pop()
```

### 4. 字段名称注意

**关键**：子代理名称字段是 `subagent_type`，不是 `name`！

```python
# ❌ 错误
subagent_name = tool_args.get('name')

# ✅ 正确
subagent_name = tool_args.get('subagent_type')
```

### 5. Namespace 判断

**关键**：只在主代理（namespace = `()`）中检测 task 工具！

```python
# ✅ 正确
if tool_name == 'task' and not subgraph_path:  # 主代理
    # 检测到子代理调用
```

---

## 前端显示

前端可以根据 `subagent_name` 显示更友好的子代理名称：

```typescript
function SubagentMessage({ events, subagent_name }) {
  return (
    <div className="subagent">
      <div className="subagent-header">
        🤖 {subagent_name || 'Subagent'}
      </div>
      <div className="subagent-content">
        {events.map(...)}
      </div>
    </div>
  );
}
```

---

## 下一步

设计已经验证完毕，可以开始实施：

1. 修改 `src/agent_utils/formatter.py` - 添加 `subagent_name` 字段
2. 修改 `src/agent_utils/stream/runner.py` - 实现子代理跟踪逻辑
3. 创建测试用例验证
4. 前端对接
