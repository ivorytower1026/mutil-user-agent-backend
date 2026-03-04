# 06. 配置项说明

## 1. 环境变量

### 1.1 新增配置项

```bash
# .env (新增)

# ==================== 端口暴露配置 ====================

# 预览域名 (必须配置泛域名解析)
PREVIEW_DOMAIN=preview.example.com

# Caddy Admin API 地址
CADDY_API_URL=http://localhost:2019

# 用户端口限制
MAX_PORTS_PER_USER=10

# 端口映射 TTL (秒)
PORT_MAPPING_TTL=86400

# ==================== Docker 网络配置 ====================

# Docker 网络名称
DOCKER_NETWORK_NAME=sandbox_network

# Docker PIDs 限制
DOCKER_PIDS_LIMIT=100
```

### 1.2 完整配置示例

```bash
# .env.example (更新)

# 智谱AI配置
ZHIPUAI_API_KEY=your_api_key
ZHIPUAI_API_BASE=https://open.bigmodel.cn/api/paas/v4

# Langfuse配置
IS_LANGFUSE=0
LANGFUSE_SECRET_KEY=
LANGFUSE_PUBLIC_KEY=
LANGFUSE_BASE_URL=

# 工作空间配置
WORKSPACE_ROOT=~/workspaces
SHARED_DIR=~/shared
DOCKER_IMAGE=python:3.13-slim
CONTAINER_WORKSPACE_DIR=/workspace
CONTAINER_SKILLS_DIR=/skills
CONTAINER_SHARED_DIR=/shared

# 数据库配置
DATABASE_URL=postgresql://user:pass@localhost:5432/db

# JWT配置
SECRET_KEY=your_secret_key
ACCESS_TOKEN_EXPIRE_HOURS=24

# 服务端口
PORT=8002

# LLM 端点
OPENAI_API_BASE_8001=http://localhost:8001/v1
OPENAI_API_BASE_8002=http://localhost:8002/v1

# ModelScope
MODELSCOPE_SDK_TOKEN=your_token
MODELSCOPE_URL=https://api-inference.modelscope.cn/v1

# LLM 模式
LLM_MODE=1

# Redis
REDIS_URL=redis://localhost:6379/0

# Skill 配置
SKILL_IMAGES_DIR=D:/docker_volume/mutil-user-agent/skill-images
SKILL_IMAGE_VERSIONS_TO_KEEP=5

# Docker 资源限制
DOCKER_CPU_LIMIT=1.0
DOCKER_MEMORY_LIMIT=2g
DOCKER_IDLE_TIMEOUT_SECONDS=60

# ==================== 新增: 端口暴露配置 ====================

# 预览域名 (泛域名)
PREVIEW_DOMAIN=preview.example.com

# Caddy API
CADDY_API_URL=http://localhost:2019

# 用户端口限制
MAX_PORTS_PER_USER=10

# 端口映射 TTL (24小时)
PORT_MAPPING_TTL=86400

# Docker 网络
DOCKER_NETWORK_NAME=sandbox_network

# Docker PIDs 限制
DOCKER_PIDS_LIMIT=100
```

## 2. Config 类更新

```python
# src/config.py (新增字段)

class Settings(BaseSettings):
    # ... 现有字段 ...
    
    # 端口暴露配置
    PREVIEW_DOMAIN: str = "preview.example.com"
    CADDY_API_URL: str = "http://localhost:2019"
    MAX_PORTS_PER_USER: int = 10
    PORT_MAPPING_TTL: int = 86400  # 24 hours
    
    # Docker 网络配置
    DOCKER_NETWORK_NAME: str = "sandbox_network"
    DOCKER_PIDS_LIMIT: int = 100
    
    # 阻止的端口
    BLOCKED_PORTS: set[int] = {22, 25, 80, 443, 3306, 5432, 6379, 27017}
```

## 3. Caddy 配置

### 3.1 Caddyfile

```caddyfile
# /etc/caddy/Caddyfile

{
    email admin@example.com
    storage file_system /var/lib/caddy/.local/share/caddy
    
    # 启用 Admin API
    admin 0.0.0.0:2019
}

# 泛域名处理
*.preview.example.com {
    tls {
        # 使用 DNS 验证获取泛域名证书
        dns cloudflare {env.CLOUDFLARE_API_TOKEN}
    }
    
    # 动态路由 (通过 API 添加)
    # 初始配置: 返回 404
    respond "Service not found or not running" 404
}

# 可选: 主服务代理
example.com {
    reverse_proxy localhost:8002
}
```

