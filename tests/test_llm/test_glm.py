
from langchain_core.messages import HumanMessage,SystemMessage

from src.config import llm_glm_5

messages = [
    HumanMessage(content="你好")
]

resp = llm_glm_5.invoke(messages)

print(resp.content)