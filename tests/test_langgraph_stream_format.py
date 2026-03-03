"""
测试 LangGraph 流格式
运行: uv run python -m tests.test_langgraph_stream_format
"""

import asyncio
import json
from datetime import datetime
from typing import Any
from pathlib import Path

from langchain.agents import create_agent
from langchain_core.messages import HumanMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import MemorySaver

from src.config import flash_llm

llm = flash_llm

def print_separator(title: str):
    print(f"\n{'=' * 60}")
    print(f" {title}")
    print("=" * 60)


def summarize_chunk(chunk: Any, chunk_num: int) -> dict:
    """总结单个chunk的结构信息"""
    summary = {"chunk_num": chunk_num, "type": type(chunk).__name__}

    if isinstance(chunk, tuple):
        summary["tuple_length"] = len(chunk)
        summary["items"] = []
        for i, item in enumerate(chunk):
            item_info = {"index": i, "type": type(item).__name__}
            if isinstance(item, str):
                item_info["value"] = item[:50] + "..." if len(item) > 50 else item
            elif hasattr(item, "__dict__"):
                item_info["attrs"] = list(item.__dict__.keys())[:10]
            summary["items"].append(item_info)
    elif isinstance(chunk, dict):
        summary["keys"] = list(chunk.keys())[:10]
        for k, v in list(chunk.items())[:3]:
            summary[f"sample_{k}"] = {
                "type": type(v).__name__,
                "preview": str(v)[:50] + "..." if len(str(v)) > 50 else str(v),
            }
    elif hasattr(chunk, "__dict__"):
        summary["attrs"] = list(chunk.__dict__.keys())[:10]
        if hasattr(chunk, "content"):
            content = str(chunk.content)
            summary["content_preview"] = (
                content[:50] + "..." if len(content) > 50 else content
            )

    return summary


@tool
def get_weather(city: str) -> str:
    """获取城市天气"""
    return f"{city}的天气: 晴朗, 25°C"


@tool
def execute_command(command: str) -> str:
    """执行命令 (会触发中断)"""
    return f"执行: {command}"


async def test_stream_modes():
    """测试不同的stream_mode组合，只输出总结"""
    print_separator("测试不同 stream_mode 组合")

    tools = [get_weather]
    checkpointer = MemorySaver()

    agent = create_agent(
        model=llm,
        tools=tools,
        checkpointer=checkpointer,
    )

    test_message = {"messages": [HumanMessage(content="北京天气如何？")]}

    modes_to_test = [
        ["messages"],
        ["updates"],
        ["values"],
        ["messages", "updates"],
        ["messages", "updates", "tools"],
        ["messages", "updates", "values", "debug"],
    ]

    results = {}

    for modes in modes_to_test:
        mode_key = str(modes)
        print(f"\n>>> stream_mode={modes}")

        config = {"configurable": {"thread_id": f"test-{hash(str(modes))}"}}
        chunks = []
        first_chunk_summary = None
        chunk_types = {}

        async for chunk in agent.astream(
            test_message, config=config, stream_mode=modes
        ):
            chunks.append(chunk)

            if first_chunk_summary is None:
                first_chunk_summary = summarize_chunk(chunk, 1)

            chunk_type = type(chunk).__name__
            if isinstance(chunk, tuple) and len(chunk) > 0:
                chunk_type = f"tuple({type(chunk[0]).__name__})"
            chunk_types[chunk_type] = chunk_types.get(chunk_type, 0) + 1

        results[mode_key] = {
            "total_chunks": len(chunks),
            "chunk_types": chunk_types,
            "first_chunk_structure": first_chunk_summary,
        }

        print(f"    Total chunks: {len(chunks)}")
        print(f"    Chunk types: {chunk_types}")
        print(f"    First chunk structure:")
        print(f"      {json.dumps(first_chunk_summary, ensure_ascii=False, indent=6)}")

    return results


