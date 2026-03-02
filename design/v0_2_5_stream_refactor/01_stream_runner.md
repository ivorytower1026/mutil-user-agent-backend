# 01. AgentStreamRunner - 流执行器

## 职责

封装 `agent.astream()` 调用，处理 auto_resume 循环。

## 设计原则

1. **使用 LangGraph 原生流模式** - `["messages", "updates", "tools"]`
2. **最小化自定义逻辑** - 只处理业务特有的 auto_resume
3. **委托格式化** - SSE 格式化交给 SSEFormatter

## 类设计

```python
from dataclasses import dataclass
from typing import AsyncIterator, Any
from langgraph.types import Command

from ..types import AUTO_APPROVE_TOOLS, TASK_DISPLAY_NAMES


@dataclass
class StreamChunk:
    """流处理结果"""
    event: str | None = None      # SSE 事件字符串
    auto_resume: bool = False     # 需要自动恢复
    error: str | None = None      # 错误消息


class AgentStreamRunner:
    """
    流执行器 - 封装 auto_resume 循环
    
    使用 LangGraph 原生流模式：
    - messages: LLM token 流
    - updates: 状态更新 + 中断
    - tools: 工具生命周期事件
    """
    
    def __init__(self, agent: Any, formatter: "SSEFormatter"):
        self.agent = agent
        self.formatter = formatter
    
    async def run(
        self,
        thread_id: str,
        initial_input: dict | Command,
        mode: str = "build",
        callbacks: list | None = None,
    ) -> AsyncIterator[str]:
        """
        执行流式处理
        
        Args:
            thread_id: 会话 ID
            initial_input: 初始输入（消息 dict 或恢复 Command）
            mode: 运行模式 ("build" | "plan")
            callbacks: Langfuse 等回调
            
        Yields:
            SSE 格式的事件字符串
        """
        config = {
            "configurable": {"thread_id": thread_id},
            "callbacks": callbacks or []
        }
        current_input = initial_input
        
        while True:
            auto_resume = False
            
            async for chunk in self._stream_one_cycle(current_input, config, mode):
                if chunk.auto_resume:
                    auto_resume = True
                    break
                elif chunk.error:
                    yield chunk.error
                    return
                elif chunk.event:
                    yield chunk.event
            
            if auto_resume:
                current_input = Command(resume={"decisions": [{"type": "approve"}]})
            else:
                break
    
    async def _stream_one_cycle(
        self,
        current_input: dict | Command,
        config: dict,
        mode: str,
    ) -> AsyncIterator[StreamChunk]:
        """处理单次流循环"""
        
        async for stream_mode, data in self.agent.astream(
            current_input,
            config=config,
            stream_mode=["messages", "updates", "tools"],
            subgraphs=True,
        ):
            if stream_mode == "messages":
                yield from self._handle_messages(data)
            
            elif stream_mode == "updates":
                chunk = self._handle_updates(data, mode)
                if chunk:
                    yield chunk
            
            elif stream_mode == "tools":
                event = self._handle_tools(data)
                if event:
                    yield StreamChunk(event=event)
    
    def _handle_messages(self, data: Any) -> AsyncIterator[StreamChunk]:
        """处理 messages 流 - LLM token"""
        if isinstance(data, tuple) and len(data) == 2:
            token, _ = data
            if hasattr(token, 'content') and token.content:
                content = str(token.content)
                if content:
                    yield StreamChunk(event=self.formatter.content(content))
        elif isinstance(data, str) and data:
            yield StreamChunk(event=self.formatter.content(data))
    
    def _handle_updates(self, data: dict, mode: str) -> StreamChunk | None:
        """处理 updates 流 - 状态更新和中断"""
        if not isinstance(data, dict):
            return None
        
        # 检查中断
        if "__interrupt__" in data:
            return self._handle_interrupt(data, mode)
        
        return None
    
    def _handle_interrupt(self, data: dict, mode: str) -> StreamChunk:
        """处理中断事件"""
        interrupt_list = data.get("__interrupt__", [])
        if not interrupt_list:
            return StreamChunk()
        
        interrupt = interrupt_list[0]
        requests = interrupt.value.get("action_requests", [])
        if not requests:
            return StreamChunk()
        
        request = requests[0]
        tool_name = request.get("name", "")
        
        # AUTO_APPROVE_TOOLS 在 build 模式下自动批准
        if tool_name in AUTO_APPROVE_TOOLS:
            if mode == "build":
                return StreamChunk(auto_resume=True)
            else:
                return StreamChunk(
                    error=self.formatter.error("当前为思考模式，请切换到 build 模式执行操作")
                )
        
        # 其他工具产生中断事件
        return StreamChunk(
            event=self.formatter.interrupt(
                info=self._format_interrupt_info(request),
                task_name=TASK_DISPLAY_NAMES.get(tool_name, tool_name),
                data=self._sanitize_data(interrupt.value),
                questions=request.get("args", {}).get("questions"),
            )
        )
    
    def _handle_tools(self, data: dict) -> str | None:
        """处理 tools 流 - 工具生命周期事件"""
        event_type = data.get("event")
        tool_name = data.get("name", "")
        
        if event_type == "on_tool_start":
            args = data.get("args", {})
            todos = args.get("todos") if tool_name == "write_todos" else None
            return self.formatter.tool_start(tool_name, todos)
        
        elif event_type == "on_tool_end":
            return self.formatter.tool_end(tool_name)
        
        return None
    
    def _format_interrupt_info(self, request: dict) -> str:
        """格式化中断信息"""
        import os
        
        tool_name = request.get("name", "Unknown")
        args = request.get("args", {})
        
        if tool_name == "execute":
            command = args.get("command", "")
            preview = command[:30] + "..." if len(command) > 30 else command
            return f"正在执行命令: {preview}"
        elif tool_name == "write_file":
            file_path = args.get("file_path", "")
            name = os.path.basename(file_path) if file_path else "文件"
            return f"正在写入文件: {name}"
        elif tool_name == "ask_user":
            questions = args.get("questions", [])
            return f"Agent 提出了 {len(questions)} 个问题"
        else:
            return "正在执行操作"
    
    def _sanitize_data(self, data: Any) -> dict:
        """清理数据用于 JSON 序列化"""
        if isinstance(data, dict):
            filtered = {k: v for k, v in data.items() if k not in ["content", "messages"]}
            return self._convert_for_json(filtered)
        return self._convert_for_json(data)
    
    def _convert_for_json(self, data: Any) -> Any:
        if isinstance(data, (str, int, float, bool, type(None))):
            return data
        elif isinstance(data, dict):
            return {k: self._convert_for_json(v) for k, v in data.items()}
        elif isinstance(data, (list, tuple)):
            return [self._convert_for_json(item) for item in data]
        else:
            return str(data)
```

## 关键设计决策

### 1. 使用 `tools` 流模式

LangGraph 自动提供标准化的工具事件：

```python
# on_tool_start
{
    "event": "on_tool_start",
    "name": "execute",
    "args": {"command": "ls -la"}
}

# on_tool_end
{
    "event": "on_tool_end", 
    "name": "execute",
    "output": "..."
}
```

无需手动解析 `updates` 中的工具状态。

### 2. StreamChunk 统一返回类型

所有处理方法返回 `StreamChunk`，包含：
- `event`: SSE 事件字符串
- `auto_resume`: 是否需要自动恢复
- `error`: 错误事件

### 3. 职责单一

- `_handle_messages`: 只处理 LLM token
- `_handle_updates`: 只处理中断（状态更新已不需要）
- `_handle_tools`: 只处理工具事件
