# Docker Compose 一键部署方案

> 版本: v0.2.4  
> 日期: 2026-03-02  
> 作者: AI Agent

## 📋 概述

本方案提供一个完整的 Docker Compose 配置，用于一键搭建项目所需的所有基础设施容器和自定义沙箱镜像。

### 核心组件

1. **Redis** - 缓存和会话管理
2. **PostgreSQL** - 持久化数据存储
3. **Python Sandbox** - 自定义沙箱镜像（基于 python:3.13-slim）

---

## 🎯 设计目标

- ✅ 一键启动所有依赖服务
- ✅ 从 `.env.docker` 文件读取挂载路径配置
- ✅ 支持代理配置（可选）
- ✅ 沙箱镜像预装基础工具（git, curl, vim）
- ✅ 统一的配置管理
- ✅ 易于维护和扩展

---

## 📁 文件结构

```
backend/
├── docker/
│   ├── sandbox/
│   │   └── Dockerfile          # 沙箱镜像构建文件
│   └── README.md                # Docker 使用说明
├── docker-compose.yml           # 容器编排文件
├── .env.docker                  # Docker 专用环境变量
├── .env                         # 应用环境变量（需更新）
└── .env.example                 # 环境变量示例（需更新）
```

---

## 📄 文件详细说明

### 1. `docker/sandbox/Dockerfile`

**用途**: 构建自定义沙箱镜像

**基础镜像**: `python:3.13-slim`

**预装工具**:
- `git` - 版本控制
- `curl` - HTTP 客户端
- `vim` - 文本编辑器

**代理配置**: 通过构建参数传入（可选）

**关键特性**:
- 从 `.env.docker` 读取代理配置
- 最小化镜像体积（清理 apt 缓存）
- 设置默认工作目录 `/workspace`

```dockerfile
FROM python:3.13-slim

# 构建参数：代理配置
ARG HTTP_PROXY
ARG HTTPS_PROXY

# 设置代理环境变量
ENV HTTP_PROXY=${HTTP_PROXY} \
    HTTPS_PROXY=${HTTPS_PROXY} \
    http_proxy=${HTTP_PROXY} \
    https_proxy=${HTTPS_PROXY}

# 安装基础命令
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    vim \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# 创建工作目录
WORKDIR /workspace

# 默认命令
CMD ["/bin/bash"]
```

---

### 2. `docker-compose.yml`

**用途**: 容器编排配置

**服务列表**:

#### 2.1 Redis 服务
- **镜像**: `redis:latest`
- **端口**: `6379:6379`
- **无密码认证**（仅本地开发）
- **挂载**:
  - 数据目录: `${REDIS_DATA_DIR}:/data`
  - 配置文件: `${REDIS_CONF_DIR}:/usr/local/etc/redis/redis.conf`

#### 2.2 PostgreSQL 服务
- **镜像**: `postgres:latest`
- **端口**: `5432:5432`
- **默认配置**:
  - 用户: `root`
  - 密码: `123456`
  - 数据库: `agent_db`
- **挂载**:
  - 数据目录: `${POSTGRES_DATA_DIR}:/var/lib/postgresql`

#### 2.3 Sandbox Builder 服务
- **构建上下文**: `./docker/sandbox`
- **输出镜像**: `python-sandbox:latest`
- **构建参数**: 从 `.env.docker` 读取代理配置

```yaml
version: '3.8'

services:
  redis:
    image: redis:latest
    container_name: redis
    restart: always
    ports:
      - "6379:6379"
    volumes:
      - ${REDIS_DATA_DIR}:/data
      - ${REDIS_CONF_DIR}:/usr/local/etc/redis/redis.conf
    command: ["redis-server", "/usr/local/etc/redis/redis.conf"]

  postgres:
    image: postgres:latest
    container_name: postgres
    restart: always
    ports:
      - "5432:5432"
    volumes:
      - ${POSTGRES_DATA_DIR}:/var/lib/postgresql
    environment:
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_DB: ${POSTGRES_DB}

  sandbox-builder:
    build:
      context: ./docker/sandbox
      dockerfile: Dockerfile
      args:
        HTTP_PROXY: ${HTTP_PROXY:-}
        HTTPS_PROXY: ${HTTPS_PROXY:-}
    image: python-sandbox:latest
```

---

### 3. `.env.docker`

**用途**: Docker Compose 专用环境变量

**配置项**:

```bash
# 挂载路径配置
REDIS_DATA_DIR=D:\docker_volume\redis\data
REDIS_CONF_DIR=D:\docker_volume\redis\redis.conf
POSTGRES_DATA_DIR=D:\docker_volume\postgres\data

# 代理配置（可选，留空则不使用代理）
HTTP_PROXY=
HTTPS_PROXY=

# PostgreSQL 配置
POSTGRES_PASSWORD=123456
POSTGRES_USER=root
POSTGRES_DB=agent_db
```