async def test_tuple_vs_single():
    """测试单模式和多模式的返回格式差异"""
    print_separator("单模式 vs 多模式返回格式")

    tools = [get_weather]
    checkpointer = MemorySaver()

    agent = create_agent(model=llm, tools=tools, checkpointer=checkpointer)

    results = {}

    print("\n>>> 单模式 ['messages']")
    config1 = {"configurable": {"thread_id": "test-single-1"}}
    single_type = None
    count = 0
    async for chunk in agent.astream(
        {"messages": [HumanMessage(content="hi")]},
        config=config1,
        stream_mode=["messages"],
    ):
        count += 1
        if single_type is None:
            single_type = {
                "type": type(chunk).__name__,
                "is_tuple": isinstance(chunk, tuple),
            }
            if isinstance(chunk, tuple):
                single_type["length"] = len(chunk)
                single_type["item_types"] = [type(x).__name__ for x in chunk[:3]]
    print(f"    Chunks: {count}")
    print(f"    Format: {json.dumps(single_type, ensure_ascii=False, indent=4)}")
    results["single_mode"] = single_type

    print("\n>>> 多模式 ['messages', 'updates']")
    config2 = {"configurable": {"thread_id": "test-single-2"}}
    multi_type = None
    count = 0
    async for chunk in agent.astream(
        {"messages": [HumanMessage(content="hi")]},
        config=config2,
        stream_mode=["messages", "updates"],
    ):
        count += 1
        if multi_type is None:
            multi_type = {
                "type": type(chunk).__name__,
                "is_tuple": isinstance(chunk, tuple),
            }
            if isinstance(chunk, tuple):
                multi_type["length"] = len(chunk)
                multi_type["item_types"] = [type(x).__name__ for x in chunk[:3]]
                if len(chunk) > 0:
                    multi_type["first_item_value"] = str(chunk[0])[:50]
    print(f"    Chunks: {count}")
    print(f"    Format: {json.dumps(multi_type, ensure_ascii=False, indent=4)}")
    results["multi_mode"] = multi_type

    return results


async def test_interrupt_format():
    """测试中断(__interrupt__)的格式"""
    print_separator("中断(__interrupt__)格式")

    print("\n>>> 测试工具调用的 updates 格式 (不使用 interrupt_on)")
    print("-" * 40)

    tools = [execute_command]
    checkpointer = MemorySaver()

    agent = create_agent(
        model=llm,
        tools=tools,
        checkpointer=checkpointer,
    )

    config = {"configurable": {"thread_id": "test-interrupt-format"}}

    chunk_count = 0
    updates_chunks = []

    async for stream_mode, data in agent.astream(
        {"messages": [HumanMessage(content="执行命令 ls")]},
        config=config,
        stream_mode=["updates"],
    ):
        chunk_count += 1
        updates_chunks.append(
            {
                "chunk_num": chunk_count,
                "stream_mode": stream_mode,
                "data_type": type(data).__name__,
                "data_keys": list(data.keys()) if isinstance(data, dict) else None,
            }
        )

    print(f"    Total chunks: {chunk_count}")
    print(f"    Updates chunks structure:")
    for chunk in updates_chunks[:5]:  # 只显示前5个
        print(f"      {json.dumps(chunk, ensure_ascii=False)}")

    if len(updates_chunks) > 5:
        print(f"      ... ({len(updates_chunks) - 5} more)")

    return {"total_chunks": chunk_count, "updates_chunks": updates_chunks}


