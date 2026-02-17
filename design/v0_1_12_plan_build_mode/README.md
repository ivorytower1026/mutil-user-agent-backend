# Plan/Build 双模式设计

## 背景

### 现状
- 每次执行 `execute` 命令、`write_file` 写入文件或 `edit_file` 编辑文件都需要人工审核（HITL）
- 用户需要手动点击"批准"或"拒绝"才能继续

### 期望
- 提供两种模式，用户可自由切换：
  - **plan（思考模式）**：不能执行命令/写入文件，自动拒绝并提示
  - **build（构建模式）**：自动批准执行命令/写入文件，无需人工审核

## 设计原则

1. **前端存储**：模式状态存储在前端 localStorage，默认 `build`
2. **请求携带**：每次 chat 请求携带当前模式
3. **后端处理**：根据模式自动处理 `execute`/`write_file`/`edit_file` 的 interrupt

## 模式行为

| 工具 | plan 模式 | build 模式 |
|------|----------|-----------|
| `execute` | 自动 reject，返回提示 | 自动 approve，继续执行 |
| `write_file` | 自动 reject，返回提示 | 自动 approve，继续执行 |
| `edit_file` | 自动 reject，返回提示 | 自动 approve，继续执行 |
| `ask_user` | 正常 interrupt，等待用户回答 | 正常 interrupt，等待用户回答 |

## 流程图

```
前端发送请求
POST /api/chat/{thread_id}
{
  "message": "...",
  "mode": "build" | "plan"  // 默认 build
}
        │
        ▼
后端 stream_chat(message, files, mode)
        │
        ▼
┌───────────────────────────────────────┐
│           Agent 执行循环               │
│                                       │
│  async for data in astream(...):      │
│      │                                │
│      ▼                                │
│  检测是否是 interrupt?                 │
│      │                                │
│      ├── 否 → 正常返回 SSE 事件        │
│      │                                │
│      └── 是 → 提取工具名称             │
│              │                        │
│              ▼                        │
│         execute / write_file / edit_file?   │
│              │                        │
│              ├── 是 →                  │
│              │    ├── build: approve → 继续循环 │
│              │    └── plan: reject → 返回提示  │
│              │                        │
│              └── 否 (ask_user等) →     │
│                   正常返回 interrupt 事件│
└───────────────────────────────────────┘
```

## API 设计

### Chat 请求

```http
POST /api/chat/{thread_id}
Content-Type: application/json

{
  "message": "创建一个 hello.py 文件",
  "files": [],
  "mode": "build"
}
```

**参数说明**：
- `mode`: 可选，默认 `"build"`
  - `"plan"`: 思考模式，禁止执行命令、写入和编辑文件
  - `"build"`: 构建模式，自动批准执行命令、写入和编辑文件

### 模式切换提示（plan 模式下触发）

当 plan 模式下检测到 `execute`、`write_file` 或 `edit_file` 时，返回：

```http
event: error
data: {"message": "当前为思考模式，请切换到 build 模式执行操作"}

event: done
data: {}
```

## 核心实现

### 1. API 层修改

#### `api/models.py`

```python
from typing import Literal

class ChatRequest(BaseModel):
    message: str
    files: list[str] | None = None
    mode: Literal["plan", "build"] = "build"  # 新增
```

#### `api/server.py`

```python
@router.post("/chat/{thread_id}")
async def chat(..., request: ChatRequest, ...):
    async def event_generator():
        async for chunk in agent_manager.stream_chat(
            thread_id, request.message, request.files, request.mode
        ):
            yield chunk
```

### 2. 工具类修改

#### `src/agent_utils/formatter.py` - 添加工具名称提取方法

```python
class StreamDataFormatter:
    # ... 现有代码 ...
    
    def extract_interrupt_tool_name(self, data: Any) -> str | None:
        """从 stream data 中提取 interrupt 的工具名称，非 interrupt 返回 None"""
        if not isinstance(data, dict) or "__interrupt__" not in data:
            return None
        
        interrupt_list = data.get("__interrupt__", [])
        if not interrupt_list:
            return None
        
        interrupt = interrupt_list[0]
        if hasattr(interrupt, "value"):
            value = interrupt.value
        elif isinstance(interrupt, dict):
            value = interrupt.get("value", {})
        else:
            return None
        
        requests = value.get("action_requests", [])
        return requests[0].get("name") if requests else None
```

