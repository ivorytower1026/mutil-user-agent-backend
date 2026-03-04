import asyncio

from src.config import big_llm
from deepagents import create_deep_agent
from langchain.agents import create_agent

from langchain_core.messages import HumanMessage, SystemMessage


agent_2 = create_deep_agent(
            model=big_llm,
            system_prompt="你的名字是小明",
)

messages_2 = [
    SystemMessage(content="你处于plan模式，只能思考，不能写文件。另外今天长沙的温度是20摄氏度"),
    HumanMessage(content="今天长沙温度是多少度")
]

async def main_2():
    print("\n🚀 开始执行 create_deep_agent...\n")

    async for token, _metadata in agent.astream(
            {"messages": messages_2},
            stream_mode="messages"
    ):
        print(token.content, end="", flush=True)

agent = create_agent(
            model=big_llm,
            system_prompt="你的名字是小明",
)

messages_1 = [
    SystemMessage(content="你处于plan模式，只能思考，不能写文件。另外今天长沙的温度是20摄氏度"),
    HumanMessage(content="今天长沙温度是多少度")
]

async def main_1():
    print("\n🚀 开始执行 create_agent...\n")

    async for token, _metadata in agent.astream(
            {"messages": messages_1},
            stream_mode="messages"
    ):
        print(token.content, end="", flush=True)


messages = [
	SystemMessage(content="你的名字是小明"),
    SystemMessage(content="你处于plan模式，只能思考，不能写文件。另外今天长沙的温度是20摄氏度"),
    HumanMessage(content="你的名字是什么？"),
    # HumanMessage(content="今天长沙温度是多少度"),
]


async def main():
    print("\n🚀 开始执行 普通llm...\n")

    # 直接传 messages 列表，不要包 dict
    async for chunk in big_llm.astream(messages):
        print(chunk.content, end="", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
    asyncio.run(main_1())
    asyncio.run(main_2())