**说明**:
- 所有挂载路径可自定义
- 代理配置为空时不使用代理
- PostgreSQL 配置应与 `.env` 中的 `DATABASE_URL` 保持一致

---

### 4. `docker/README.md`

**用途**: Docker 使用说明文档

**内容包括**:
- 环境要求
- 快速开始
- 详细配置说明
- 常见问题排查

---

## 🔧 需要修改的现有文件

### 4.1 `backend/.env`

需要更新以下配置项：

```diff
- DOCKER_IMAGE=python:3.13-slim
+ DOCKER_IMAGE=python-sandbox:latest
```

### 4.2 `backend/.env.example`

在文件末尾添加 Docker 相关配置说明：

```bash
# Docker 配置（使用 docker-compose 时）
# DOCKER_IMAGE=python-sandbox:latest
```

---

## 🚀 使用方式

### 前置条件

1. 安装 Docker Desktop (Windows) 或 Docker + Docker Compose (Linux)
2. 确保 Docker 服务正在运行

### 步骤 1: 创建挂载目录

Windows PowerShell:
```powershell
# 创建 Redis 目录
New-Item -ItemType Directory -Force -Path "D:\docker_volume\redis\data"
New-Item -ItemType Directory -Force -Path "D:\docker_volume\redis"

# 创建 PostgreSQL 目录
New-Item -ItemType Directory -Force -Path "D:\docker_volume\postgres\data"

# 创建 Redis 配置文件（如果不存在）
if (-not (Test-Path "D:\docker_volume\redis\redis.conf")) {
    New-Item -ItemType File -Path "D:\docker_volume\redis\redis.conf"
}
```

Linux/Mac:
```bash
# 创建所有目录
mkdir -p ~/.mutil-user-agent/redis/data
mkdir -p ~/.mutil-user-agent/postgres/data

# 创建 Redis 配置文件
touch ~/.mutil-user-agent/redis/redis.conf
```

### 步骤 2: 配置环境变量

1. 复制 `.env.docker` 并根据需要修改：
   ```bash
   # Windows 用户修改路径为本地路径
   REDIS_DATA_DIR=D:\docker_volume\redis\data
   REDIS_CONF_DIR=D:\docker_volume\redis\redis.conf
   POSTGRES_DATA_DIR=D:\docker_volume\postgres\data
   ```

2. 如需使用代理，填写代理地址：
   ```bash
   HTTP_PROXY=http://your-proxy-server:port
   HTTPS_PROXY=http://your-proxy-server:port
   ```

### 步骤 3: 启动所有容器

```bash
# 在 backend/ 目录下执行
docker-compose --env-file .env.docker up -d
```

**参数说明**:
- `--env-file .env.docker`: 指定环境变量文件
- `up`: 启动容器
- `-d`: 后台运行

### 步骤 4: 验证容器状态

```bash
# 查看运行中的容器
docker ps

# 预期输出应包含三个容器：
# - redis
# - postgres
# - python-sandbox:latest (镜像已构建)
```

### 步骤 5: 验证服务连接

```bash
# 测试 Redis 连接
docker exec -it redis redis-cli ping
# 预期输出: PONG

# 测试 PostgreSQL 连接
docker exec -it postgres psql -U root -d agent_db -c "SELECT version();"
# 预期输出: PostgreSQL 版本信息
```

### 步骤 6: 更新应用配置

更新 `backend/.env` 文件：
```bash
DOCKER_IMAGE=python-sandbox:latest
DATABASE_URL="postgresql://root:123456@postgres/agent_db"
REDIS_URL="redis://redis:6379/0"
```

### 步骤 7: 重启应用

```bash
# 停止应用（如果正在运行）
# Ctrl+C

# 重新启动应用
uv run python main.py
```

---

## 🛠️ 常用操作命令

### 查看日志

```bash
# 查看所有服务日志
docker-compose logs

# 查看特定服务日志
docker-compose logs redis
docker-compose logs postgres

# 实时跟踪日志
docker-compose logs -f
```

### 停止和重启

```bash
# 停止所有容器
docker-compose stop

# 重启所有容器
docker-compose restart

# 停止并删除容器（保留数据）
docker-compose down

# 停止并删除容器和数据卷（谨慎使用）
docker-compose down -v
```

### 重新构建沙箱镜像

```bash
# 重新构建沙箱镜像
docker-compose build sandbox-builder

# 或强制重新构建
docker-compose build --no-cache sandbox-builder
```

### 进入容器调试

