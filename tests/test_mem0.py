from mem0 import Memory

config = {
    "vector_store": {
        "provider": "qdrant",
        "config": {
            "collection_name": "test",
            "host": "localhost",
            "port": 6333,
            "embedding_model_dims": 1024,  # 匹配 Qwen3-Embedding-0.6B 的维度
        },
    },
    "llm": {
        "provider": "vllm",
        "config": {
            "model": "Qwen3-VL-30B-A3B-Instruct",
            "vllm_base_url": "http://192.168.110.44:8001/v1",
            "temperature": 0,
            "max_tokens": 2000,
        },

    },
    "embedder": {
        "provider": "openai",
        "config": {
            "model": "Qwen3-Embedding-0.6B",
            "api_key": "dummy-key",  # vLLM 本地不需要真实 key
            "openai_base_url": "http://192.168.110.44:8008/v1",
            "embedding_dims": 1024,
        },
    },
}

# 初始化 Memory
m = Memory.from_config(config)

# 添加记忆
result = m.add("I'm visiting Paris", user_id="john")
print("添加结果:", result)

# 添加更多记忆
m.add("I love eating sushi and ramen", user_id="john")
m.add("My favorite programming language is Python", user_id="john")
m.add("I love eating meal", user_id="john")


# 获取所有记忆
memories = m.get_all(user_id="john")
print("所有记忆:", memories)

# 搜索记忆
search_results = m.search("What food does john like recently?", user_id="john")
print("搜索结果:", search_results)