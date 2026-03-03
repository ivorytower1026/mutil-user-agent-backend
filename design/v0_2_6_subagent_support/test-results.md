# DeepAgents 子代理测试结果

## 测试信息

- **测试时间**：2026-03-03 21:34
- **测试文件**：`tests/test_task_tool_simple.py`
- **LLM**：big_llm
- **DeepAgents**：已配置子代理

---

## 测试1：普通工具调用

### 输入
```
计算 5+3
```

### 输出

**Chunk 2** - 工具调用：
```
namespace: ()
tool_name: simple_calc
tool_args: {'expr': '5+3'}
```

**结果**：
- ✅ 总共 6 个 chunks
- ✅ 检测到 1 个工具调用
- ✅ Namespace 为空（主代理）

---

## 测试2：子代理调用

### 输入
```
北京天气如何？
```

### 输出

**Chunk 2** - 主代理调用 task 工具：
```
namespace: ()
stream_mode: updates
tool_name: task
tool_args: {
    'description': '查询北京当前的天气情况，包括温度、天气状况、风力等信息',
    'subagent_type': 'weather_agent'
}
```

**Chunk 4-9** - 子代理内部事件：
```
namespace: ('tools:08478f5b-49db-3622-d864-8826a0431269',)
stream_mode: updates
```

**Chunk 5** - 子代理调用工具：
```
namespace: ('tools:08478f5b-49db-3622-d864-8826a0431269',)
tool_name: get_weather
tool_args: {'city': '北京'}
```

**Chunk 10-12** - 返回主代理：
```
namespace: ()
stream_mode: updates
```

**结果**：
- ✅ 总共 12 个 chunks
- ✅ 检测到 2 个工具调用（task + get_weather）
- ✅ 主代理调用 task 时 namespace = ()
- ✅ 子代理内部事件 namespace = ('tools:ID',)

---

## 关键发现

### 1. Namespace 规律

| 场景 | Namespace | 说明 |
|------|-----------|------|
| 主代理调用普通工具 | `()` | 空元组 |
| 主代理调用 task 工具 | `()` | 空元组 |
| 子代理内部的所有事件 | `('tools:ID',)` | 有 tools: 前缀 |

### 2. Task 工具参数

```python
{
    'description': '任务描述',
    'subagent_type': 'weather_agent'  # 子代理名称
}
```

**注意**：字段名是 `subagent_type`，不是 `name`！

### 3. 识别逻辑

```python
# 步骤1: 在主代理中检测 task 工具
if tool_name == 'task' and not subgraph_path:
    # 这是子代理调用！
    subagent_name = tool_args.get('subagent_type')
    
# 步骤2: 后续的 tools: namespace 事件都属于子代理
if subgraph_path and subgraph_path[0].startswith('tools:'):
    # 这些是子代理内部的事件
    subagent_id = subgraph_path[0].split(':', 1)[1]
```

---

## 实施建议

### 后端改动

1. **修改 RunnerState**：添加子代理跟踪状态
2. **修改 _handle_messages()**：检测 task 工具调用
3. **修改 _handle_updates()**：检测 task 工具调用
4. **修改 SSE 事件格式**：添加 `subagent_name` 字段

### 前端改动

1. **识别子代理事件**：检查 `namespace` 字段
2. **提取子代理信息**：使用 `subagent_id` 和 `subagent_name`
3. **实现折叠UI**：根据 `subagent_id` 分组显示

---

## 验证通过 ✅

- ✅ 检测到 task 工具调用
- ✅ 成功提取子代理名称（subagent_type）
- ✅ Namespace 规律验证正确
- ✅ 子代理 ID 提取正确
- ✅ 主代理和子代理事件区分正确

---

## 测试文件

完整测试代码：`tests/test_task_tool_simple.py`

运行命令：
```bash
uv run python -m tests.test_task_tool_simple
```
