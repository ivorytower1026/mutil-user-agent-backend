# Mem0 记忆工具简化实现方案（单用户模式）

> **版本**: v2.0 简化版  
> **更新日期**: 2026-03-04  
> **模式**: 单用户模式（无跨用户访问）

## 设计原则

1. **不向后兼容** - 直接使用新工具名
2. **仅支持text模式** - 不支持messages参数
3. **单用户隔离** - 所有工具自动注入user_id，禁止跨用户访问
4. **简化设计** - 移除不必要的复杂功能

---

## 工具列表（6个）

| 工具名 | 功能 | 参数 | 说明 |
|--------|------|------|------|
| `add_memory` | 保存记忆 | text, metadata | 只支持text，自动注入user_id |
| `search_memories` | 搜索记忆 | query, limit | 自动过滤当前用户 |
| `get_memories` | 列出记忆 | page, page_size | 自动过滤当前用户，支持分页 |
| `get_memory` | 获取单个记忆 | memory_id | 验证ownership |
| `update_memory` | 更新记忆 | memory_id, text | 验证ownership |
| `delete_memory` | 删除记忆 | memory_id | 验证ownership |

---

## 详细设计

### 1. add_memory

**功能**: 保存新的记忆

**参数**:
- `text`: str - 要保存的文本（必需）
- `metadata`: dict | None - 元数据（可选）

**实现**:
```python
def add_memory(
    text: str,
    metadata: dict | None = None,
    state: Annotated[dict, InjectedState] = None,
) -> str:
    """保存新记忆"""
    user_id = self._extract_user_id(state)
    
    try:
        # 构造conversation格式（Mem0要求）
        conversation = [{"role": "user", "content": text}]
        
        kwargs = {
            "user_id": user_id,
        }
        
        if metadata:
            kwargs["metadata"] = metadata
        
        result = self._memory_client.add(conversation, **kwargs)
        
        logger.info(f"[MemoryManager] Added memory for user {user_id}: {text[:50]}")
        
        return json.dumps(result, ensure_ascii=False, indent=2)
    
    except Exception as e:
        logger.exception(f"[MemoryManager] Failed to add memory: {e}")
        return json.dumps({"error": str(e)}, ensure_ascii=False)
```

**使用示例**:
```python
add_memory(
    text="用户偏好使用 Python 进行数据分析",
    metadata={"category": "preference"}
)
```

### 2. search_memories

**功能**: 语义搜索记忆

**参数**:
- `query`: str - 查询文本（必需）
- `limit`: int - 返回数量（默认5）

**实现**:
```python
def search_memories(
    query: str,
    limit: int = 5,
    state: Annotated[dict, InjectedState] = None,
) -> str:
    """搜索记忆（自动过滤当前用户）"""
    user_id = self._extract_user_id(state)
    
    try:
        # 自动添加user_id过滤
        filters = {"AND": [{"user_id": user_id}]}
        
        results = self._memory_client.search(
            query=query,
            filters=filters,
            limit=limit,
        )
        
        logger.info(
            f"[MemoryManager] Searched memories for user {user_id}: "
            f"query='{query}', found={len(results.get('results', []))}"
        )
        
        return json.dumps(results, ensure_ascii=False, indent=2)
    
    except Exception as e:
        logger.exception(f"[MemoryManager] Failed to search memories: {e}")
        return json.dumps({"error": str(e)}, ensure_ascii=False)
```

**使用示例**:
```python
search_memories(query="编程语言偏好", limit=5)
```

### 3. get_memories

**功能**: 列出记忆（支持分页）

**参数**:
- `page`: int - 页码（1-indexed，默认1）
- `page_size`: int - 每页数量（默认10）

**实现**:
```python
def get_memories(
    page: int = 1,
    page_size: int = 10,
    state: Annotated[dict, InjectedState] = None,
) -> str:
    """列出记忆（自动过滤当前用户，支持分页）"""
    user_id = self._extract_user_id(state)
    
    try:
        # 自动添加user_id过滤
        filters = {"AND": [{"user_id": user_id}]}
        
        results = self._memory_client.get_all(
            filters=filters,
            page=page,
            page_size=page_size,
        )
        
        logger.info(
            f"[MemoryManager] Got memories for user {user_id}: "
            f"page={page}, page_size={page_size}"
        )
        
        return json.dumps(results, ensure_ascii=False, indent=2)
    
    except Exception as e:
        logger.exception(f"[MemoryManager] Failed to get memories: {e}")
        return json.dumps({"error": str(e)}, ensure_ascii=False)
```

**使用示例**:
```python
# 获取第1页
get_memories(page=1, page_size=10)

# 获取第2页
get_memories(page=2, page_size=10)
```

### 4. get_memory

**功能**: 获取单个记忆

**参数**:
- `memory_id`: str - 记忆ID（必需）

