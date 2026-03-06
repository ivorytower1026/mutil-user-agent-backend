# Multi-tenant AI Agent Platform

基于 LangGraph 和 DeepAgents 的多租户 AI Agent 平台，提供沙箱隔离的代码执行环境。

## 技术栈

- **Python 3.13**
- **FastAPI** - Web 服务框架
- **LangGraph 1.0+** - Agent 编排框架
- **DeepAgents 0.4.4+** - Agent 工具库
- **PostgreSQL** - 持久化存储
- **Redis** - 缓存和会话管理
- **Docker** - 沙箱隔离环境
- **Qdrant** - 向量数据库（可选，记忆功能需要）

## 环境要求

- **Python 3.13+**
- **Docker Desktop** (Windows) 或 **Docker Engine** (Linux)
- **PostgreSQL 12+**
- **Redis 6+**
- **uv 包管理器** - [安装指南](https://github.com/astral-sh/uv)

## 快速开始

### Windows 用户

#### 1. 安装依赖
```bash
uv sync
```

#### 2. 配置 Docker 环境

创建数据目录（PowerShell）：
```powershell
New-Item -ItemType Directory -Force -Path "D:\docker_volume\mutil-user-agent\redis\data"
New-Item -ItemType Directory -Force -Path "D:\docker_volume\mutil-user-agent\postgres\data"
New-Item -ItemType Directory -Force -Path "D:\docker_volume\mutil-user-agent\qdrant\data"
```

配置 Docker 环境变量：
```bash
# 复制配置文件
copy .env.docker.windows .env.docker

# ⚠️ 如果需要代理，编辑 .env.docker 文件取消注释并配置：
# HTTP_PROXY=http://127.0.0.1:7890
# HTTPS_PROXY=http://127.0.0.1:7890
```

#### 3. 启动 Docker 容器
```bash
docker-compose --env-file .env.docker up -d
```

#### 4. 配置应用环境
```bash
# 复制配置文件
copy .env.example.windows .env

# 编辑 .env 文件，修改以下必填项：
# ZHIPUAI_API_KEY=你的智谱AI密钥
# DATABASE_URL=postgresql://root:123456@localhost/agent_db
# SECRET_KEY=随机字符串（生产环境必须修改）
```

#### 5. 启动应用
```bash
uv run python main.py
```

应用将在 `http://localhost:8005` 启动（端口可在 `.env` 中修改）。

### Linux/Mac 用户

#### 1. 安装依赖
```bash
uv sync
```

#### 2. 配置 Docker 环境

创建数据目录：
```bash
sudo mkdir -p /var/lib/mutil-user-agent/{redis,postgres,qdrant}/data
sudo chown -R $USER:$USER /var/lib/mutil-user-agent
```

配置 Docker 环境变量：
```bash
# 复制配置文件
cp .env.docker.linux .env.docker

# ⚠️ 如果需要代理，编辑 .env.docker 文件取消注释并配置：
# HTTP_PROXY=http://127.0.0.1:7890
# HTTPS_PROXY=http://127.0.0.1:7890
```

#### 3. 启动 Docker 容器
```bash
docker-compose --env-file .env.docker up -d
```

#### 4. 配置应用环境
```bash
# 复制配置文件
cp .env.example.linux .env

# 编辑 .env 文件，修改以下必填项：
# ZHIPUAI_API_KEY=你的智谱AI密钥
# DATABASE_URL=postgresql://root:123456@localhost/agent_db
# SECRET_KEY=随机字符串（生产环境必须修改）
```

#### 5. 启动应用
```bash
uv run python main.py
```

应用将在 `http://localhost:8005` 启动（端口可在 `.env` 中修改）。

## Docker 代理配置说明

⚠️ **重要提示**：如果 Docker 沙箱需要通过代理访问外网（例如安装 Python 包），请按以下步骤配置：

1. 编辑 `.env.docker` 文件（Windows 用 `.env.docker.windows`，Linux 用 `.env.docker.linux`）
2. 取消注释并配置代理地址：
   ```bash
   HTTP_PROXY=http://127.0.0.1:7890
   HTTPS_PROXY=http://127.0.0.1:7890
   ```
3. 重新构建沙箱镜像：
   ```bash
   docker-compose build --no-cache sandbox-builder
   ```
4. 重启容器：
   ```bash
   docker-compose --env-file .env.docker down
   docker-compose --env-file .env.docker up -d
   ```

## 应用配置说明

### 必需配置项

| 配置项 | 说明 | 示例 |
|--------|------|------|
| `ZHIPUAI_API_KEY` | 智谱AI API 密钥 | `xxxx` |
| `DATABASE_URL` | PostgreSQL 连接字符串 | `postgresql://root:123456@localhost/agent_db` |
| `SECRET_KEY` | JWT 签名密钥 | 随机字符串（生产环境必须修改）|

### 功能开关

📊 **默认功能状态**：

| 功能 | 配置项 | 默认值 | 说明 |
|------|--------|--------|------|
| Langfuse 监控 | `IS_LANGFUSE` | `0` (关闭) | AI 对话监控和追踪 |
| 记忆系统 | `MEMORY_ENABLED` | `0` (关闭) | 长期记忆功能（需要 Qdrant）|

💡 **启用方法**：

**启用 Langfuse 监控**：
```bash
IS_LANGFUSE=1
LANGFUSE_SECRET_KEY=your-secret-key
LANGFUSE_PUBLIC_KEY=your-public-key
LANGFUSE_BASE_URL=http://your-langfuse-server:3000
```

**启用记忆功能**：
```bash
MEMORY_ENABLED=1
MEM0_QDRANT_HOST=localhost
MEM0_QDRANT_PORT=6333
```

### 可选配置项

<details>
<summary>点击展开完整配置列表</summary>

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `PORT` | `8005` | 服务端口 |
| `ZHIPUAI_API_BASE` | `https://open.bigmodel.cn/api/coding/paas/v4` | 智谱AI API 地址 |
| `WORKSPACE_ROOT` | `~/.mutil-user-agent/workspace` | 用户工作空间目录 |
| `SHARED_DIR` | `~/.mutil-user-agent/shared` | 共享资源目录 |
| `SKILL_DIR` | `~/.mutil-user-agent/skills` | 技能目录 |
| `DOCKER_IMAGE` | `mutil-user-agent-sandbox:latest` | 沙箱镜像名称 |
| `DOCKER_CPU_LIMIT` | `1.0` | 容器 CPU 核数限制 |
| `DOCKER_MEMORY_LIMIT` | `2g` | 容器内存限制 |
| `DOCKER_IDLE_TIMEOUT_SECONDS` | `300` | 容器空闲超时时间（秒）|
| `REDIS_URL` | `redis://localhost:6379/0` | Redis 连接地址 |
| `LLM_MODE` | `1` | LLM 模式（1=智谱AI, 2=本地 VLLM）|
| `ACCESS_TOKEN_EXPIRE_HOURS` | `24` | JWT 令牌过期时间（小时）|
| `LOG_LEVEL` | `INFO` | 日志级别 |
| `LOG_TO_CONSOLE` | `0` | 是否输出日志到控制台 |

</details>

## 验证服务

### 检查容器状态
```bash
docker ps
```

应该看到以下容器运行中：
- `redis`
- `postgres`
- `qdrant`（可选，记忆功能需要）
- `sandbox-builder`（构建完成后）

### 测试 API
```bash
# 健康检查
curl http://localhost:8005/

# 用户注册
curl -X POST http://localhost:8005/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username":"test","password":"test123"}'

# 用户登录
curl -X POST http://localhost:8005/api/auth/login \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=test&password=test123"
```

## API 端点

访问 `http://localhost:8005/` 查看完整 API 文档。

### 核心端点

| 方法 | 路径 | 描述 |
|------|------|------|
| POST | `/api/auth/register` | 用户注册 |
| POST | `/api/auth/login` | 用户登录 |
| POST | `/api/sessions` | 创建会话 |
| POST | `/api/chat/{thread_id}` | 发送消息（SSE 流） |
| POST | `/api/resume/{thread_id}` | 恢复中断 |
| * | `/dav/{path}` | WebDAV 文件操作 |
| POST | `/api/files/init-upload` | 分片上传初始化 |
| GET | `/api/admin/skills` | 技能管理（需要管理员权限）|

## Docker 容器管理

```bash
# 查看日志
docker-compose logs -f

# 停止容器
docker-compose down

# 重启容器
docker-compose restart

# 重新构建沙箱镜像
docker-compose build --no-cache sandbox-builder

# 清理所有数据（危险操作）
docker-compose down -v
```

## 故障排查

### 1. 端口冲突
如果默认端口被占用，修改 `.env` 文件中的 `PORT` 配置。

### 2. Docker 容器启动失败
- **Windows**: 检查 Docker Desktop 是否正常运行
- **Linux**: 检查数据目录权限：`ls -la /var/lib/mutil-user-agent`
- 查看日志：`docker-compose logs [服务名]`

### 3. 数据库连接失败
- 确认 PostgreSQL 容器正常运行：`docker ps | grep postgres`
- 检查 `DATABASE_URL` 配置是否正确
- 测试连接：`docker exec -it postgres psql -U root -d agent_db`

### 4. Redis 连接失败
- 确认 Redis 容器正常运行：`docker ps | grep redis`
- 测试连接：`docker exec -it redis redis-cli ping`

### 5. 代理问题
如果沙箱内无法访问外网：
- 确认 `.env.docker` 中的代理配置正确
- 重新构建镜像：`docker-compose build --no-cache sandbox-builder`
- 检查代理服务是否正常工作

### 6. 查看应用日志
```bash
# 实时查看日志
tail -f logs/app.log

# 启用控制台输出（调试用）
LOG_TO_CONSOLE=1 uv run python main.py
```

## 项目结构

```
backend/
├── main.py              # FastAPI 应用入口
├── pyproject.toml       # 项目依赖配置
├── docker-compose.yml   # Docker 编排配置
├── src/                 # 核心业务逻辑
│   ├── config.py        # 配置管理
│   ├── agent_manager.py # Agent 生命周期管理
│   ├── docker_sandbox.py # Docker 沙箱实现
│   └── database.py      # 数据库模型
├── api/                 # API 路由层
│   ├── server.py        # Agent API 路由
│   ├── auth.py          # 认证 API 路由
│   ├── webdav.py        # WebDAV 路由
│   ├── files.py         # 文件上传路由
│   └── admin.py         # 管理员 API 路由
└── docker/              # Docker 相关文件
    └── sandbox/         # 沙箱镜像构建文件
```

详细目录结构和开发规范请参考 [AGENTS.md](./AGENTS.md)。

## 核心特性

### 1. 多租户隔离
- 每个用户拥有独立的工作空间
- 使用 `thread_id` 进行会话隔离
- Docker 容器级别的资源隔离

### 2. Docker 沙箱
- 每个会话独立容器
- 容器按需创建和自动清理
- 支持代码执行和文件操作
- CPU 和内存资源限制

### 3. HITL（人工介入）
- 敏感操作（execute/write_file）可中断
- 用户可以批准或取消操作
- 安全的代码执行环境

### 4. 持久化存储
- PostgreSQL 存储用户数据
- LangGraph checkpoint 存储会话状态
- WebDAV 文件管理

### 5. 可观测性
- Langfuse 集成（可选）
- 统一日志管理
- 请求追踪和监控

## 参考文档

- [AGENTS.md](./AGENTS.md) - 完整开发和部署指南
- [LangGraph 文档](https://langchain-ai.github.io/langgraph/)
- [DeepAgents 文档](https://github.com/langchain-ai/deepagents)
- [FastAPI 文档](https://fastapi.tiangolo.com/)

## 许可证

[添加许可证信息]
