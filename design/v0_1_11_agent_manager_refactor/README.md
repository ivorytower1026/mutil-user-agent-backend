# Agent Manager 重构方案

## 背景

`src/agent_manager.py` 当前 567 行，存在以下问题：

| 问题 | 影响 | 严重程度 |
|------|------|----------|
| 单文件职责过多 | 难以维护、测试、理解 | 高 |
| 代码重复 (interrupt 处理逻辑) | 修改需同步多处 | 中 |
| 30+ 处调试 print | 生产代码污染 | 低 |
| 嵌套过深 (4-5 层) | 可读性差 | 中 |
| 魔法字符串 | 易出错、难以重构 | 低 |
| 同步/异步混用 | 潜在性能问题 | 中 |

## 目标

1. **单一职责**：每个模块只做一件事
2. **消除重复**：提取公共逻辑
3. **降低耦合**：模块间通过清晰接口通信
4. **提升可测试性**：每个模块可独立测试
5. **代码整洁**：移除调试代码，使用 logging

## 目录结构

```
src/
├── agent_manager.py          # 主入口，协调各组件 (196 行)
└── agent_utils/
    ├── __init__.py           # 包导出 (18 行)
    ├── types.py              # 类型定义、常量、枚举 (80 行)
    ├── formatter.py          # SSE 格式化、流数据处理 (187 行)
    ├── interrupt.py          # 中断处理、HITL 逻辑 (210 行)
    └── session.py            # 会话 CRUD 操作 (101 行)
```

**总计**：从 567 行单文件 → 5 个模块共 792 行
- 主入口减少 65%（567 → 196 行）
- 增加的行数来自：类型注解、枚举定义、模块化开销

## 模块职责

### 1. `agent/types.py` - 类型与常量

```python
# 枚举
class SSEEvent(StrEnum):
    CONTENT = "messages/partial"
    TOOL_START = "tool/start"
    TOOL_END = "tool/end"
    INTERRUPT = "interrupt"
    ERROR = "error"
    END = "end"
    TITLE_UPDATED = "title_updated"

class InterruptAction(StrEnum):
    CONTINUE = "continue"
    CANCEL = "cancel"
    ANSWER = "answer"

# 常量
TOOL_EXECUTE = "execute"
TOOL_WRITE_FILE = "write_file"
TOOL_ASK_USER = "ask_user"

TASK_DISPLAY_NAMES = {
    TOOL_EXECUTE: "执行命令",
    TOOL_WRITE_FILE: "写入文件",
    TOOL_ASK_USER: "用户问答",
}

# TypedDict
class InterruptData(TypedDict):
    info: str
    taskName: str
    data: dict
    questions: list[dict] | None
```

### 2. `agent/formatter.py` - 格式化器

```python
class SSEFormatter:
    """SSE 事件格式化"""
    
    def format(self, event_type: SSEEvent, data: dict) -> str: ...
    def make_content_event(self, content: str) -> str: ...
    def make_tool_event(self, event: SSEEvent, tool: str, **extra) -> str: ...
    def make_interrupt_event(self, interrupt_data: InterruptData) -> str: ...

class StreamDataFormatter:
    """流数据解析与格式化"""
    
    def format_stream_data(self, mode: str, data: Any) -> str | None: ...
    def format_astream_chunk(self, chunk: tuple) -> str | None: ...
    def format_interrupt_info(self, request: dict) -> str: ...
```

### 3. `agent/interrupt.py` - 中断处理

```python
class InterruptHandler:
    """HITL 中断处理"""
    
    async def resume(
        self,
        thread_id: str,
        action: InterruptAction,
        answers: list[str] | None = None
    ) -> AsyncIterator[str]: ...
    
    def extract_tool_name(self, snapshot: Any) -> str | None: ...
    def extract_args(self, snapshot: Any, tool_name: str) -> dict: ...
    def build_resume_command(self, action: InterruptAction, ...) -> Command: ...
```

### 4. `agent/session.py` - 会话管理

```python
class SessionManager:
    """会话 CRUD 操作"""
    
    async def create(self, user_id: str) -> str: ...
    async def list(self, user_id: str, page: int, page_size: int) -> dict: ...
    async def get_status(self, thread_id: str) -> dict: ...
    async def get_history(self, thread_id: str) -> dict: ...
```

### 5. `agent_manager.py` - 主入口

```python
class AgentManager:
    """Agent 管理器主入口"""
    
    def __init__(self):
        self.pool = ...
        self.sse_formatter = SSEFormatter()
        self.stream_formatter = StreamDataFormatter(self.sse_formatter)
        self.interrupt_handler: InterruptHandler | None = None
        self.session_manager: SessionManager | None = None
    
    async def init(self): ...
    async def stream_chat(self, thread_id: str, message: str, files: list[str] | None) -> AsyncIterator[str]: ...
    async def stream_resume_interrupt(self, ...) -> AsyncIterator[str]: ...
    async def create_session(self, user_id: str) -> str: ...
    async def list_sessions(self, ...) -> dict: ...
    async def get_status(self, thread_id: str) -> dict: ...
    async def get_history(self, thread_id: str) -> dict: ...
```

