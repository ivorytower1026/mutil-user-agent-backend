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

from src.config import big_llm


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
        model=big_llm,
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

    agent = create_agent(model=big_llm, tools=tools, checkpointer=checkpointer)

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
        model=big_llm,
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

    agent = create_agent(model=big_llm, tools=tools, checkpointer=checkpointer)

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

    agent = create_agent(model=big_llm, tools=tools, checkpointer=checkpointer)

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

    agent = create_agent(model=big_llm, tools=tools, checkpointer=checkpointer)

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


async def main():
    print("\n" + "=" * 60)
    print(" LangGraph 流格式测试 (精简版)")
    print(f" 时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    all_results = {}

    all_results["tuple_vs_single"] = await test_tuple_vs_single()
    all_results["stream_modes"] = await test_stream_modes()
    all_results["tools_stream"] = await test_tools_stream()
    all_results["subgraphs"] = await test_subgraphs_format()
    all_results["interrupt"] = await test_interrupt_format()
    all_results["messages_detailed"] = await test_messages_detailed()

    print("\n" + "=" * 60)
    print(" 测试完成!")
    print("=" * 60)

    print("\n\n>>> 完整结果摘要:")
    print(json.dumps(all_results, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())