async def test_tools_stream():
    """测试tools流模式的格式"""
    print_separator("tools 流模式格式")

    tools = [get_weather]
    checkpointer = MemorySaver()

    agent = create_agent(model=llm, tools=tools, checkpointer=checkpointer)

    config = {"configurable": {"thread_id": "test-tools"}}

    print("\n>>> stream_mode=['tools']")
    tools_chunks = []
    async for chunk in agent.astream(
        {"messages": [HumanMessage(content="北京天气")]},
        config=config,
        stream_mode=["tools"],
    ):
        tools_chunks.append(chunk)

    print(f"    Total chunks: {len(tools_chunks)}")
    if tools_chunks:
        print(f"    First chunk type: {type(tools_chunks[0])}")
        print(f"    First chunk structure:")
        print(
            f"      {json.dumps(summarize_chunk(tools_chunks[0], 1), ensure_ascii=False, indent=6)}"
        )

    print("\n>>> stream_mode=['tools'] + subgraphs=True")
    config2 = {"configurable": {"thread_id": "test-tools-subgraphs"}}
    subgraph_chunks = []
    async for chunk in agent.astream(
        {"messages": [HumanMessage(content="北京天气")]},
        config=config2,
        stream_mode=["tools"],
        subgraphs=True,
    ):
        subgraph_chunks.append(chunk)

    print(f"    Total chunks: {len(subgraph_chunks)}")
    if subgraph_chunks:
        print(f"    First chunk type: {type(subgraph_chunks[0])}")
        print(f"    First chunk structure:")
        print(
            f"      {json.dumps(summarize_chunk(subgraph_chunks[0], 1), ensure_ascii=False, indent=6)}"
        )


async def test_subgraphs_format():
    """测试subgraphs=True时的格式"""
    print_separator("subgraphs=True 格式")

    tools = [get_weather]
    checkpointer = MemorySaver()

    agent = create_agent(model=llm, tools=tools, checkpointer=checkpointer)

    config = {"configurable": {"thread_id": "test-subgraphs"}}

    print("\n>>> stream_mode=['messages', 'updates'] + subgraphs=True")
    chunks = []
    chunk_structure = None

    async for chunk in agent.astream(
        {"messages": [HumanMessage(content="hi")]},
        config=config,
        stream_mode=["messages", "updates"],
        subgraphs=True,
    ):
        chunks.append(chunk)
        if chunk_structure is None:
            chunk_structure = summarize_chunk(chunk, 1)

    print(f"    Total chunks: {len(chunks)}")
    if chunk_structure:
        print(f"    First chunk structure:")
        print(f"      {json.dumps(chunk_structure, ensure_ascii=False, indent=6)}")


async def test_messages_detailed():
    """详细分析messages流中的token格式"""
    print_separator("messages 流 token 格式分析")

    tools = [get_weather]
    checkpointer = MemorySaver()

    agent = create_agent(model=llm, tools=tools, checkpointer=checkpointer)

    config = {"configurable": {"thread_id": "test-token"}}

    print("\n>>> 收集前10个chunks的结构")
    chunks_info = []
    count = 0

    async for chunk in agent.astream(
        {"messages": [HumanMessage(content="北京天气")]},
        config=config,
        stream_mode=["messages"],
    ):
        count += 1
        chunks_info.append(summarize_chunk(chunk, count))
        if count >= 10:
            break

    print(f"    Collected {len(chunks_info)} chunks")
    print("\n    Chunk structures:")
    for info in chunks_info:
        print(f"      [{info['chunk_num']}] {info['type']}")
        if "content_preview" in info:
            print(f"           content: {info['content_preview']}")

    return chunks_info


async def test_tool_calls_format():
    """测试工具调用的完整流程格式"""
    print_separator("工具调用完整流程")

    tools = [get_weather]
    checkpointer = MemorySaver()

    agent = create_agent(model=llm, tools=tools, checkpointer=checkpointer)

    config = {"configurable": {"thread_id": "test-tool-calls"}}

    print("\n>>> messages 模式 - 查找 tool_calls")
    print("-" * 40)

    tool_call_chunks = []
    async for stream_mode, data in agent.astream(
            {"messages": [HumanMessage(content="北京天气")]},
            config=config,
            stream_mode=["messages"],
    ):
        if isinstance(data, tuple) and len(data) == 2:
            msg, metadata = data
            if hasattr(msg, 'tool_calls') and msg.tool_calls:
                tool_call_chunks.append({
                    "msg_type": type(msg).__name__,
                    "tool_calls": [
                        {
                            "name": tc.get('name') if isinstance(tc, dict) else getattr(tc, 'name', None),
                            "args": str(tc.get('args', {}))[:100] if isinstance(tc, dict) else str(
                                getattr(tc, 'args', {}))[:100],
                        }
                        for tc in msg.tool_calls
                    ],
                    "content_preview": str(msg.content)[:50] if msg.content else None,
                })

    print(f"    Found {len(tool_call_chunks)} chunks with tool_calls")
    for i, chunk in enumerate(tool_call_chunks):
        print(f"\n    [Tool Call #{i + 1}]")
        print(f"      msg_type: {chunk['msg_type']}")
        print(f"      tool_calls: {json.dumps(chunk['tool_calls'], ensure_ascii=False, indent=6)}")
        print(f"      content: {chunk['content_preview']}")

    return tool_call_chunks


