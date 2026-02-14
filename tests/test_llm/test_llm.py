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

messages = [
    SystemMessage(content="你是一个资深Python工程师"),
    HumanMessage(content="实现一个LRU缓存")
]

resp = llm_minimax_m2_1.invoke(messages)

print(resp.content)