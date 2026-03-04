# Mem0 记忆工具重新设计方案（参考官方实现）

> **更新日期**: 2026-03-04  
> **版本**: v2.0  
> **参考**: Mem0 Official MCP Server

## 变更说明

参考 Mem0 官方 MCP Server 实现，将原有的4个工具扩展为9个完整工具，提供更强大的记忆管理能力。

---

## 工具列表对比

### 旧版本（4个工具）
1. `save_memory` - 保存记忆
2. `search_memory` - 检索记忆
3. `list_memories` - 列出记忆
4. `delete_memory` - 删除记忆

### 新版本（9个工具，参考官方）
1. `add_memory` - 保存记忆（支持text和messages两种方式）
2. `search_memories` - 语义搜索（支持filters）
3. `get_memories` - 列出记忆（支持filters和pagination）
4. `get_memory` - 获取单个记忆（通过memory_id）
5. `update_memory` - 更新记忆文本
6. `delete_memory` - 删除单个记忆
7. `delete_all_memories` - 批量删除记忆
8. `delete_entities` - 删除实体（用户/agent/app/run）
9. `list_entities` - 列出所有实体

---

## 核心改进

### 1. 更灵活的保存方式

**旧版本**：
```python
save_memory(content="用户喜欢Python", metadata={"category": "preference"})
```

**新版本（支持两种方式）**：
```python
# 方式1: 简单文本
add_memory(text="用户喜欢使用 Python 做数据分析", metadata={"category": "preference"})

# 方式2: 对话历史
add_memory(
    messages=[
        {"role": "user", "content": "我喜欢用 Python"},
        {"role": "assistant", "content": "好的，我记住了"}
    ],
    metadata={"category": "preference"}
)
```

### 2. 高级过滤功能

**新版本支持filters**：
```python
# 单个用户
search_memories(
    query="编程语言",
    filters={"AND": [{"user_id": "john"}]}
)

# 多个用户
get_memories(
    filters={"AND": [{"user_id": {"in": ["john", "jane"]}}]}
)

# 时间范围
get_memories(
    filters={"AND": [
        {"user_id": "john"},
        {"created_at": {"gte": "2024-01-01"}}
    ]}
)

# 复杂查询
search_memories(
    query="技术栈",
    filters={"OR": [
        {"user_id": "john"},
        {"agent_id": "assistant"}
    ]}
)
```

### 3. 分页支持

**新版本支持分页**：
```python
# 第1页，每页10条
get_memories(page=1, page_size=10)

# 第2页
get_memories(page=2, page_size=10)
```

### 4. 实体管理

**新版本支持实体级别操作**：
```python
# 列出所有用户
list_entities()

# 删除用户及其所有记忆
delete_entities(user_id="john")

# 删除用户的所有记忆但保留用户实体
delete_all_memories(user_id="john")
```

---

## 详细工具设计

### 1. add_memory

**功能**: 保存新的偏好、事实或对话片段

**参数**:
- `text`: str - 要保存的文本（必需，即使提供了messages）
- `messages`: list[dict] | None - 对话历史（可选）
- `metadata`: dict | None - 附加元数据（可选）

**使用场景**:
```python
# 场景1: 保存用户偏好
add_memory(
    text="用户偏好使用 Python 进行数据分析",
    metadata={"category": "preference", "domain": "data_analysis"}
)

# 场景2: 保存对话历史
add_memory(
    text="用户是后端工程师",
    messages=[
        {"role": "user", "content": "我是后端工程师"},
        {"role": "assistant", "content": "好的，我记住了"}
    ],
    metadata={"category": "background"}
)
```

### 2. search_memories

**功能**: 语义搜索现有记忆

**参数**:
- `query`: str - 自然语言查询（必需）
- `filters`: dict | None - 过滤条件（可选）
- `limit`: int | None - 返回数量（可选，默认5）