### 3. 核心逻辑修改

#### `src/agent_manager.py`

```python
from langgraph.types import Command

AUTO_APPROVE_TOOLS = {"execute", "write_file", "edit_file"}

class AgentManager:
    # ... 现有代码 ...
    
    async def stream_chat(
        self, 
        thread_id: str, 
        message: str, 
        files: list[str] | None = None,
        mode: str = "build"  # 新增
    ) -> AsyncIterator[str]:
        queue: asyncio.Queue[str | None] = asyncio.Queue()
        pending = {'count': 2}
        
        with SessionLocal() as db:
            thread = db.query(Thread).filter(Thread.thread_id == thread_id).first()
            need_title = thread and thread.title is None
        
        async def agent_task():
            try:
                handler, _ = init_langfuse()
                config = {"configurable": {"thread_id": thread_id}, "callbacks": [handler]}
                
                messages = []
                if files:
                    file_list = "\n".join(f"- {path}" for path in files)
                    messages.append(SystemMessage(content=f"当前对话中用户已上传的文件：\n{file_list}"))
                
                if mode == "plan":
                    messages.append(SystemMessage(
                        content="""# Plan Mode

当前为思考模式，你只能进行只读操作：
- 禁止执行命令、写入文件、编辑文件
- 只能观察、分析、规划
- 可以向用户提问澄清需求

请先制定计划，等用户切换到 build 模式后再执行操作。"""
                    ))
                
                messages.append(HumanMessage(content=message))
                current_input = {"messages": messages}
                
                while True:
                    auto_resume = False
                    
                    async for stream_mode, data in self.compiled_agent.astream(
                        current_input, config=config, stream_mode=["messages", "updates"]
                    ):
                        tool_name = self.stream_formatter.extract_interrupt_tool_name(data)
                        
                        if tool_name in AUTO_APPROVE_TOOLS:
                            if mode == "build":
                                auto_resume = True
                                break
                            else:
                                await self.compiled_agent.ainvoke(
                                    Command(resume={"decisions": [{"type": "reject"}]}), config
                                )
                                await queue.put(self.sse_formatter.make_error_event(
                                    "当前为思考模式，请切换到 build 模式执行操作"
                                ))
                                return
                        else:
                            formatted = self.stream_formatter.format_stream_data(stream_mode, data)
                            if formatted:
                                await queue.put(formatted)
                    
                    if auto_resume:
                        current_input = Command(resume={"decisions": [{"type": "approve"}]})
                    else:
                        break
                        
            except Exception as e:
                logger.exception("Error in agent_task")
                await queue.put(self.sse_formatter.make_error_event(str(e)))
            finally:
                pending['count'] -= 1
                if pending['count'] == 0:
                    await queue.put(None)
        
        # title_task 保持不变...
        async def title_task():
            # ... 现有代码不变 ...
            pass
        
        asyncio.create_task(title_task())
        asyncio.create_task(agent_task())

        while True:
            item = await queue.get()
            if item is None:
                break
            yield item
        
        yield self.sse_formatter.make_done_event()
```

## 文件修改清单

| 文件 | 修改内容 | 行数估计 |
|------|---------|---------|
| `api/models.py` | `ChatRequest` 添加 `mode` 字段 | +2 |
| `api/server.py` | 传递 `request.mode` 给 `stream_chat` | +1 |
| `src/agent_utils/formatter.py` | 添加 `extract_interrupt_tool_name` 方法 | +15 |
| `src/agent_manager.py` | `stream_chat` 添加 mode 参数和自动处理逻辑 | +20 |

**总计**：约 38 行新增/修改代码

## 测试用例

### 1. build 模式 - 自动批准

```python
def test_build_mode_auto_approve():
    """build 模式下自动批准 execute/write_file/edit_file"""
    # 创建会话
    thread_id = create_session(user_id)
    
    # 发送消息（build 模式）
    response = requests.post(
        f"{BASE_URL}/api/chat/{thread_id}",
        json={"message": "执行 ls 命令", "mode": "build"},
        stream=True
    )
    
    events = parse_sse_events(response)
    
    # 验证：不应该有 interrupt 事件
    assert not any(e["type"] == "interrupt" for e in events)
    # 验证：有 tool_end 事件表示命令执行完成
    assert any(e["type"] == "tool_end" for e in events)
```