## 代码优化点

### 1. 合并重复的 interrupt 格式化逻辑

**Before** (重复代码):
```python
# _format_stream_data 中
if "__interrupt__" in data:
    interrupt_list = data["__interrupt__"]
    if interrupt_list:
        interrupt = interrupt_list[0]
        requests = interrupt.value.get("action_requests", [])
        if requests:
            request = requests[0]
            return self._make_sse("interrupt", {...})

# _format_astream_chunk 中 - 几乎相同的代码
if isinstance(data, dict) and "__interrupt__" in data:
    interrupt_list = data["__interrupt__"]
    # ... 相同逻辑
```

**After** (提取公共方法):
```python
def _format_interrupt(self, data: dict) -> str | None:
    if "__interrupt__" not in data:
        return None
    interrupt_list = data.get("__interrupt__", [])
    if not interrupt_list:
        return None
    request = self._get_first_request(interrupt_list)
    if not request:
        return None
    return self.sse_formatter.make_interrupt_event({
        "info": self.format_interrupt_info(request),
        "taskName": TASK_DISPLAY_NAMES.get(request.get("name"), request.get("name")),
        "data": sanitize_for_json(interrupt_list[0].value),
        "questions": request.get("args", {}).get("questions"),
    })
```

### 2. 使用 early return 减少嵌套

**Before**:
```python
def _format_stream_data(self, stream_mode: str, data: Any) -> str | None:
    if stream_mode == "messages":
        if isinstance(data, tuple) and len(data) == 2:
            msg, metadata = data
            if hasattr(msg, "content") and msg.content and isinstance(msg, AIMessage):
                return self._make_sse("content", {"content": msg.content})
    elif stream_mode == "updates":
        if isinstance(data, dict):
            if "__interrupt__" in data:
                # ... 5 层嵌套
```

**After**:
```python
def format_stream_data(self, mode: str, data: Any) -> str | None:
    if mode == "messages":
        return self._format_message(data)
    if mode == "updates":
        return self._format_update(data)
    return None

def _format_message(self, data: Any) -> str | None:
    if not isinstance(data, tuple) or len(data) != 2:
        return None
    msg, _ = data
    if not isinstance(msg, AIMessage) or not msg.content:
        return None
    return self.sse_formatter.make_content_event(msg.content)
```

### 3. 移除调试代码

**Before**:
```python
print(f"[DEBUG] stream_resume_interrupt: thread_id={thread_id}, action={action}")
print(f"[DEBUG] resume_command={resume_command}")
print(f"[DEBUG] Resume chunk #{chunk_count}: type={type(chunk)}, value={chunk}")
```

**After** (使用 logging):
```python
import logging
logger = logging.getLogger(__name__)

logger.debug("Resuming interrupt: thread_id=%s, action=%s", thread_id, action)
# 生产环境设置 INFO 级别，不输出 DEBUG 日志
```

### 4. 统一异步数据库操作

**Before**:
```python
async def create_session(self, user_id: str) -> str:
    thread_id = f"{user_id}-{uuid.uuid4()}"
    get_thread_backend(thread_id)
    
    with SessionLocal() as db:  # 同步操作
        db.add(Thread(thread_id=thread_id, user_id=user_id))
        db.commit()
    
    return thread_id
```

**After** (保持一致性，或使用 async session):
```python
# 方案 A: 保持同步但明确标注
def _save_thread(self, thread_id: str, user_id: str) -> None:
    with SessionLocal() as db:
        db.add(Thread(thread_id=thread_id, user_id=user_id))
        db.commit()

async def create_session(self, user_id: str) -> str:
    thread_id = f"{user_id}-{uuid.uuid4()}"
    get_thread_backend(thread_id)
    self._save_thread(thread_id, user_id)
    return thread_id
```

## 兼容性保证

1. **API 接口不变**：`api/server.py` 导入路径不变
2. **公共方法签名不变**：`AgentManager` 的所有 public 方法保持原有签名
3. **SSE 事件格式不变**：前端无需修改

## 实施步骤

1. [x] 创建设计文档
2. [x] 创建 `src/agent_utils/` 目录结构
3. [x] 实现 `types.py`
4. [x] 实现 `formatter.py`
5. [x] 实现 `interrupt.py`
6. [x] 实现 `session.py`
7. [x] 重构 `agent_manager.py`
8. [ ] 运行测试验证
9. [ ] 更新 AGENTS.md（如有必要）

## 风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| 重构引入 bug | 高 | 每步后运行完整测试 |
| 接口不兼容 | 中 | 保持公共 API 不变 |
| 遗漏边缘情况 | 中 | 保留原文件备份，对比测试 |
