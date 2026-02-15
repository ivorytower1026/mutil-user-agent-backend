# v0.1.7 对话文件上传

> 在对话窗口直接上传文件，Agent 可读取并处理文件

---

## 一、现象（实际）

### 1.1 当前能力

| 功能 | 状态 | 说明 |
|------|------|------|
| 分块上传 API | ✅ 已有 | `/api/files/init-upload`, `/upload-chunk`, `/complete-upload` |
| WebDAV 文件管理 | ✅ 已有 | `/dav/{path}` |
| 对话消息 | ⚠️ 仅文本 | `ChatRequest.message: str` |
| 文件与对话关联 | ❌ 缺失 | Agent 不知道用户上传了什么文件 |

### 1.2 现有问题

| # | 问题 | 影响 |
|---|------|------|
| 1 | **对话无法携带文件** | 用户需要先在文件管理上传，再在对话中描述路径 |
| 2 | **操作割裂** | 上传和对话是两个独立流程，体验不连贯 |
| 3 | **Agent 无感知** | 即使文件存在，Agent 也不知道用户意图 |

### 1.3 相关代码位置

| 文件 | 说明 |
|------|------|
| `api/models.py:6-7` | `ChatRequest` 仅支持 `message: str` |
| `api/files.py` | 现有分块上传 API |
| `src/chunk_upload.py` | 分块上传管理器 |
| `src/agent_manager.py:73` | `stream_chat` 仅处理文本消息 |

---

## 二、意图（期望）

### 2.1 目标功能

```
用户在对话窗口选择文件 → 上传到 /workspace/uploads/ → 发送消息时携带文件信息
                              ↓
                     Agent 收到："用户上传了以下文件：xxx，用户消息：yyy"
```

### 2.2 期望效果

| # | 期望 | 实现方式 |
|---|------|----------|
| 1 | **对话中直接上传** | 新增上传 API |
| 2 | **消息携带文件** | `ChatRequest.files: list[str]` |
| 3 | **自动注入提示** | Agent 收到文件路径信息（SystemMessage） |
| 4 | **统一存储位置** | `/workspace/uploads/` 临时目录 |

### 2.3 限制条件

| 限制项 | 限制值 | 超限处理 |
|--------|--------|----------|
| 单次上传文件数 | **最多 5 个** | 返回 400 错误 |
| 单文件大小 | **最大 50MB** | 返回 413 错误，提示使用 WebDAV |
| 超大文件 | > 50MB | 推荐使用 WebDAV 上传到工作目录 |

> **说明**：50MB 以内单次 HTTP 上传完全可行，无需分块。分块上传主要用于超大文件（几百MB+）和断点续传场景。对话场景的文件通常较小（代码、文档、数据文件等），50MB 足够覆盖。

### 2.4 文件存储结构

```
{WORKSPACE_ROOT}/{user_id}/uploads/
├── 20260215_143022_a1b2c3.pdf
├── 20260215_143022_d4e5f6.csv
└── 20260215_150111_x9y8z7.png
```

- 文件名格式：`{timestamp}_{uuid8}.{ext}`
- 容器内路径：`/workspace/uploads/xxx.pdf`

### 2.5 API 设计

#### 新增：上传接口

```
POST /api/files/upload-simple
Content-Type: multipart/form-data

file: <binary>

Response (成功):
{
  "success": true,
  "path": "/workspace/uploads/20260215_143022_a1b2c3.pdf",
  "filename": "report.pdf",
  "size": 1234567
}

Response (超过 50MB):
{
  "detail": "文件超过 50MB，请使用 WebDAV 上传到工作目录"
}
```

#### 限制说明

| 限制 | 错误码 | 错误信息 |
|------|--------|----------|
| 单文件 > 50MB | 413 | 文件超过 50MB，请使用 WebDAV 上传到工作目录 |
| 文件数 > 5 | 400 | 单次最多上传 5 个文件，请分批上传或使用 WebDAV |

#### 修改：Chat 请求

```python
class ChatRequest(BaseModel):
    message: str
    files: list[str] | None = None  # 容器内文件路径列表
```

#### 消息格式详解（方案A：SystemMessage + 历史过滤）

> 核心思路：文件信息注入到 SystemMessage，用户历史记录中过滤掉，实现无感知

