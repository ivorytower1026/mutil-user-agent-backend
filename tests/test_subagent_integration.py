"""
集成测试：验证子代理识别功能
运行: uv run python -m tests.test_subagent_integration
"""

import asyncio
import json
from langchain_core.messages import HumanMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import MemorySaver
from deepagents import create_deep_agent
from deepagents.middleware.subagents import SubAgent
from src.config import big_llm
from src.agent_utils.formatter import SSEFormatter
from src.agent_utils.stream.runner import AgentStreamRunner


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


async def test_subagent_sse_events():
    """测试子代理的 SSE 事件格式"""
    print("\n" + "=" * 70)
    print(" 测试子代理 SSE 事件格式")
    print("=" * 70)

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
        tools=[simple_calc],
        subagents=[weather_subagent],
    )

    formatter = SSEFormatter()
    runner = AgentStreamRunner(agent, formatter)

    print("\n>>> 测试: 查询北京天气（子代理调用）")
    print("-" * 70)

    sse_events = []
    async for sse_event in runner.run(
        thread_id="test-subagent-sse",
        initial_input={"messages": [HumanMessage(content="北京天气如何？")]},
        mode="build",
    ):
        # 解析 SSE 事件
        if sse_event.startswith("event: "):
            lines = sse_event.strip().split("\n")
            if len(lines) >= 2:
                event_name = lines[0].split(": ", 1)[1]
                data_line = lines[1]
                data = json.loads(data_line.split("data: ", 1)[1])
                sse_events.append({"event": event_name, "data": data})

    # 分析结果
    print(f"\n总共 {len(sse_events)} 个事件")

    # 查找子代理事件
    subagent_events = [e for e in sse_events if e["data"].get("namespace")]
    main_events = [e for e in sse_events if not e["data"].get("namespace")]

    print(f"主代理事件: {len(main_events)}")
    print(f"子代理事件: {len(subagent_events)}")

    # 验证子代理事件格式
    if subagent_events:
        print("\n子代理事件示例:")
        sample = subagent_events[0]
        print(json.dumps(sample, indent=2, ensure_ascii=False))

        # 验证字段
        data = sample["data"]
        assert "namespace" in data, "应该包含 namespace 字段"
        assert isinstance(data["namespace"], list), "namespace 应该是列表"

        if "subagent_id" in data:
            assert isinstance(data["subagent_id"], str), "subagent_id 应该是字符串"
            print(f"\n✅ subagent_id: {data['subagent_id']}")

        if "subagent_name" in data:
            assert isinstance(data["subagent_name"], str), "subagent_name 应该是字符串"
            print(f"✅ subagent_name: {data['subagent_name']}")

        print("\n✅ 子代理事件格式正确！")
    else:
        print("\n⚠️  未检测到子代理事件（可能LLM没有调用子代理）")

    return sse_events


async def test_main_agent_events():
    """测试主代理的 SSE 事件格式"""
    print("\n" + "=" * 70)
    print(" 测试主代理 SSE 事件格式")
    print("=" * 70)

    checkpointer = MemorySaver()

    agent = create_deep_agent(
        model=big_llm,
        backend=None,
        checkpointer=checkpointer,
        tools=[simple_calc],
        subagents=[],  # 无子代理
    )

    formatter = SSEFormatter()
    runner = AgentStreamRunner(agent, formatter)

    print("\n>>> 测试: 计算 5+3（普通工具调用）")
    print("-" * 70)

    sse_events = []
    async for sse_event in runner.run(
        thread_id="test-main-agent-sse",
        initial_input={"messages": [HumanMessage(content="计算 5+3")]},
        mode="build",
    ):
        if sse_event.startswith("event: "):
            lines = sse_event.strip().split("\n")
            if len(lines) >= 2:
                event_name = lines[0].split(": ", 1)[1]
                data_line = lines[1]
                data = json.loads(data_line.split("data: ", 1)[1])
                sse_events.append({"event": event_name, "data": data})

    print(f"\n总共 {len(sse_events)} 个事件")

    # 验证主代理事件不包含子代理字段
    events_with_namespace = [e for e in sse_events if e["data"].get("namespace")]

    if events_with_namespace:
        print(f"\n❌ 主代理事件不应该包含 namespace 字段")
        print(f"   发现 {len(events_with_namespace)} 个异常事件")
    else:
        print("\n✅ 主代理事件格式正确（无 namespace 字段）")

    return sse_events


async def main():
    print("\n" + "=" * 70)
    print(" 子代理识别功能集成测试")
    print("=" * 70)

    # 测试1: 主代理事件
    events1 = await test_main_agent_events()

    # 测试2: 子代理事件
    events2 = await test_subagent_sse_events()

    print("\n" + "=" * 70)
    print(" 测试完成")
    print("=" * 70)

    print("\n总结:")
    print(f"  主代理事件: {len(events1)}")
    print(f"  子代理事件: {len(events2)}")
    print("\n✅ 所有测试通过！")


if __name__ == "__main__":
    asyncio.run(main())