async def test_write_todos_format():
    """测试 write_todos 工具的特殊格式"""
    print_separator("write_todos 工具格式")

    # 模拟 write_todos 工具
    @tool
    def write_todos(todos: list[dict]) -> str:
        """写入待办事项"""
        return f"已写入 {len(todos)} 个待办事项"

    tools = [write_todos]
    checkpointer = MemorySaver()

    agent = create_agent(model=llm, tools=tools, checkpointer=checkpointer)

    config = {"configurable": {"thread_id": "test-write-todos"}}

    print("\n>>> messages 模式 - 检测 tool_calls 中的 todos")
    print("-" * 40)

    messages_results = []
    async for stream_mode, data in agent.astream(
            {"messages": [HumanMessage(content="制定个todolist，写个冒泡排序的python脚本")]},
            config=config,
            stream_mode=["messages"],
    ):
        if isinstance(data, tuple) and len(data) == 2:
            msg, metadata = data
            if hasattr(msg, 'tool_calls') and msg.tool_calls:
                for tc in msg.tool_calls:
                    if isinstance(tc, dict) and tc.get('name') == 'write_todos':
                        messages_results.append({
                            "name": tc.get('name'),
                            "todos": tc.get('args', {}).get('todos', [])[:2],  # 只显示前2个
                            "todos_count": len(tc.get('args', {}).get('todos', [])),
                        })

    print(f"    Found {len(messages_results)} write_todos in messages")
    for r in messages_results:
        print(f"      todos count: {r['todos_count']}")
        print(f"      sample: {json.dumps(r['todos'], ensure_ascii=False)}")

    print("\n>>> updates 模式 - 检测 write_todos 的完整结构")
    print("-" * 40)

    config2 = {"configurable": {"thread_id": "test-write-todos-2"}}
    updates_results = []

    async for stream_mode, data in agent.astream(
            {"messages": [HumanMessage(content="制定个todolist，写个冒泡排序的python脚本")]},
            config=config2,
            stream_mode=["updates"],
    ):
        if isinstance(data, dict):
            # 检查是否有 write_todos 键
            if "write_todos" in data:
                wd = data["write_todos"]
                updates_results.append({
                    "key": "write_todos",
                    "type": type(wd).__name__,
                    "has_input": "input" in wd if isinstance(wd, dict) else False,
                    "has_output": "output" in wd if isinstance(wd, dict) else False,
                    "keys": list(wd.keys()) if isinstance(wd, dict) else None,
                })
            # 检查 tools 键
            if "tools" in data:
                tools_data = data["tools"]
                updates_results.append({
                    "key": "tools",
                    "type": type(tools_data).__name__,
                    "has_name": hasattr(tools_data, 'name'),
                    "name": getattr(tools_data, 'name', None),
                })

    print(f"    Found {len(updates_results)} relevant updates")
    for r in updates_results:
        print(f"      {json.dumps(r, ensure_ascii=False, indent=6)}")

    return {
        "messages": messages_results,
        "updates": updates_results,
    }


