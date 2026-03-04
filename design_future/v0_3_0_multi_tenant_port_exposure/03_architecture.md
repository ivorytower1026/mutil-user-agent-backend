# 03. 系统架构设计

## 1. 整体架构

```
┌─────────────────────────────────────────────────────────────────────────┐
│                              系统架构                                    │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│    Internet                                                             │
│        │                                                                │
│        ▼                                                                │
│    ┌─────────────────────────────────────────┐                         │
│    │           DNS 解析                       │                         │
│    │   *.preview.example.com → Server IP     │                         │
│    └───────────────────┬─────────────────────┘                         │
│                          │                                              │
│                          ▼                                              │
│    ┌─────────────────────────────────────────┐                         │
│    │              Caddy                       │                         │
│    │    - 自动 HTTPS (Let's Encrypt)          │                         │
│    │    - 泛域名证书                           │                         │
│    │    - 反向代理                             │                         │
│    │    - 动态路由 (API)                       │                         │
│    └───────────────────┬─────────────────────┘                         │
│                          │                                              │
│                          ▼                                              │
│    ┌─────────────────────────────────────────┐                         │
│    │         Port Mapping Service             │                         │
│    │    - 端口映射管理                         │                         │
│    │    - 自动检测                             │                         │
│    │    - Caddy 配置同步                       │                         │
│    └───────────────────┬─────────────────────┘                         │
│                          │                                              │
│            ┌─────────────┼─────────────┐                               │
│            ▼             ▼             ▼                               │
│    ┌─────────────┐ ┌─────────────┐ ┌─────────────┐                     │
│    │   Redis     │ │  PostgreSQL │ │   Docker    │                     │
│    │  (映射表)    │ │  (持久化)    │ │  (容器池)    │                     │
│    └─────────────┘ └─────────────┘ └─────────────┘                     │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

## 2. 组件详解

### 2.1 Caddy (反向代理层)

**职责**：
- 处理 HTTPS 请求
- 根据子域名路由到对应容器
- 自动证书管理

**配置结构**：
```caddyfile
# /etc/caddy/Caddyfile

{
    email admin@example.com
    storage file_system /var/lib/caddy/.local/share/caddy
}

# 动态路由通过 API 管理
# 初始配置只处理通配符

*.preview.example.com {
    tls {
        dns cloudflare {env.CLOUDFLARE_API_TOKEN}
    }
    
    # 动态路由匹配
    @port_user match {
        expression {host} matches `^(\d+)-([a-f0-9-]+)\.preview\.example\.com$`
    }
    
    handle @port_user {
        # 调用端口映射服务获取目标
        reverse_proxy localhost:18080 {
            header_up X-Preview-Host {host}
        }
    }
    
    # 未匹配的请求
    handle {
        respond "Service not found" 404
    }
}
```

**动态路由 API**：
```python
# Caddy Admin API
POST /config/apps/http/servers/srv0/routes
{
    "@id": "8080-user123.preview.example.com",
    "match": [{"host": ["8080-user123.preview.example.com"]}],
    "handle": [{
        "handler": "reverse_proxy",
        "upstreams": [{"dial": "172.17.0.5:8080"}]
    }]
}
```

### 2.2 Port Mapping Service

**职责**：
- 管理端口映射关系
- 自动检测容器内监听端口
- 同步 Caddy 配置
- 清理过期映射

**数据流**：
```
┌─────────────────────────────────────────────────────────────┐
│                    Port Mapping Flow                        │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  1. 用户在容器内启动服务                                     │
│     └──► python -m http.server 8080                        │
│                                                             │
│  2. 自动检测或手动注册                                       │
│     └──► detect_listening_ports()                          │
│     └──► register_port(user_id, thread_id, 8080)           │
│                                                             │
│  3. 更新 Redis 映射表                                        │
│     └──► port_map:{user_id}:{thread_id}:8080 = {...}       │
│                                                             │
│  4. 同步 Caddy 配置                                          │
│     └──► caddy.add_route(host, container_ip, port)         │
│                                                             │
│  5. 用户访问 URL                                             │
│     └──► https://8080-user123.preview.example.com          │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 2.3 Docker 网络架构

