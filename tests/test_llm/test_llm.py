import asyncio

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage,SystemMessage

from src.config import settings

llm_qwen3_vl_30b_a3b_instruct = ChatOpenAI(
    model="Qwen3-VL-30B-A3B-Instruct",
    base_url=settings.OPENAI_API_BASE_8001,
    api_key="EMPTY",   # vllm不校验
    temperature=0.7,
    max_tokens=1024,
)


llm_minimax_m2_1 = ChatOpenAI(
    model="MiniMax-M2.1",
    base_url=settings.OPENAI_API_BASE_8002,
    api_key="EMPTY",   # vllm不校验
    temperature=0.7,
    max_tokens=1024,
)


llm_Qwen3_5_35B_A3B = ChatOpenAI(
    model="Qwen3.5-35B-A3B",
    base_url=settings.OPENAI_API_BASE_8001,
    api_key="EMPTY",   # vllm不校验
    temperature=0,
    max_tokens=1024,
    extra_body={
        "chat_template_kwargs": {
            "enable_thinking": False
        }
    }
)

messages = [
    HumanMessage(content="用10个字总结中国")
]

# resp = llm_Qwen3_5_35B_A3B.invoke(messages)
#
# print(resp.content)


messages = [
	SystemMessage(content="你的名字是小明"),
    HumanMessage(content="用10个字总结中国"),
]


async def main():
    print("\n🚀 开始执行 普通llm...\n")

    # 直接传 messages 列表，不要包 dict
    async for chunk in llm_Qwen3_5_35B_A3B.astream(messages):
        print(chunk.content, end="", flush=True)


if __name__ == "__main__":
    asyncio.run(main())