### 3.2 DNS 验证配置

**Cloudflare 示例**:
```bash
# 获取 Cloudflare API Token
# 权限: Zone - DNS - Edit

export CLOUDFLARE_API_TOKEN=your_token
```

**其他 DNS 提供商**:
```caddyfile
# 阿里云 DNS
tls {
    dns alidns {
        access_key_id {env.ALI_ACCESS_KEY_ID}
        access_key_secret {env.ALI_ACCESS_KEY_SECRET}
    }
}

# 腾讯云 DNS
tls {
    dns tencentcloud {
        secret_id {env.TENCENT_SECRET_ID}
        secret_key {env.TENCENT_SECRET_KEY}
    }
}
```

### 3.3 Docker Compose Caddy

```yaml
# docker-compose.yml (添加 Caddy)

services:
  caddy:
    image: caddy:2
    container_name: caddy
    restart: unless-stopped
    ports:
      - "80:80"
      - "443:443"
      - "2019:2019"  # Admin API
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile
      - caddy_data:/data
      - caddy_config:/config
    environment:
      - CLOUDFLARE_API_TOKEN=${CLOUDFLARE_API_TOKEN}
    networks:
      - sandbox_network

volumes:
  caddy_data:
  caddy_config:

networks:
  sandbox_network:
    external: true
```

## 4. DNS 配置

### 4.1 泛域名解析

```
类型: A
名称: *.preview
值: 服务器 IP
TTL: 600

# 或使用 CNAME
类型: CNAME
名称: *.preview
值: your-server.com
```

### 4.2 验证 DNS

```bash
# 验证泛域名解析
dig 8080-user123.preview.example.com
nslookup 8080-user123.preview.example.com
```

## 5. Redis 配置

```bash
# Redis 默认配置即可
REDIS_URL=redis://localhost:6379/0

# 如果使用 Redis 密码
REDIS_URL=redis://:password@localhost:6379/0

# 如果使用 Redis Sentinel
REDIS_URL=redis+sentinel://localhost:26379/mymaster/0
```

## 6. 资源限制配置

### 6.1 Docker 资源限制

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| DOCKER_CPU_LIMIT | 1.0 | CPU 核数 |
| DOCKER_MEMORY_LIMIT | 2g | 内存限制 |
| DOCKER_PIDS_LIMIT | 100 | 进程数限制 |
| DOCKER_IDLE_TIMEOUT_SECONDS | 60 | 空闲超时 (秒) |

### 6.2 用户限制

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| MAX_PORTS_PER_USER | 10 | 每用户最大端口数 |
| PORT_MAPPING_TTL | 86400 | 映射有效期 (秒) |

## 7. 安全配置

### 7.1 端口白名单/黑名单

```python
# src/config.py

# 允许的端口范围
ALLOWED_PORT_RANGE = (1024, 65535)

# 阻止的端口 (系统端口和常用数据库端口)
BLOCKED_PORTS = {
    22,      # SSH
    25,      # SMTP
    80,      # HTTP
    443,     # HTTPS
    3306,    # MySQL
    5432,    # PostgreSQL
    6379,    # Redis
    27017,   # MongoDB
}
```

### 7.2 容器安全配置

```python
# Docker 安全选项
security_opt = [
    "no-new-privileges:true",  # 禁止提权
]

# 能力控制
cap_drop = ["ALL"]              # 丢弃所有能力
cap_add = ["NET_BIND_SERVICE"]  # 仅添加必要能力
```

## 8. 监控配置

### 8.1 Prometheus 指标

```python
# 可选: 添加 Prometheus 指标

from prometheus_client import Counter, Gauge

port_mappings_total = Gauge(
    'port_mappings_total',
    'Total number of active port mappings'
)

port_registrations = Counter(
    'port_registrations_total',
    'Total number of port registrations'
)
```

### 8.2 日志配置

```python
# 日志格式
LOG_FORMAT = "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s"

# 端口映射日志
# [PortMapping] Registered: 8080-user123.preview.example.com -> 172.28.0.5:8080
# [PortMapping] Unregistered: 8080-user123.preview.example.com
# [PortMapping] Cleaned up 5 inactive mappings
```