**使用场景**:
```python
# 简单搜索
search_memories(query="用户的编程语言偏好")

# 带过滤的搜索
search_memories(
    query="技术栈",
    filters={"AND": [{"user_id": "john"}]},
    limit=10
)

# 复杂过滤
search_memories(
    query="最近的项目",
    filters={"AND": [
        {"user_id": "john"},
        {"created_at": {"gte": "2024-01-01"}}
    ]}
)
```

### 3. get_memories

**功能**: 使用过滤器分页浏览记忆

**参数**:
- `filters`: dict | None - 过滤条件（可选）
- `page`: int | None - 页码（1-indexed）
- `page_size`: int | None - 每页数量（默认10）

**使用场景**:
```python
# 获取用户所有记忆
get_memories(filters={"AND": [{"user_id": "john"}]})

# 分页获取
get_memories(page=1, page_size=20)

# 按时间过滤
get_memories(
    filters={"AND": [
        {"user_id": "john"},
        {"created_at": {"gte": "2024-01-01"}}
    ]},
    page=1,
    page_size=10
)
```

### 4. get_memory

**功能**: 根据memory_id获取单个记忆

**参数**:
- `memory_id`: str - 记忆ID（必需）

**使用场景**:
```python
# 获取特定记忆
get_memory(memory_id="mem_abc123")
```

### 5. update_memory

**功能**: 覆盖现有记忆的文本

**参数**:
- `memory_id`: str - 记忆ID（必需）
- `text`: str - 新的文本内容（必需）

**使用场景**:
```python
# 更新记忆内容
update_memory(
    memory_id="mem_abc123",
    text="用户偏好使用 Python 和 JavaScript"
)
```

### 6. delete_memory

**功能**: 删除单个记忆

**参数**:
- `memory_id`: str - 记忆ID（必需）

**使用场景**:
```python
# 删除特定记忆
delete_memory(memory_id="mem_abc123")
```

### 7. delete_all_memories

**功能**: 批量删除指定范围的所有记忆（保留实体）

**参数**:
- `user_id`: str | None - 用户ID（可选）
- `agent_id`: str | None - Agent ID（可选）
- `app_id`: str | None - App ID（可选）
- `run_id`: str | None - Run ID（可选）

**使用场景**:
```python
# 删除用户的所有记忆
delete_all_memories(user_id="john")

# 删除特定agent的记忆
delete_all_memories(agent_id="assistant")
```

### 8. delete_entities

**功能**: 删除用户/agent/app/run实体（及其所有记忆）

**参数**:
- `user_id`: str | None - 用户ID（可选）
- `agent_id`: str | None - Agent ID（可选）
- `app_id`: str | None - App ID（可选）
- `run_id`: str | None - Run ID（可选）

**使用场景**:
```python
# 删除用户及所有记忆
delete_entities(user_id="john")

# 删除agent及所有记忆
delete_entities(agent_id="assistant")
```

### 9. list_entities

**功能**: 列出当前存储记忆的所有用户/agent/app/run

**参数**: 无

**使用场景**:
```python
# 列出所有实体
list_entities()
```

---

## 过滤器语法

### 基本过滤器

```python
# 单个条件
{"user_id": "john"}

# 使用操作符
{"created_at": {"gte": "2024-01-01"}}
{"user_id": {"in": ["john", "jane"]}}
```

### 组合过滤器

```python
# AND
{"AND": [
    {"user_id": "john"},
    {"category": "preference"}
]}

# OR
{"OR": [
    {"user_id": "john"},
    {"agent_id": "assistant"}
]}

# NOT
{"NOT": {"category": "temp"}}

# 嵌套组合
{"AND": [
    {"OR": [
        {"user_id": "john"},
        {"user_id": "jane"}
    ]},
    {"created_at": {"gte": "2024-01-01"}}
]}
```

### 支持的操作符

- `eq`: 等于（默认）
- `neq`: 不等于
- `gt`: 大于
- `gte`: 大于等于
- `lt`: 小于
- `lte`: 小于等于
- `in`: 在列表中
- `nin`: 不在列表中

