# Multi-tenant AI Agent Platform

## MVP实现

本项目实现了多租户AI Agent平台的MVP版本，基于以下技术栈：

- **Python 3.13**
- **FastAPI**: Web服务框架
- **LangGraph 1.0+**: LangGraph框架
- **DeepAgents 0.3.12+**: Agent框架
- **Docker**: 容器化隔离

## 目录结构

```
backend/
├── main.py                 # FastAPI应用入口
├── pyproject.toml          # 项目依赖
├── .env.example            # 环境变量模板
├── src/
│   ├── config.py          # LLM和Docker配置
│   ├── docker_sandbox.py  # Docker沙箱后端
│   └── agent_manager.py   # Agent管理器
├── api/
│   ├── server.py          # FastAPI路由
│   └── models.py          # Pydantic模型
└── tests/
    └── test_mvp.py       # MVP测试脚本
```

## 快速开始

### 1. 配置环境变量

```bash
cp .env.example .env
```

编辑`.env`文件，设置你的智谱AI API密钥：

```bash
ZHIPUAI_API_KEY=your-api-key-here
WORKSPACE_ROOT=./workspaces
SHARED_DIR=./shared
```

### 2. 启动服务

```bash
uv run python main.py
```

服务将在 `http://localhost:8000` 启动。

### 3. 运行测试

```bash
uv run python tests/test_mvp.py
```

## API端点

| 方法 | 路径 | 描述 |
|------|--------|------|
| POST | `/api/sessions` | 创建新会话，返回thread_id |
| POST | `/api/chat/{thread_id}` | 发送消息，返回SSE流 |
| POST | `/api/resume/{thread_id}` | 恢复HITL中断（continue/cancel） |

### 创建会话

```bash
curl -X POST http://localhost:8000/api/sessions
# 返回: {"thread_id": "user-xxx"}
```

### 发送消息（SSE）

```bash
curl -N -X POST http://localhost:8000/api/chat/user-xxx \
  -H "Content-Type: application/json" \
  -d '{"message": "创建一个hello.py文件"}'
```

### 恢复中断

```bash
curl -X POST http://localhost:8000/api/resume/user-xxx \
  -H "Content-Type: application/json" \
  -d '{"action": "continue"}'
```

## 核心特性

### 1. 多线程隔离
- 使用LangGraph的`thread_id`进行隔离
- 每个用户可以有多个独立会话

### 2. Docker沙箱隔离
- 每个会话有独立的Docker容器
- 容器按需创建和销毁
- 工作空间独立挂载

### 3. HITL（人工介入）
- 敏感操作（execute/write_file）可中断
- 用户可以批准或取消操作

### 4. 跨平台支持
- 支持Windows和Linux
- 自动处理路径分隔符
- 环境变量配置挂载路径

## 环境变量

| 变量 | 默认值 | 说明 |
|-------|---------|------|
| `ZHIPUAI_API_KEY` | (必填) | 智谱AI API密钥 |
| `ZHIPUAI_API_BASE` | https://open.bigmodel.cn/api/paas/v4/ | API地址 |
| `WORKSPACE_ROOT` | ./workspaces | 工作空间根目录 |
| `SHARED_DIR` | ./shared | 共享目录 |
| `DOCKER_IMAGE` | python:3.13-slim | Docker镜像 |
| `CONTAINER_WORKSPACE_DIR` | /workspace | 容器内工作目录 |
| `CONTAINER_SHARED_DIR` | /shared | 容器内共享目录 |

## MVP范围

### ✅ 已实现
- 单用户多会话
- Docker沙箱隔离
- 内存存储（MemoryCheckpointer）
- HITL中断机制
- FastAPI + SSE
- 跨平台路径处理

### ❌ 未实现（后续迭代）
- 用户认证
- PostgreSQL持久化
- 容器池管理
- 前端界面
- 自定义skills
- 监控和日志

## 开发指南

### 安装依赖

```bash
uv sync
```

### 运行服务

```bash
uv run python main.py
```

### 运行测试

```bash
uv run python tests/test_mvp.py
```

## 参考文档

- [设计文档](./design/mvp/plan.md)
- [变更日志](./design/mvp/CHANGELOG.md)
- [deepagents文档](https://github.com/langchain-ai/deepagents)
- [LangGraph文档](https://langchain-ai.github.io/langgraph/)
