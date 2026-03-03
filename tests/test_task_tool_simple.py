"""
简化测试：检测 task 工具调用
运行: uv run python -m tests.test_task_tool_simple
"""

import asyncio
from langchain_core.messages import HumanMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import MemorySaver
from deepagents import create_deep_agent
from deepagents.middleware.subagents import SubAgent
from src.config import big_llm


@tool
def get_weather(city: str) -> str:
    """获取城市天气"""
    return f"{city}的天气: 晴朗, 25°C"


@tool
def simple_calc(expr: str) -> str:
    """计算"""
    try:
        return f"结果: {eval(expr)}"
    except Exception as e:
        return f"错误: {e}"


async def main():
    print("\n" + "=" * 70)
    print(" 测试 task 工具调用检测")
    print("=" * 70)

    # 创建子代理
    weather_subagent: SubAgent = {
        "name": "weather_agent",
        "description": "天气查询子代理",
        "system_prompt": "你是天气查询助手",
        "tools": [get_weather],
    }

    checkpointer = MemorySaver()

    agent = create_deep_agent(
        model=big_llm,
        backend=None,
        checkpointer=checkpointer,
        tools=[simple_calc],  # 普通工具
        subagents=[weather_subagent],  # 子代理
    )

    config = {"configurable": {"thread_id": "test-task-simple"}}

    print("\n>>> 测试1: 只调用普通工具")
    print("-" * 70)

    chunk_count = 0
    tool_calls_found = []

    try:
        async for chunk in agent.astream(
            {"messages": [HumanMessage(content="计算 5+3")]},
            config=config,
            stream_mode=["updates"],
            subgraphs=True,
        ):
            chunk_count += 1

            # 打印前10个chunk的原始格式
            if chunk_count <= 10:
                print(f"\n[Chunk {chunk_count}]")
                print(f"  type: {type(chunk)}")
                print(
                    f"  value: {chunk if not isinstance(chunk, tuple) else f'tuple(len={len(chunk)})'}"
                )

            # 处理 chunk
            if isinstance(chunk, tuple):
                if len(chunk) == 3:
                    namespace, stream_mode, data = chunk
                elif len(chunk) == 2:
                    namespace, data = chunk
                    stream_mode = "updates"
                else:
                    continue

                # 检查 model 节点中的 tool_calls
                if isinstance(data, dict) and "model" in data:
                    model_data = data["model"]
                    if isinstance(model_data, dict) and "messages" in model_data:
                        for msg in model_data.get("messages", []):
                            if hasattr(msg, "tool_calls") and msg.tool_calls:
                                for tc in msg.tool_calls:
                                    if isinstance(tc, dict):
                                        tool_info = {
                                            "chunk": chunk_count,
                                            "namespace": namespace,
                                            "tool_name": tc.get("name"),
                                            "tool_args": tc.get("args"),
                                        }
                                        tool_calls_found.append(tool_info)
                                        print(f"\n  ★ 检测到工具调用:")
                                        print(f"    namespace: {namespace}")
                                        print(f"    tool_name: {tc.get('name')}")
                                        print(f"    tool_args: {tc.get('args')}")

        print(f"\n总共 {chunk_count} 个chunks")
        print(f"检测到 {len(tool_calls_found)} 个工具调用")

    except Exception as e:
        print(f"\n错误: {e}")
        import traceback

        traceback.print_exc()

    # 测试2: 调用子代理
    print("\n\n>>> 测试2: 调用子代理")
    print("-" * 70)

    config2 = {"configurable": {"thread_id": "test-task-simple-2"}}
    chunk_count2 = 0
    tool_calls_found2 = []

    try:
        async for chunk in agent.astream(
            {"messages": [HumanMessage(content="北京天气如何？")]},
            config=config2,
            stream_mode=["updates"],
            subgraphs=True,
        ):
            chunk_count2 += 1

            # 打印前15个chunk的原始格式
            if chunk_count2 <= 15:
                print(f"\n[Chunk {chunk_count2}]")
                if isinstance(chunk, tuple):
                    if len(chunk) == 3:
                        namespace, stream_mode, data = chunk
                        print(f"  namespace: {namespace}")
                        print(f"  stream_mode: {stream_mode}")
                    elif len(chunk) == 2:
                        namespace, data = chunk
                        print(f"  namespace: {namespace}")

            # 处理 chunk
            if isinstance(chunk, tuple):
                if len(chunk) == 3:
                    namespace, stream_mode, data = chunk
                elif len(chunk) == 2:
                    namespace, data = chunk
                else:
                    continue

                # 检查 model 节点中的 tool_calls
                if isinstance(data, dict) and "model" in data:
                    model_data = data["model"]
                    if isinstance(model_data, dict) and "messages" in model_data:
                        for msg in model_data.get("messages", []):
                            if hasattr(msg, "tool_calls") and msg.tool_calls:
                                for tc in msg.tool_calls:
                                    if isinstance(tc, dict):
                                        tool_info = {
                                            "chunk": chunk_count2,
                                            "namespace": namespace,
                                            "tool_name": tc.get("name"),
                                            "tool_args": tc.get("args"),
                                        }
                                        tool_calls_found2.append(tool_info)
                                        print(f"\n  ★ 检测到工具调用:")
                                        print(f"    namespace: {namespace}")
                                        print(f"    tool_name: {tc.get('name')}")
                                        print(f"    tool_args: {tc.get('args')}")

        print(f"\n总共 {chunk_count2} 个chunks")
        print(f"检测到 {len(tool_calls_found2)} 个工具调用")

    except Exception as e:
        print(f"\n错误: {e}")
        import traceback

        traceback.print_exc()

    # 总结
    print("\n" + "=" * 70)
    print(" 测试总结")
    print("=" * 70)

    print(f"\n测试1（普通工具）:")
    print(f"  工具调用: {[tc['tool_name'] for tc in tool_calls_found]}")

    print(f"\n测试2（子代理）:")
    print(f"  工具调用: {[tc['tool_name'] for tc in tool_calls_found2]}")

    # 检查是否有 task 工具
    task_calls = [tc for tc in tool_calls_found2 if tc["tool_name"] == "task"]
    if task_calls:
        print(f"\n✅ 检测到 task 工具调用！")
        for tc in task_calls:
            print(f"  - args: {tc['tool_args']}")
    else:
        print(f"\n❌ 未检测到 task 工具调用")
        print("   可能的原因:")
        print("   1. DeepAgents 版本不支持")
        print("   2. 子代理配置不正确")
        print("   3. LLM 没有调用子代理")


if __name__ == "__main__":
    asyncio.run(main())