---

## 实现优先级

### Phase 1: 核心工具（必需）
- [x] `add_memory`
- [x] `search_memories`
- [x] `get_memories`
- [x] `delete_memory`

### Phase 2: 管理工具（重要）
- [ ] `get_memory`
- [ ] `update_memory`
- [ ] `delete_all_memories`

### Phase 3: 高级工具（可选）
- [ ] `list_entities`
- [ ] `delete_entities`

---

## 兼容性说明

### 向后兼容

为了保持兼容性，旧工具名称将作为别名保留：

```python
# 旧名称（别名）
save_memory(...) → add_memory(...)
search_memory(...) → search_memories(...)
list_memories(...) → get_memories(...)
```

### 渐进式迁移

1. **阶段1**: 同时支持新旧API
2. **阶段2**: 新功能只在新API中提供
3. **阶段3**: 弃用旧API（发出警告）
4. **阶段4**: 移除旧API

---

## System Prompt 更新

```python
MEMORY_SYSTEM_PROMPT = """
# 记忆系统使用指南（v2.0）

你拥有一个智能记忆系统，可以保存和检索信息。

## 可用工具

### 保存记忆
- `add_memory`: 保存文本或对话历史
  - 简单文本: add_memory(text="用户喜欢Python")
  - 对话历史: add_memory(messages=[{"role": "user", "content": "..."}])

### 检索记忆
- `search_memories`: 语义搜索
  - search_memories(query="编程语言偏好")
  - search_memories(query="...", filters={"AND": [...]})
  
- `get_memories`: 过滤浏览（支持分页）
  - get_memories(filters={"AND": [{"user_id": "..."}]})
  - get_memories(page=1, page_size=10)

### 管理记忆
- `get_memory`: 获取单个记忆（需要memory_id）
- `update_memory`: 更新记忆内容
- `delete_memory`: 删除单个记忆
- `delete_all_memories`: 批量删除记忆

## 过滤器语法

常用过滤器模式：
- 单个用户: {"AND": [{"user_id": "john"}]}
- 时间范围: {"AND": [{"created_at": {"gte": "2024-01-01"}}]}
- 多个条件: {"AND": [{"user_id": "john"}, {"category": "preference"}]}

## 最佳实践

1. **保存时机**: 用户表达偏好、背景、重要信息时
2. **检索时机**: 需要了解用户背景、历史记录时
3. **使用过滤器**: 精确查询时使用filters
4. **分页浏览**: 大量记忆时使用page和page_size
"""
```

---

## 测试用例

### add_memory 测试

```python
# 测试1: 简单文本
result = add_memory(text="用户喜欢Python")
assert result["success"] == True

# 测试2: 对话历史
result = add_memory(
    messages=[
        {"role": "user", "content": "我是后端工程师"},
        {"role": "assistant", "content": "好的"}
    ]
)
assert result["success"] == True
```

### search_memories 测试

```python
# 测试1: 简单搜索
results = search_memories(query="编程语言")
assert len(results) > 0

# 测试2: 带过滤器
results = search_memories(
    query="偏好",
    filters={"AND": [{"category": "preference"}]},
    limit=5
)
assert len(results) <= 5
```

### get_memories 测试

```python
# 测试1: 分页
page1 = get_memories(page=1, page_size=10)
page2 = get_memories(page=2, page_size=10)
assert page1 != page2

# 测试2: 过滤器
results = get_memories(
    filters={"AND": [{"created_at": {"gte": "2024-01-01"}}]}
)
assert all(m["created_at"] >= "2024-01-01" for m in results)
```

---

## 参考资料

- [Mem0 Official MCP Server](https://github.com/mem0ai/mem0-mcp-server)
- [Mem0 API Documentation](https://docs.mem0.ai)
- [Mem0 Python SDK](https://github.com/mem0ai/mem0)

---

**状态**: 设计完成  
**下一步**: 实现新的工具函数  
**预计工期**: 2-3天