**实现**:
```python
def get_memory(
    memory_id: str,
    state: Annotated[dict, InjectedState] = None,
) -> str:
    """获取单个记忆（验证ownership）"""
    user_id = self._extract_user_id(state)
    
    try:
        # 先获取记忆
        memory = self._memory_client.get(memory_id)
        
        # 验证ownership
        memory_user_id = memory.get("user_id")
        if memory_user_id != user_id:
            logger.warning(
                f"[MemoryManager] User {user_id} attempted to access "
                f"memory {memory_id} owned by {memory_user_id}"
            )
            return json.dumps(
                {"error": "Memory not found or access denied"},
                ensure_ascii=False
            )
        
        logger.info(
            f"[MemoryManager] Got memory {memory_id} for user {user_id}"
        )
        
        return json.dumps(memory, ensure_ascii=False, indent=2)
    
    except Exception as e:
        logger.exception(f"[MemoryManager] Failed to get memory: {e}")
        return json.dumps({"error": str(e)}, ensure_ascii=False)
```

**使用示例**:
```python
get_memory(memory_id="mem_abc123")
```

### 5. update_memory

**功能**: 更新记忆内容

**参数**:
- `memory_id`: str - 记忆ID（必需）
- `text`: str - 新的文本内容（必需）

**实现**:
```python
def update_memory(
    memory_id: str,
    text: str,
    state: Annotated[dict, InjectedState] = None,
) -> str:
    """更新记忆内容（验证ownership）"""
    user_id = self._extract_user_id(state)
    
    try:
        # 先获取记忆验证ownership
        memory = self._memory_client.get(memory_id)
        
        memory_user_id = memory.get("user_id")
        if memory_user_id != user_id:
            logger.warning(
                f"[MemoryManager] User {user_id} attempted to update "
                f"memory {memory_id} owned by {memory_user_id}"
            )
            return json.dumps(
                {"error": "Memory not found or access denied"},
                ensure_ascii=False
            )
        
        # 更新记忆
        result = self._memory_client.update(memory_id=memory_id, text=text)
        
        logger.info(
            f"[MemoryManager] Updated memory {memory_id} for user {user_id}"
        )
        
        return json.dumps(result, ensure_ascii=False, indent=2)
    
    except Exception as e:
        logger.exception(f"[MemoryManager] Failed to update memory: {e}")
        return json.dumps({"error": str(e)}, ensure_ascii=False)
```

**使用示例**:
```python
update_memory(
    memory_id="mem_abc123",
    text="用户偏好使用 Python 和 JavaScript"
)
```

### 6. delete_memory

**功能**: 删除记忆

**参数**:
- `memory_id`: str - 记忆ID（必需）

**实现**:
```python
def delete_memory(
    memory_id: str,
    state: Annotated[dict, InjectedState] = None,
) -> str:
    """删除记忆（验证ownership）"""
    user_id = self._extract_user_id(state)
    
    try:
        # 先获取记忆验证ownership
        memory = self._memory_client.get(memory_id)
        
        memory_user_id = memory.get("user_id")
        if memory_user_id != user_id:
            logger.warning(
                f"[MemoryManager] User {user_id} attempted to delete "
                f"memory {memory_id} owned by {memory_user_id}"
            )
            return json.dumps(
                {"error": "Memory not found or access denied"},
                ensure_ascii=False
            )
        
        # 删除记忆
        self._memory_client.delete(memory_id)
        
        logger.info(
            f"[MemoryManager] Deleted memory {memory_id} for user {user_id}"
        )
        
        return json.dumps(
            {"success": True, "message": f"Memory {memory_id} deleted"},
            ensure_ascii=False
        )
    
    except Exception as e:
        logger.exception(f"[MemoryManager] Failed to delete memory: {e}")
        return json.dumps({"error": str(e)}, ensure_ascii=False)
```

**使用示例**:
```python
delete_memory(memory_id="mem_abc123")
```

---

## 核心辅助函数

### _extract_user_id

```python
def _extract_user_id(self, state: dict) -> str:
    """
    从工具的 state 中提取用户ID
    
    Args:
        state: InjectedState 注入的 state 字典
    
    Returns:
        user_id 字符串
    """
    config = state.get("config", {})
    configurable = config.get("configurable", {})
    thread_id = configurable.get("thread_id")
    
    if not thread_id:
        logger.warning("[MemoryManager] No thread_id found, using 'default'")
        return "default"
    
    # thread_id 格式: {user_id}-{uuid}
    # 取前36个字符作为user_id
    user_id = thread_id[:36] if len(thread_id) > 37 else "default"
    
    logger.debug(f"[MemoryManager] Extracted user_id: {user_id} from thread_id: {thread_id}")
    
    return user_id
```

---

## 安全特性

### 1. 自动用户隔离

