# 02. ResumeCommandBuilder - 恢复命令构建器

## 职责

根据用户操作和当前中断状态，构建 `Command` 对象用于恢复 agent 执行。

这是纯业务逻辑，与流处理无关。

## 类设计

```python
from typing import Any
from langgraph.types import Command

from .types import InterruptAction, AUTO_APPROVE_TOOLS, TOOL_ASK_USER


class ResumeCommandBuilder:
    """
    恢复命令构建器
    
    职责：
    - 分析当前中断状态
    - 根据用户操作构建恢复命令
    - 提供错误消息
    """
    
    @staticmethod
    def build(
        action: InterruptAction,
        snapshot: Any,
        answers: list[str] | None = None,
    ) -> Command | None:
        """
        构建恢复命令
        
        Args:
            action: 用户操作 (continue/cancel/answer)
            snapshot: agent 状态快照
            answers: 回答列表（仅用于 ask_user）
            
        Returns:
            Command 对象，或 None 表示无效操作
        """
        tool_name = _extract_interrupt_tool(snapshot)
        
        # AUTO_APPROVE_TOOLS: 直接批准（理论上不会到这里，但保持兼容）
        if tool_name in AUTO_APPROVE_TOOLS:
            return Command(resume={"decisions": [{"type": "approve"}]})
        
        # ask_user 工具: 特殊处理
        if tool_name == TOOL_ASK_USER:
            return ResumeCommandBuilder._build_ask_user(action, answers, snapshot)
        
        # 其他工具 (execute, write_file 等)
        return ResumeCommandBuilder._build_default(action)
    
    @staticmethod
    def _build_ask_user(
        action: InterruptAction,
        answers: list[str] | None,
        snapshot: Any,
    ) -> Command | None:
        """构建 ask_user 工具的恢复命令"""
        if action == InterruptAction.CONTINUE:
            return None  # ask_user 不支持 continue
        
        if action == InterruptAction.CANCEL:
            return Command(resume={"decisions": [{"type": "reject"}]})
        
        if not answers:
            return None  # answer 需要 answers
        
        original_args = _extract_tool_args(snapshot, TOOL_ASK_USER)
        return Command(resume={
            "decisions": [{
                "type": "edit",
                "edited_action": {
                    "name": TOOL_ASK_USER,
                    "args": {**original_args, "answers": answers}
                }
            }]
        })
    
    @staticmethod
    def _build_default(action: InterruptAction) -> Command | None:
        """构建默认恢复命令"""
        if action == InterruptAction.CANCEL:
            return Command(resume={"decisions": [{"type": "reject"}]})
        elif action == InterruptAction.CONTINUE:
            return Command(resume={"decisions": [{"type": "approve"}]})
        else:
            return None  # answer 只对 ask_user 有效
    
    @staticmethod
    def get_error_message(
        action: InterruptAction,
        snapshot: Any,
        answers: list[str] | None,
    ) -> str:
        """获取错误消息"""
        tool_name = _extract_interrupt_tool(snapshot)
        
        if tool_name == TOOL_ASK_USER:
            if action == InterruptAction.CONTINUE:
                return "ask_user 工具只支持 'answer' 或 'cancel' 操作"
            elif action == InterruptAction.ANSWER and not answers:
                return "answer 操作需要提供 answers 参数"
        
        if action == InterruptAction.ANSWER:
            return "只有 ask_user 工具支持 'answer' 操作"
        
        return "无法恢复执行"


def _extract_interrupt_tool(snapshot: Any) -> str | None:
    """从 snapshot 中提取中断工具名称"""
    if not snapshot.tasks:
        return None
    
    for task in snapshot.tasks:
        if not hasattr(task, "interrupts") or not task.interrupts:
            continue
        for interrupt in task.interrupts:
            if hasattr(interrupt, "value"):
                requests = interrupt.value.get("action_requests", [])
                if requests:
                    return requests[0].get("name")
    return None


def _extract_tool_args(snapshot: Any, tool_name: str) -> dict:
    """从 snapshot 中提取工具参数"""
    if not snapshot.tasks:
        return {}
    
    for task in snapshot.tasks:
        if not hasattr(task, "interrupts") or not task.interrupts:
            continue
        for interrupt in task.interrupts:
            if hasattr(interrupt, "value"):
                requests = interrupt.value.get("action_requests", [])
                for req in requests:
                    if req.get("name") == tool_name:
                        return req.get("args", {})
    return {}
```

## 决策矩阵

| 工具类型 | Action | 结果 |
|----------|--------|------|
| AUTO_APPROVE_TOOLS | * | `approve` (自动) |
| ask_user | continue | ❌ None |
| ask_user | cancel | `reject` |
| ask_user | answer + answers | `edit` + 注入 answers |
| ask_user | answer 无 answers | ❌ None |
| 其他 | continue | `approve` |
| 其他 | cancel | `reject` |
| 其他 | answer | ❌ None |
