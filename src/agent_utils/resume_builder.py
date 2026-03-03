import logging
from typing import Any

from langgraph.types import Command

from .types import InterruptAction, AUTO_APPROVE_TOOLS, TOOL_ASK_USER

logger = logging.getLogger(__name__)


class ResumeCommandBuilder:
    """
    Resume command builder
    
    Responsibilities:
    - Analyze current interrupt state
    - Build resume command based on user action
    - Provide error messages
    """
    
    @staticmethod
    def build(
        action: InterruptAction,
        snapshot: Any,
        answers: list[str] | None = None,
    ) -> Command | None:
        """
        Build resume command
        
        Args:
            action: User action (continue/cancel/answer)
            snapshot: Agent state snapshot
            answers: Answer list (only for ask_user)
            
        Returns:
            Command object, or None for invalid action
        """
        tool_name = _extract_interrupt_tool(snapshot)
        
        if tool_name in AUTO_APPROVE_TOOLS:
            return Command(resume={"decisions": [{"type": "approve"}]})
        
        if tool_name == TOOL_ASK_USER:
            return ResumeCommandBuilder._build_ask_user(action, answers, snapshot)
        
        return ResumeCommandBuilder._build_default(action)
    
    @staticmethod
    def _build_ask_user(
        action: InterruptAction,
        answers: list[str] | None,
        snapshot: Any,
    ) -> Command | None:
        """Build ask_user tool resume command"""
        if action == InterruptAction.CONTINUE:
            return None
        
        if action == InterruptAction.CANCEL:
            return Command(resume={"decisions": [{"type": "reject"}]})
        
        if not answers:
            return None
        
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
        """Build default resume command"""
        if action == InterruptAction.CANCEL:
            return Command(resume={"decisions": [{"type": "reject"}]})
        elif action == InterruptAction.CONTINUE:
            return Command(resume={"decisions": [{"type": "approve"}]})
        else:
            return None
    
    @staticmethod
    def get_error_message(
        action: InterruptAction,
        snapshot: Any,
        answers: list[str] | None,
    ) -> str:
        """Get error message"""
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
    """Extract interrupt tool name from snapshot"""
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
    """Extract tool args from snapshot"""
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
