import logging
from typing import Any, AsyncIterator

from langchain_core.runnables import RunnableConfig
from langgraph.types import Command

from .types import InterruptAction, TOOL_ASK_USER
from .formatter import SSEFormatter

logger = logging.getLogger(__name__)


class InterruptHandler:
    def __init__(self, compiled_agent: Any, sse_formatter: SSEFormatter):
        self.agent = compiled_agent
        self.sse = sse_formatter

    async def resume(
        self,
        thread_id: str,
        action: InterruptAction,
        answers: list[str] | None = None,
        langfuse_handler: Any = None,
    ) -> AsyncIterator[str]:
        if action not in [InterruptAction.CONTINUE, InterruptAction.CANCEL, InterruptAction.ANSWER]:
            raise ValueError("Action must be 'continue', 'cancel' or 'answer'")

        config: RunnableConfig = {
            "configurable": {"thread_id": thread_id},
            "callbacks": [langfuse_handler] if langfuse_handler else []
        }

        snapshot = await self.agent.aget_state(config)
        current_tool = self.extract_tool_name(snapshot)

        logger.debug("Resuming interrupt: thread_id=%s, action=%s, tool=%s", thread_id, action, current_tool)

        resume_command = self._build_resume_command(
            action=action,
            current_tool=current_tool,
            answers=answers,
            snapshot=snapshot,
        )
        
        if resume_command is None:
            async for error_event in self._yield_validation_errors(action, current_tool, answers):
                yield error_event
            return

        try:
            async for chunk in self.agent.astream(
                resume_command,
                config=config,
                stream_mode=["messages", "updates"],
                subgraphs=True,
            ):
                formatted = self._format_chunk(chunk)
                if formatted:
                    yield formatted
        except Exception as e:
            logger.exception("Error in stream_resume_interrupt")
            yield self.sse.make_error_event(f"{type(e).__name__}: {str(e)}")
            return
        finally:
            yield self.sse.make_done_event(action)

    def _build_resume_command(
        self,
        action: InterruptAction,
        current_tool: str | None,
        answers: list[str] | None,
        snapshot: Any,
    ) -> Command | None:
        if current_tool == TOOL_ASK_USER:
            return self._build_ask_user_command(action, answers, snapshot)
        else:
            return self._build_execute_command(action)

    def _build_ask_user_command(
        self,
        action: InterruptAction,
        answers: list[str] | None,
        snapshot: Any,
    ) -> Command | None:
        if action == InterruptAction.CONTINUE:
            return None
        
        if action == InterruptAction.CANCEL:
            return Command(resume={"decisions": [{"type": "reject"}]})
        
        if not answers:
            return None
        
        original_args = self.extract_args(snapshot, TOOL_ASK_USER)
        return Command(resume={
            "decisions": [{
                "type": "edit",
                "edited_action": {
                    "name": TOOL_ASK_USER,
                    "args": {**original_args, "answers": answers}
                }
            }]
        })

    def _build_execute_command(self, action: InterruptAction) -> Command | None:
        if action == InterruptAction.CANCEL:
            return Command(resume={"decisions": [{"type": "reject"}]})
        elif action == InterruptAction.ANSWER:
            return None
        else:
            return Command(resume={"decisions": [{"type": "approve"}]})

    async def _yield_validation_errors(
        self,
        action: InterruptAction,
        current_tool: str | None,
        answers: list[str] | None,
    ) -> AsyncIterator[str]:
        if current_tool == TOOL_ASK_USER:
            if action == InterruptAction.CONTINUE:
                yield self.sse.make_error_event("ask_user 工具只支持 'answer' 或 'cancel' 操作")
            elif action == InterruptAction.ANSWER and not answers:
                yield self.sse.make_error_event("answer 操作需要提供 answers 参数")
        else:
            if action == InterruptAction.ANSWER:
                yield self.sse.make_error_event("只有 ask_user 工具支持 'answer' 操作")
        yield self.sse.make_done_event("error")

    def _format_chunk(self, chunk: Any) -> str | None:
        if not isinstance(chunk, tuple) or len(chunk) != 3:
            return None
        
        mode = chunk[1]
        data = chunk[2]

        if mode == "messages":
            return self._format_messages_chunk(data)
        elif mode == "updates":
            return self._format_updates_chunk(data)
        return None

    def _format_messages_chunk(self, data: Any) -> str | None:
        from langchain_core.messages import AIMessage
        
        if isinstance(data, tuple) and len(data) == 2:
            token, _ = data
            if token and isinstance(token, AIMessage):
                content = getattr(token, "content", "")
                if content:
                    return self.sse.make_content_event(content)
        elif isinstance(data, str):
            return self.sse.make_content_event(data)
        return None

    def _format_updates_chunk(self, data: Any) -> str | None:
        from .formatter import sanitize_for_json
        
        if not isinstance(data, dict) or "__interrupt__" not in data:
            return None
        
        interrupt_list = data.get("__interrupt__", [])
        if not interrupt_list:
            return None
        
        interrupt = interrupt_list[0]
        requests = interrupt.value.get("action_requests", [])
        if not requests:
            return None
        
        request = requests[0]
        tool_name = request.get("name", "Unknown")
        
        from .formatter import StreamDataFormatter, TASK_DISPLAY_NAMES
        return self.sse.make_interrupt_event({
            "info": StreamDataFormatter.format_interrupt_info(request),
            "taskName": TASK_DISPLAY_NAMES.get(tool_name, tool_name),
            "data": sanitize_for_json(interrupt.value),
            "questions": request.get("args", {}).get("questions"),
        })

    @staticmethod
    def extract_tool_name(snapshot: Any) -> str | None:
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

    @staticmethod
    def extract_args(snapshot: Any, tool_name: str) -> dict:
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