**1. 前端发送的 HTTP 请求**

```http
POST /api/chat/user123-thread-abc
Authorization: Bearer <token>
Content-Type: application/json

{
  "message": "帮我分析这些文件",
  "files": [
    "/workspace/uploads/20260215_143022_a1b2c3.pdf",
    "/workspace/uploads/20260215_143022_d4e5f6.csv"
  ]
}
```

**2. 后端构建的消息列表**

```python
# src/agent_manager.py
from langchain_core.messages import HumanMessage, SystemMessage

# 有文件时：[SystemMessage, HumanMessage]
messages = [
    SystemMessage(content="当前对话中用户已上传的文件：\n- /workspace/uploads/...\n- /workspace/uploads/..."),
    HumanMessage(content="帮我分析这些文件")  # 用户原始消息，无注入
]

# 无文件时：[HumanMessage]
messages = [
    HumanMessage(content="你好")
]
```

**3. 传给 LLM 的完整 messages 结构**

```python
# LangGraph state 中的 messages（有文件时）
[
    SystemMessage(content="当前对话中用户已上传的文件：\n- /workspace/uploads/xxx.pdf"),
    HumanMessage(content="帮我分析这些文件"),
    AIMessage(content="好的，我来读取这个文件..."),
    ToolMessage(...)
]
```

**4. 历史接口返回（过滤后）**

```python
# GET /api/history/{thread_id} 返回
{
    "thread_id": "user123-thread-abc",
    "messages": [
        {"role": "user", "content": "帮我分析这些文件"},      # 干净的用户消息
        {"role": "assistant", "content": "好的，我来读取..."}  # 不含文件 SystemMessage
    ]
}
```

**5. 无文件时的兼容格式**

```http
POST /api/chat/user123-thread-abc

{
  "message": "你好"
}
```

```python
# files 为 None 或空数组时，不插入 SystemMessage
messages = [HumanMessage(content="你好")]
```

**6. 仅上传文件无消息**

```http
POST /api/chat/user123-thread-abc

{
  "message": "",
  "files": ["/workspace/uploads/xxx.pdf"]
}
```

```python
# message 为空也正常处理
messages = [
    SystemMessage(content="当前对话中用户已上传的文件：\n- /workspace/uploads/xxx.pdf"),
    HumanMessage(content="")  # 空消息
]
```

---

## 三、情境（环境约束）

### 3.1 技术栈约束

| 约束 | 说明 |
|------|------|
| Python 3.13 | 使用现代语法 |
| FastAPI | 表单上传使用 `UploadFile` |
| Docker Sandbox | 文件需写入用户工作目录 |
| 单文件限制 | 50MB 以内 |
| 单次文件数 | 最多 5 个 |

### 3.2 现有架构约束

| 约束 | 影响 |
|------|------|
| **用户工作目录** `{WORKSPACE_ROOT}/{user_id}/` | 上传目标目录 |
| **容器挂载** `/workspace` → 用户目录 | Agent 可直接访问 |
| **JWT 认证** | user_id 从 token 获取 |
| **WebDAV** | 超大文件 (>50MB) 使用 WebDAV 上传 |

### 3.3 前端对接要求

| 场景 | 处理方式 |
|------|----------|
| 文件 ≤ 50MB 且 ≤ 5 个 | 调用 `/upload-simple` |
| 文件 > 50MB | 提示用户使用 WebDAV 上传到工作目录 |
| 文件 > 5 个 | 提示用户分批上传或使用 WebDAV |
| 发送消息 | 携带 `files` 字段 |

---

## 四、边界（明确不做）

### 4.1 本次迭代不做

| # | 不做 | 原因 |
|---|------|------|
| 1 | **不做图片/视频预览** | 前端自行实现 |
| 2 | **不做文件类型校验** | 允许任意类型 |
| 3 | **不做 Agent 读取工具** | 用户后续自行添加 |
| 4 | **不做文件过期清理** | 后续迭代考虑 |
| 5 | **不改分块上传** | 保持现有逻辑 |

### 4.2 范围外场景

| 场景 | 说明 |
|------|------|
| 断点续传 | 使用现有分块上传 |
| 文件去重 | 不处理 |
| 并发上传限制 | 不处理 |

---