async def test_error_handling():
    """测试错误处理格式 - agent 内部抛出异常时的流格式"""
    print_separator("错误处理格式")

    @tool
    def error_tool(msg: str) -> str:
        """一个会抛出异常的工具"""
        raise ValueError(f"工具内部错误: {msg}")

    tools = [error_tool]
    checkpointer = MemorySaver()

    agent = create_agent(model=llm, tools=tools, checkpointer=checkpointer)

    config = {"configurable": {"thread_id": "test-error"}}

    print("\n>>> 测试工具抛出异常时的流格式")
    print("-" * 40)

    results = {
        "messages_mode": [],
        "updates_mode": [],
        "exception_raised": None,
    }

    try:
        async for stream_mode, data in agent.astream(
            {"messages": [HumanMessage(content="用error_tool测试错误消息")]},
            config=config,
            stream_mode=["messages", "updates"],
        ):
            if stream_mode == "messages":
                if isinstance(data, tuple) and len(data) == 2:
                    msg, metadata = data
                    results["messages_mode"].append({
                        "msg_type": type(msg).__name__,
                        "has_error": hasattr(msg, 'is_error') and msg.is_error,
                        "content_preview": str(msg.content)[:100] if msg.content else None,
                    })
            elif stream_mode == "updates":
                results["updates_mode"].append({
                    "keys": list(data.keys()) if isinstance(data, dict) else None,
                    "has_error_key": "error" in data if isinstance(data, dict) else False,
                    "data_preview": str(data)[:200],
                })

    except Exception as e:
        results["exception_raised"] = {
            "type": type(e).__name__,
            "message": str(e)[:200],
        }
        print(f"    [异常捕获] {type(e).__name__}: {str(e)[:100]}")

    print(f"\n    messages 模式 chunks: {len(results['messages_mode'])}")
    for i, m in enumerate(results['messages_mode'][:3]):
        print(f"      [{i+1}] {m}")

    print(f"\n    updates 模式 chunks: {len(results['updates_mode'])}")
    for i, u in enumerate(results['updates_mode'][:3]):
        print(f"      [{i+1}] {u}")

    print(f"\n    exception_raised: {results['exception_raised']}")

    return results


async def test_resume_format():
    """测试中断恢复后的流格式"""
    print_separator("中断恢复后的流格式")

    interrupt_flag = {"count": 0}

    @tool
    def need_confirm(action: str) -> str:
        """需要确认的操作"""
        return f"已执行: {action}"

    tools = [need_confirm]
    checkpointer = MemorySaver()

    from langgraph.prebuilt.interrupt import HumanInterrupt
    from langgraph.types import Command

    agent = create_agent(
        model=llm,
        tools=tools,
        checkpointer=checkpointer,
        interrupt_before=["tools"],
    )

    thread_id = "test-resume-format"
    config = {"configurable": {"thread_id": thread_id}}

    print("\n>>> 第一阶段: 触发中断")
    print("-" * 40)

    first_run_chunks = []
    async for stream_mode, data in agent.astream(
        {"messages": [HumanMessage(content="用need_confirm执行测试")]},
        config=config,
        stream_mode=["updates"],
    ):
        first_run_chunks.append({
            "stream_mode": stream_mode,
            "data_keys": list(data.keys()) if isinstance(data, dict) else None,
        })

    print(f"    第一阶段 chunks: {len(first_run_chunks)}")
    for c in first_run_chunks:
        print(f"      {c}")

    print("\n>>> 获取当前状态 (snapshot)")
    print("-" * 40)

    snapshot = await agent.aget_state(config)
    snapshot_info = {
        "has_tasks": hasattr(snapshot, 'tasks') and snapshot.tasks is not None,
        "next_nodes": list(snapshot.next) if hasattr(snapshot, 'next') else [],
        "values_keys": list(snapshot.values.keys()) if hasattr(snapshot, 'values') and snapshot.values else [],
    }
    print(f"    snapshot: {json.dumps(snapshot_info, ensure_ascii=False)}")

    print("\n>>> 第二阶段: 恢复执行 (Command)")
    print("-" * 40)

    resume_command = Command(resume={"decisions": [{"type": "approve"}]})
    resume_chunks = []
    exception_info = None

    try:
        async for stream_mode, data in agent.astream(
            resume_command,
            config=config,
            stream_mode=["messages", "updates"],
        ):
            chunk_info = {
                "stream_mode": stream_mode,
                "data_type": type(data).__name__,
            }
            if isinstance(data, dict):
                chunk_info["keys"] = list(data.keys())
            elif isinstance(data, tuple):
                chunk_info["tuple_length"] = len(data)
            resume_chunks.append(chunk_info)
    except Exception as e:
        exception_info = {"type": type(e).__name__, "message": str(e)[:200]}
        print(f"    [异常] {exception_info}")

    print(f"    恢复后 chunks: {len(resume_chunks)}")
    for i, c in enumerate(resume_chunks[:5]):
        print(f"      [{i+1}] {c}")
    if len(resume_chunks) > 5:
        print(f"      ... ({len(resume_chunks) - 5} more)")

    return {
        "first_run": first_run_chunks,
        "snapshot": snapshot_info,
        "resume": resume_chunks,
        "exception": exception_info,
    }


