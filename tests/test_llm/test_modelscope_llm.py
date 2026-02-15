from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage,SystemMessage

from src.config import settings

llm_modelscope_qwen3_vl_30b_a3b_instruct = ChatOpenAI(
    model="Qwen/Qwen3-VL-30B-A3B-Instruct",
    base_url=settings.MODELSCOPE_URL,
    api_key=settings.MODELSCOPE_SDK_TOKEN,
    temperature=0.7,
    max_tokens=1024,
)

messages = [
    SystemMessage(content="你是一个资深Python工程师"),
    HumanMessage(content="实现一个LRU缓存")
]

resp = llm_modelscope_qwen3_vl_30b_a3b_instruct.invoke(messages)

print(resp.content)