### 2. plan 模式 - 自动拒绝

```python
def test_plan_mode_auto_reject():
    """plan 模式下自动拒绝 execute/write_file/edit_file"""
    thread_id = create_session(user_id)
    
    response = requests.post(
        f"{BASE_URL}/api/chat/{thread_id}",
        json={"message": "执行 ls 命令", "mode": "plan"},
        stream=True
    )
    
    events = parse_sse_events(response)
    
    # 验证：有 error 事件包含模式提示
    error_events = [e for e in events if e["type"] == "error"]
    assert len(error_events) > 0
    assert "思考模式" in error_events[0]["data"]["message"]
    assert "build 模式" in error_events[0]["data"]["message"]
```

### 3. ask_user - 两种模式都正常 interrupt

```python
def test_ask_user_interrupt_in_both_modes():
    """ask_user 工具在两种模式下都正常返回 interrupt"""
    for mode in ["plan", "build"]:
        thread_id = create_session(user_id)
        
        response = requests.post(
            f"{BASE_URL}/api/chat/{thread_id}",
            json={"message": "帮我选择一个方案", "mode": mode},
            stream=True
        )
        
        events = parse_sse_events(response)
        
        # 验证：ask_user 触发 interrupt
        interrupt_events = [e for e in events if e["type"] == "interrupt"]
        assert len(interrupt_events) > 0
        # interrupt_info 中应该有 questions 字段
        assert "questions" in interrupt_events[0]["data"]
```

### 4. 连续执行多个命令

```python
def test_build_mode_consecutive_commands():
    """build 模式下连续执行多个命令"""
    thread_id = create_session(user_id)
    
    response = requests.post(
        f"{BASE_URL}/api/chat/{thread_id}",
        json={
            "message": "先执行 pwd，再执行 ls，最后创建 test.txt 文件",
            "mode": "build"
        },
        stream=True
    )
    
    events = parse_sse_events(response)
    
    # 验证：所有命令都执行完成
    tool_end_count = len([e for e in events if e["type"] == "tool_end"])
    assert tool_end_count >= 3
```

## 前端集成

### localStorage 存储

```typescript
// 默认 build 模式
const DEFAULT_MODE = 'build';

// 获取模式
function getMode(): 'plan' | 'build' {
  return localStorage.getItem('agent_mode') as 'plan' | 'build' || DEFAULT_MODE;
}

// 设置模式
function setMode(mode: 'plan' | 'build') {
  localStorage.setItem('agent_mode', mode);
}
```

### 发送请求时携带模式

```typescript
async function sendMessage(threadId: string, message: string) {
  const mode = getMode();
  
  const response = await fetch(`/api/chat/${threadId}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, mode })
  });
  
  // 处理 SSE 响应...
}
```

### 模式切换 UI

```tsx
function ModeToggle() {
  const [mode, setMode] = useState(getMode());
  
  const handleModeChange = (newMode: 'plan' | 'build') => {
    setMode(newMode);
    setMode(newMode); // 保存到 localStorage
  };
  
  return (
    <div className="mode-toggle">
      <button 
        className={mode === 'plan' ? 'active' : ''}
        onClick={() => handleModeChange('plan')}
      >
        🧠 思考
      </button>
      <button 
        className={mode === 'build' ? 'active' : ''}
        onClick={() => handleModeChange('build')}
      >
        🔨 构建
      </button>
    </div>
  );
}
```

## 注意事项

1. **防止无限循环**：设置 `max_iterations = 50` 限制
2. **ask_user 正常处理**：不影响现有提问功能
3. **错误处理**：plan 模式 reject 后返回友好提示
4. **日志记录**：记录自动批准/拒绝的操作，便于调试

## 后续优化

1. **细粒度控制**：未来可扩展为按工具类型分别控制
2. **审计日志**：记录所有自动批准的操作
3. **模式历史**：记录用户模式切换行为