async def test_values_state_structure():
    """测试 values 模式的 state 结构"""
    print_separator("values 模式 state 结构")

    tools = [get_weather]
    checkpointer = MemorySaver()

    agent = create_agent(model=llm, tools=tools, checkpointer=checkpointer)

    config = {"configurable": {"thread_id": "test-values-state"}}

    print("\n>>> 详细分析 values 模式的 state 结构")
    print("-" * 40)

    values_chunks = []
    async for stream_mode, data in agent.astream(
        {"messages": [HumanMessage(content="北京天气")]},
        config=config,
        stream_mode=["values"],
    ):
        chunk_info = {
            "stream_mode": stream_mode,
            "keys": list(data.keys()) if isinstance(data, dict) else [],
        }

        if isinstance(data, dict):
            if "messages" in data:
                messages = data["messages"]
                chunk_info["messages_count"] = len(messages)
                chunk_info["message_types"] = [type(m).__name__ for m in messages[-3:]]
                if messages:
                    last_msg = messages[-1]
                    chunk_info["last_msg_preview"] = str(getattr(last_msg, 'content', ''))[:50]

            for key in ["agent", "tools", "model"]:
                if key in data:
                    chunk_info[f"has_{key}"] = True

        values_chunks.append(chunk_info)

    print(f"    Total values chunks: {len(values_chunks)}")
    for i, c in enumerate(values_chunks):
        print(f"\n    [Chunk {i+1}]")
        for k, v in c.items():
            if k != "stream_mode":
                print(f"      {k}: {v}")

    return values_chunks


async def test_concurrent_stream():
    """测试并发/重入 - 同一 thread_id 同时发起两个 astream"""
    print_separator("并发/重入测试")

    tools = [get_weather]
    checkpointer = MemorySaver()

    agent = create_agent(model=llm, tools=tools, checkpointer=checkpointer)

    thread_id = "test-concurrent"
    config1 = {"configurable": {"thread_id": thread_id}}
    config2 = {"configurable": {"thread_id": thread_id}}

    results = {
        "stream1_chunks": 0,
        "stream2_chunks": 0,
        "stream1_error": None,
        "stream2_error": None,
    }

    async def run_stream1():
        try:
            async for _ in agent.astream(
                {"messages": [HumanMessage(content="北京天气")]},
                config=config1,
                stream_mode=["updates"],
            ):
                results["stream1_chunks"] += 1
        except Exception as e:
            results["stream1_error"] = {"type": type(e).__name__, "message": str(e)[:100]}

    async def run_stream2():
        await asyncio.sleep(0.1)
        try:
            async for _ in agent.astream(
                {"messages": [HumanMessage(content="上海天气")]},
                config=config2,
                stream_mode=["updates"],
            ):
                results["stream2_chunks"] += 1
        except Exception as e:
            results["stream2_error"] = {"type": type(e).__name__, "message": str(e)[:100]}

    print("\n>>> 同时启动两个相同 thread_id 的流")
    print("-" * 40)

    await asyncio.gather(run_stream1(), run_stream2())

    print(f"    Stream 1: chunks={results['stream1_chunks']}, error={results['stream1_error']}")
    print(f"    Stream 2: chunks={results['stream2_chunks']}, error={results['stream2_error']}")

    if results["stream1_error"] or results["stream2_error"]:
        print("\n    结论: 并发流会抛出异常")
    else:
        print("\n    结论: 并发流正常执行（可能串行化）")

    return results