```
┌─────────────────────────────────────────────────────────────┐
│                    Docker Network                           │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              sandbox_network (Bridge)               │   │
│  │                                                     │   │
│  │  ┌───────────┐  ┌───────────┐  ┌───────────┐      │   │
│  │  │ Container │  │ Container │  │ Container │      │   │
│  │  │  User A   │  │  User B   │  │  User C   │      │   │
│  │  │ Thread 1  │  │ Thread 1  │  │ Thread 1  │      │   │
│  │  │           │  │           │  │           │      │   │
│  │  │ :8080     │  │ :3000     │  │ :5000     │      │   │
│  │  │ :3000     │  │           │  │           │      │   │
│  │  └─────┬─────┘  └─────┬─────┘  └─────┬─────┘      │   │
│  │        │              │              │            │   │
│  └────────┼──────────────┼──────────────┼────────────┘   │
│           │              │              │                 │
│           └──────────────┼──────────────┘                 │
│                          │                                │
│                          ▼                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │                    Host (Caddy)                     │   │
│  │                                                     │   │
│  │  路由表:                                            │   │
│  │  8080-userA → Container A:8080                     │   │
│  │  3000-userA → Container A:3000                     │   │
│  │  3000-userB → Container B:3000                     │   │
│  │  5000-userC → Container C:5000                     │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 2.4 Redis 数据结构

```
# 端口映射表
port_map:{user_id}:{thread_id}:{internal_port}
├── external_host: "8080-user123.preview.example.com"
├── internal_port: 8080
├── container_ip: "172.17.0.5"
├── service_name: "my-web-app"
├── created_at: 1709520000
├── last_active: 1709520300
└── status: "active"

# 用户端口列表 (用于快速查询)
user_ports:{user_id} = SET {8080, 3000, 5000}

# 端口池管理 (用于分配外部端口，可选)
port_pool:available = SET {30001, 30002, ...}
port_pool:used = SET {30001}
```

## 3. 数据模型

### 3.1 数据库模型 (PostgreSQL)

```python
# src/database.py (新增)

from sqlalchemy import Column, String, Integer, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime

class PortMapping(Base):
    """端口映射持久化记录"""
    __tablename__ = "port_mappings"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    thread_id = Column(String(100), nullable=False, index=True)
    internal_port = Column(Integer, nullable=False)
    external_host = Column(String(255), nullable=False, unique=True)
    service_name = Column(String(100))
    container_id = Column(String(64))
    container_ip = Column(String(45))
    status = Column(String(20), default="active")  # active, inactive, deleted
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_accessed_at = Column(DateTime)
    
    user = relationship("User", back_populates="port_mappings")

# 在 User 模型中添加
class User(Base):
    # ... 现有字段 ...
    port_mappings = relationship("PortMapping", back_populates="user")
```

### 3.2 Pydantic 模型

```python
# api/models.py (新增)

from pydantic import BaseModel
from datetime import datetime
from typing import Optional

class PortMappingCreate(BaseModel):
    internal_port: int
    service_name: Optional[str] = None

class PortMappingResponse(BaseModel):
    id: int
    external_url: str
    internal_port: int
    service_name: Optional[str]
    status: str
    created_at: datetime
    
    class Config:
        from_attributes = True

class PortMappingList(BaseModel):
    mappings: list[PortMappingResponse]
    total: int

class PortDetectionResponse(BaseModel):
    detected_ports: list[int]
    registered: list[str]
```

## 4. 工作流程

### 4.1 端口自动检测流程

```
┌─────────────────────────────────────────────────────────────┐
│               Automatic Port Detection                      │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  定时任务 (每 30 秒) 或 用户触发                             │
│       │                                                     │
│       ▼                                                     │
│  ┌─────────────────────┐                                   │
│  │ 获取活跃容器列表     │                                   │
│  └──────────┬──────────┘                                   │
│             │                                               │
│             ▼                                               │
│  ┌─────────────────────┐                                   │
│  │ 执行 ss -tln 命令    │                                   │
│  │ 获取监听端口列表     │                                   │
│  └──────────┬──────────┘                                   │
│             │                                               │
│             ▼                                               │
│  ┌─────────────────────┐                                   │
│  │ 过滤系统端口         │                                   │
│  │ (22, 80, 443 等)    │                                   │
│  └──────────┬──────────┘                                   │
│             │                                               │
│             ▼                                               │
│  ┌─────────────────────┐                                   │
│  │ 检查是否已注册       │                                   │
│  └──────────┬──────────┘                                   │
│             │                                               │
│       ┌─────┴─────┐                                        │
│       ▼           ▼                                        │
│   已注册       未注册                                       │
│       │           │                                        │
│       ▼           ▼                                        │
│  更新活跃时间  注册新映射                                    │
│                   │                                        │
│                   ▼                                        │
│            生成外部 URL                                     │
│                   │                                        │
│                   ▼                                        │
│            同步 Caddy                                       │
│                   │                                        │
│                   ▼                                        │
│            通知用户 (可选)                                  │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 4.2 请求处理流程