```bash
# 进入 Redis 容器
docker exec -it redis /bin/bash

# 进入 PostgreSQL 容器
docker exec -it postgres /bin/bash

# 连接 PostgreSQL 数据库
docker exec -it postgres psql -U root -d agent_db
```

---

## 🔍 故障排查

### 问题 1: 端口被占用

**症状**: 启动时报错 `port is already allocated`

**解决方案**:
1. 检查端口占用:
   ```bash
   # Windows
   netstat -ano | findstr :6379
   netstat -ano | findstr :5432
   
   # Linux/Mac
   lsof -i :6379
   lsof -i :5432
   ```

2. 修改 `docker-compose.yml` 中的端口映射:
   ```yaml
   ports:
     - "6380:6379"  # 改为其他端口
   ```

### 问题 2: 挂载路径不存在

**症状**: 启动时报错 `volume not found`

**解决方案**:
1. 确认 `.env.docker` 中的路径是否正确
2. 确认路径对应的目录已创建
3. Windows 用户注意路径分隔符（使用 `\` 或 `/` 均可）

### 问题 3: Redis 配置文件不存在

**症状**: Redis 容器启动失败

**解决方案**:
```bash
# 创建空的 Redis 配置文件
echo "" > D:\docker_volume\redis\redis.conf

# 或使用默认配置
docker run --rm redis:latest cat /usr/local/etc/redis/redis.conf > D:\docker_volume\redis\redis.conf
```

### 问题 4: PostgreSQL 初始化失败

**症状**: 数据库连接失败

**解决方案**:
1. 检查数据目录权限
2. 清空数据目录重新初始化:
   ```bash
   # 停止容器
   docker-compose down
   
   # 清空数据目录（会丢失数据）
   rm -rf D:\docker_volume\postgres\data\*
   
   # 重新启动
   docker-compose up -d
   ```

### 问题 5: 沙箱镜像构建失败

**症状**: 构建过程中下载包超时

**解决方案**:
1. 检查代理配置是否正确
2. 使用国内镜像源（修改 Dockerfile）:
   ```dockerfile
   RUN sed -i 's/deb.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list
   ```

---

## 📊 配置对比

### 原始配置 vs Docker Compose 配置

| 配置项 | 原始配置 | Docker Compose 配置 |
|--------|----------|---------------------|
| Docker 镜像 | `python:3.13-slim` | `python-sandbox:latest` |
| 数据库连接 | `localhost` | `postgres` (服务名) |
| Redis 连接 | `localhost` | `redis` (服务名) |
| 镜像工具 | 无 | git, curl, vim |
| 代理配置 | 无 | 支持从 .env 读取 |
| 部署方式 | 手动安装 | 一键启动 |

---

## 🔐 安全建议

### 生产环境注意事项

1. **Redis 密码保护**:
   ```bash
   # 在 redis.conf 中添加
   requirepass your-strong-password
   ```
   
   更新 `.env`:
   ```bash
   REDIS_URL="redis://:your-strong-password@redis:6379/0"
   ```

2. **PostgreSQL 强密码**:
   ```bash
   POSTGRES_PASSWORD=your-strong-password
   ```

3. **网络隔离**:
   - 不暴露端口到宿主机（移除 `ports` 配置）
   - 使用 Docker 内部网络

4. **定期备份**:
   ```bash
   # PostgreSQL 备份
   docker exec postgres pg_dump -U root agent_db > backup.sql
   
   # Redis 备份
   docker exec redis redis-cli BGSAVE
   ```

---

## 📝 版本历史

| 版本 | 日期 | 变更内容 |
|------|------|----------|
| v0.2.4 | 2026-03-02 | 初始版本：Docker Compose 一键部署方案 |

---

## 🎓 参考资料

- [Docker Compose 官方文档](https://docs.docker.com/compose/)
- [Redis 官方文档](https://redis.io/documentation)
- [PostgreSQL 官方文档](https://www.postgresql.org/docs/)
- [Python Docker 官方镜像](https://hub.docker.com/_/python)

---

## ✅ 实施检查清单

- [ ] 创建 `docker/sandbox/Dockerfile`
- [ ] 创建 `docker-compose.yml`
- [ ] 创建 `.env.docker`
- [ ] 创建 `docker/README.md`
- [ ] 更新 `backend/.env`
- [ ] 更新 `backend/.env.example`

---

## 💡 扩展建议

### 未来可能的增强

1. **添加 Nginx 反向代理**
2. **添加监控服务（Prometheus + Grafana）**
3. **添加日志收集（ELK Stack）**
4. **添加自动备份服务**
5. **支持多环境配置（dev/staging/prod）**

---

**文档结束**