async def test_stream_cancellation():
    """测试流取消 - 客户端断开时的处理"""
    print_separator("流取消测试")

    tools = [get_weather]
    checkpointer = MemorySaver()

    agent = create_agent(model=llm, tools=tools, checkpointer=checkpointer)

    thread_id = "test-cancellation"
    config = {"configurable": {"thread_id": thread_id}}

    print("\n>>> 模拟客户端断开（中途取消迭代）")
    print("-" * 40)

    chunks_collected = 0
    gen = agent.astream(
        {"messages": [HumanMessage(content="北京天气如何？请详细说明")]},
        config=config,
        stream_mode=["messages"],
    )

    try:
        async for chunk in gen:
            chunks_collected += 1
            if chunks_collected >= 3:
                print(f"    收集了 {chunks_collected} 个 chunks，模拟断开...")
                break
    except Exception as e:
        print(f"    迭代异常: {type(e).__name__}: {str(e)[:50]}")

    print(f"    中断时收集的 chunks: {chunks_collected}")

    print("\n>>> 检查中断后的 checkpoint 状态")
    print("-" * 40)

    snapshot = await agent.aget_state(config)
    state_info = {
        "next": list(snapshot.next) if hasattr(snapshot, 'next') else [],
        "values_keys": list(snapshot.values.keys()) if hasattr(snapshot, 'values') and snapshot.values else [],
        "messages_count": len(snapshot.values.get("messages", [])) if hasattr(snapshot, 'values') else 0,
    }
    print(f"    checkpoint state: {json.dumps(state_info, ensure_ascii=False)}")

    print("\n>>> 尝试恢复执行")
    print("-" * 40)

    try:
        resume_chunks = 0
        async for chunk in agent.astream(
            {"messages": [HumanMessage(content="继续")]},
            config=config,
            stream_mode=["updates"],
        ):
            resume_chunks += 1
        print(f"    恢复后 chunks: {resume_chunks}")
        print("    结论: 流取消后可以正常恢复")
    except Exception as e:
        print(f"    恢复异常: {type(e).__name__}: {str(e)[:100]}")

    return {
        "chunks_before_cancel": chunks_collected,
        "state_after_cancel": state_info,
    }


async def main():
    print("\n" + "=" * 60)
    print(" LangGraph 流格式测试 (完整版)")
    print(f" 时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    all_results = {}

    all_results["tuple_vs_single"] = await test_tuple_vs_single()
    all_results["stream_modes"] = await test_stream_modes()
    all_results["tools_stream"] = await test_tools_stream()
    all_results["subgraphs"] = await test_subgraphs_format()
    all_results["interrupt"] = await test_interrupt_format()
    all_results["messages_detailed"] = await test_messages_detailed()
    all_results["tool_calls"] = await test_tool_calls_format()
    all_results["write_todos"] = await test_write_todos_format()

    print("\n" + "=" * 60)
    print(" SSE 相关测试")
    print("=" * 60)

    all_results["error_handling"] = await test_error_handling()
    all_results["resume_format"] = await test_resume_format()
    all_results["values_state"] = await test_values_state_structure()
    all_results["concurrent"] = await test_concurrent_stream()
    all_results["cancellation"] = await test_stream_cancellation()

    print("\n" + "=" * 60)
    print(" 测试完成!")
    print("=" * 60)

    print("\n\n>>> 完整结果摘要:")
    print(json.dumps(all_results, ensure_ascii=False, indent=2, default=str))



if __name__ == "__main__":
    asyncio.run(main())