## 五、方案选择

### 5.1 上传方式对比

| 方案 | 优点 | 缺点 | 推荐 |
|------|------|------|------|
| A. 仅分块上传 | 大文件支持好 | 小文件流程复杂 | |
| B. 仅简单上传 | 简单直接 | 大文件超时 | |
| **C. 自动选择** | 兼顾体验与能力 | 需要两套 API | ✓ |

### 5.2 选择方案C

**限制逻辑**：
- 文件 ≤ 50MB 且 ≤ 5 个：`POST /upload-simple`
- 文件 > 50MB：返回 413，提示使用 WebDAV
- 文件 > 5 个：返回 400，提示分批上传或使用 WebDAV

### 5.3 消息注入方案对比（业界做法）

| 方案 | 格式示例 | 优点 | 缺点 |
|------|----------|------|------|
| **结构化多模态** (OpenAI/智谱 GLM-4.5V) | `content: [{type:"file_url"}, {type:"text"}]` | 标准格式，模型直接理解文件 | 需要特定模型+公网URL |
| **文本注入 HumanMessage** | `"用户上传了：/path/to/file\n消息：xxx"` | 简单直接 | 污染用户历史，用户困惑 |
| **SystemMessage + 过滤** (本方案) | `[SystemMessage(文件), HumanMessage(消息)]` | 用户无感知，历史干净 | 需修改历史接口 |
| **Base64 内嵌** | `content: [{type:"image", data:"base64..."}]` | 无需公网 URL | 仅限图片，大文件不可行 |

### 5.4 选择 SystemMessage + 过滤 的原因

| 因素 | 说明 |
|------|------|
| **模型限制** | 当前使用 GLM-4（非 GLM-4.5V），不支持 `file_url` 多模态 |
| **文件位置** | 本地文件，无公网 URL |
| **文件类型** | 用户可能上传代码、CSV、Excel 等任意类型，非多模态支持范围 |
| **Agent 能力** | agent 有执行命令能力，可根据路径调用工具读取 |
| **用户体验** | 历史记录干净，用户无感知文件信息注入 |

### 5.5 消息注入位置：SystemMessage

采用 **SystemMessage + 历史过滤** 方案：

```python
# 传给 LLM 的消息列表
messages = [
    SystemMessage(content="当前对话中用户已上传的文件：\n- /workspace/uploads/xxx.csv"),
    HumanMessage(content="帮我分析这些数据")  # 用户原始消息，干净
]
```

**历史接口过滤逻辑**：
```python
# 跳过以 "当前对话中用户已上传的文件：" 开头的 SystemMessage
if msg_type == "system" and content.startswith("当前对话中用户已上传的文件："):
    continue  # 不加入历史
```

**效果**：
- ✅ Agent 能看到文件信息，正常处理
- ✅ 用户历史记录干净，看不到文件信息注入
- ✅ 无需前端任何改动

---

## 六、风险评估

### 6.1 大文件上传超时 (低风险)

**场景**：用户上传 > 50MB 文件

**缓解**：
- API 层限制 50MB
- 返回 413 错误，提示使用 WebDAV 上传到工作目录

### 6.2 文件数量超限 (低风险)

**场景**：用户一次上传 > 5 个文件

**缓解**：
- API 层限制 5 个文件
- 返回 400 错误，提示分批上传或使用 WebDAV

### 6.3 文件名冲突 (低风险)

**场景**：用户快速上传同名文件

**缓解**：
- 使用时间戳 + UUID 命名
- 保留原始文件名在响应中

### 6.3 磁盘空间 (中风险)

**场景**：大量上传占用磁盘

**缓解**：
- 后续迭代增加清理机制
- 监控磁盘使用

---

## 七、文件清单

| 文件 | 说明 |
|------|------|
| [README.md](./README.md) | 本文档 (四件套分析) |
| [实现计划.md](./实现计划.md) | 详细代码修改 |
| [测试用例.md](./测试用例.md) | 测试验证 |

---

## 八、实施顺序

1. 修改 `api/models.py` - ChatRequest 增加 files 字段
2. 修改 `api/files.py` - 新增 upload-simple 端点
3. 修改 `src/agent_manager.py` - stream_chat 处理文件注入
4. 编写测试用例
5. 更新版本号