```
┌─────────────────────────────────────────────────────────────┐
│                 Request Flow                                │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  1. 用户请求                                                │
│     GET https://8080-user123.preview.example.com/api/data  │
│                                                             │
│  2. DNS 解析                                                │
│     *.preview.example.com → Server IP                      │
│                                                             │
│  3. Caddy 接收请求                                          │
│     - TLS 终止                                              │
│     - 解析 Host: 8080-user123.preview.example.com          │
│                                                             │
│  4. 路由匹配                                                │
│     - 提取 port=8080, user=user123                         │
│     - 查找映射: port_map:user123:*:8080                    │
│                                                             │
│  5. 反向代理                                                │
│     - 目标: Container IP:8080                              │
│     - 添加 headers:                                         │
│       X-Real-IP: client.ip                                 │
│       X-Forwarded-For: client.ip                           │
│       X-Forwarded-Proto: https                             │
│                                                             │
│  6. 容器响应                                                │
│     Container → Caddy → User                               │
│                                                             │
│  7. 更新活跃时间 (异步)                                      │
│     port_map:...:last_active = now()                       │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

## 5. 资源隔离设计

### 5.1 容器级别隔离

```python
# src/docker_sandbox.py

def _create_container(self):
    return self.client.containers.create(
        image=self.image,
        
        # 资源限制
        cpu_quota=int(settings.DOCKER_CPU_LIMIT * 100000),  # 1 CPU
        mem_limit=settings.DOCKER_MEMORY_LIMIT,              # 2GB
        pids_limit=settings.DOCKER_PIDS_LIMIT,               # 100 processes
        
        # 网络配置
        network=settings.DOCKER_NETWORK_NAME,  # 自定义网络
        
        # 安全配置
        security_opt=[
            "no-new-privileges:true",  # 禁止提权
        ],
        cap_drop=["ALL"],              # 丢弃所有能力
        cap_add=["NET_BIND_SERVICE"],  # 仅添加必要能力
        
        # 只读根文件系统 (可选)
        # read_only=True,
        # tmpfs={"/tmp": "size=100M"},
    )
```

### 5.2 网络隔离

```python
# 创建隔离网络
def create_sandbox_network():
    try:
        return client.networks.get("sandbox_network")
    except docker.errors.NotFound:
        return client.networks.create(
            "sandbox_network",
            driver="bridge",
            internal=False,  # 允许外部访问
            enable_ipv6=False,
            ipam=docker.types.IPAMConfig(
                pool_configs=[
                    docker.types.IPAMPool(
                        subnet="172.28.0.0/16",
                        gateway="172.28.0.1"
                    )
                ]
            )
        )
```

### 5.3 用户级别限制

```python
# src/config.py

class Settings(BaseSettings):
    # 用户端口限制
    MAX_PORTS_PER_USER: int = 10
    
    # 端口范围
    ALLOWED_PORT_RANGE: tuple[int, int] = (1024, 65535)
    BLOCKED_PORTS: set[int] = {22, 25, 80, 443, 3306, 5432, 6379}
    
    # 服务超时
    PORT_MAPPING_TTL: int = 3600 * 24  # 24 小时
    INACTIVE_SERVICE_TTL: int = 3600    # 1 小时无访问自动清理
```

## 6. 扩展性设计

### 6.1 抽象层设计

```python
# src/port_mapping/abc.py

from abc import ABC, abstractmethod

class PortMappingBackend(ABC):
    """端口映射后端抽象"""
    
    @abstractmethod
    async def register(self, user_id: str, thread_id: str, port: int) -> str:
        """注册端口映射，返回外部 URL"""
        pass
    
    @abstractmethod
    async def unregister(self, mapping_id: str) -> bool:
        """取消端口映射"""
        pass
    
    @abstractmethod
    async def get_target(self, host: str) -> tuple[str, int] | None:
        """根据外部 host 获取内部目标"""
        pass

class ProxyConfigBackend(ABC):
    """代理配置后端抽象"""
    
    @abstractmethod
    async def add_route(self, host: str, target_ip: str, target_port: int) -> bool:
        """添加路由规则"""
        pass
    
    @abstractmethod
    async def remove_route(self, host: str) -> bool:
        """移除路由规则"""
        pass
```

### 6.2 多后端支持

```python
# 当前实现: Docker + Caddy
class DockerCaddyBackend(PortMappingBackend):
    pass

# 未来扩展: Kubernetes + Ingress
class KubernetesIngressBackend(PortMappingBackend):
    async def register(self, user_id, thread_id, port):
        # 创建 Service 和 Ingress 规则
        pass

# 未来扩展: 云服务
class CloudLBBackend(PortMappingBackend):
    async def register(self, user_id, thread_id, port):
        # 调用云 API 创建负载均衡规则
        pass
```