所有工具自动注入 `user_id`，无需手动传递：

```python
# ✅ 正确 - 自动注入user_id
search_memories(query="编程语言")

# ❌ 不需要 - 不支持跨用户
search_memories(query="编程语言", user_id="other_user")  # 参数不存在
```

### 2. Ownership验证

对于 `get_memory`, `update_memory`, `delete_memory`，都会验证记忆的ownership：

```python
# 获取记忆
memory = self._memory_client.get(memory_id)

# 验证ownership
if memory.get("user_id") != current_user_id:
    return {"error": "Memory not found or access denied"}
```

### 3. 防止信息泄露

- 搜索和列表操作自动添加 `user_id` 过滤
- 不提供 `list_entities` 和 `delete_entities` 工具
- 禁止跨用户访问

---

## 错误处理

所有工具统一返回JSON格式的错误：

```json
{
  "error": "Error message here"
}
```

成功返回：

```json
{
  "results": [...],
  ...
}
```

---

## System Prompt 更新

```python
MEMORY_SYSTEM_PROMPT = """
# 记忆系统使用指南

你拥有一个智能记忆系统，可以保存和检索信息。

## 可用工具

1. **add_memory(text, metadata)** - 保存记忆
   - text: 要保存的文本
   - metadata: 可选的元数据

2. **search_memories(query, limit)** - 搜索记忆
   - query: 查询文本
   - limit: 返回数量（默认5）

3. **get_memories(page, page_size)** - 列出记忆
   - page: 页码（默认1）
   - page_size: 每页数量（默认10）

4. **get_memory(memory_id)** - 获取单个记忆
   - memory_id: 记忆ID

5. **update_memory(memory_id, text)** - 更新记忆
   - memory_id: 记忆ID
   - text: 新的文本内容

6. **delete_memory(memory_id)** - 删除记忆
   - memory_id: 记忆ID

## 使用场景

**保存记忆**:
- 用户表达偏好："我喜欢用Python"
- 用户背景信息："我是后端工程师"
- 重要项目信息："项目使用Django框架"

**检索记忆**:
- 用户询问："我之前说过什么？"
- 需要上下文："根据我的技术栈..."

## 注意事项

- 记忆是用户级别的，跨会话保留
- 会话级短期记忆由LangGraph自动管理
- 不要保存敏感信息（密码、密钥等）
"""
```

---

## 文件修改清单

### src/memory_manager.py

**修改内容**:
1. 删除 `save_memory`, `search_memory`, `list_memories` 等旧工具
2. 添加 6 个新工具方法
3. 简化 `_extract_user_id` 方法
4. 统一错误处理格式

**预计修改**: ~200行代码

### src/agent_manager.py

**修改内容**:
1. 更新 `MEMORY_SYSTEM_PROMPT`
2. 工具集成保持不变

**预计修改**: ~50行代码

---

## 测试用例

### 1. 基础功能测试

```python
# 测试添加记忆
result = add_memory(text="用户喜欢Python")
assert "error" not in result

# 测试搜索记忆
results = search_memories(query="编程语言")
assert len(results["results"]) > 0

# 测试列出记忆
memories = get_memories(page=1, page_size=10)
assert "results" in memories
```

### 2. 用户隔离测试

```python
# 用户A保存记忆
user_a_state = {"config": {"configurable": {"thread_id": "user-a-123"}}}
add_memory(text="用户A的偏好", state=user_a_state)

# 用户B搜索（应该搜不到用户A的记忆）
user_b_state = {"config": {"configurable": {"thread_id": "user-b-456"}}}
results = search_memories(query="偏好", state=user_b_state)
assert len(results["results"]) == 0
```

### 3. Ownership验证测试

```python
# 用户A创建记忆
user_a_state = {"config": {"configurable": {"thread_id": "user-a-123"}}}
result = add_memory(text="测试记忆", state=user_a_state)
memory_id = result["results"][0]["id"]

# 用户B尝试访问（应该失败）
user_b_state = {"config": {"configurable": {"thread_id": "user-b-456"}}}
result = get_memory(memory_id=memory_id, state=user_b_state)
assert "error" in result
```

---

## 实施计划

### Phase 1: 核心工具实现（1天）
- [ ] 实现 `add_memory`
- [ ] 实现 `search_memories`
- [ ] 实现 `get_memories`
- [ ] 测试基础功能

### Phase 2: 管理工具实现（0.5天）
- [ ] 实现 `get_memory`
- [ ] 实现 `update_memory`
- [ ] 实现 `delete_memory`
- [ ] 测试ownership验证

### Phase 3: 集成测试（0.5天）
- [ ] 测试用户隔离
- [ ] 测试System Prompt
- [ ] 端到端测试

---

**状态**: 设计完成，待实现  
**预计工期**: 2天  
**风险**: 低（简化设计，无复杂依赖）
