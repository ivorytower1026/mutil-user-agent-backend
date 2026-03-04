# 04. 核心代码实现

## 1. 文件结构

```
backend/
├── src/
│   ├── port_mapping/
│   │   ├── __init__.py
│   │   ├── manager.py          # 端口映射管理器
│   │   ├── detector.py         # 端口检测器
│   │   ├── caddy_client.py     # Caddy API 客户端
│   │   └── exceptions.py       # 自定义异常
│   ├── docker_sandbox.py       # 修改: 添加端口检测
│   └── config.py               # 修改: 添加配置项
├── api/
│   └── ports.py                # 新增: 端口映射 API
└── tests/
    └── test_port_mapping.py    # 新增: 测试用例
```

## 2. 端口映射管理器

```python
# src/port_mapping/manager.py

import time
import redis
from typing import Optional
from dataclasses import dataclass
from src.config import settings
from src.port_mapping.caddy_client import CaddyClient
from src.port_mapping.exceptions import (
    PortMappingError,
    PortLimitExceeded,
    PortAlreadyMapped
)


@dataclass
class PortMapping:
    user_id: str
    thread_id: str
    internal_port: int
    external_host: str
    container_ip: str
    service_name: Optional[str]
    created_at: float
    last_active: float
    status: str = "active"


class PortMappingManager:
    """端口映射管理器"""
    
    def __init__(self, redis_client: redis.Redis, caddy_client: CaddyClient):
        self.redis = redis_client
        self.caddy = caddy_client
        self.base_domain = settings.PREVIEW_DOMAIN
        self.max_ports = settings.MAX_PORTS_PER_USER
    
    def _get_key(self, user_id: str, thread_id: str, port: int) -> str:
        return f"port_map:{user_id}:{thread_id}:{port}"
    
    def _generate_host(self, user_id: str, port: int) -> str:
        return f"{port}-{user_id}.{self.base_domain}"
    
    def _count_user_ports(self, user_id: str) -> int:
        count = 0
        for key in self.redis.scan_iter(f"port_map:{user_id}:*"):
            count += 1
        return count
    
    def register(
        self,
        user_id: str,
        thread_id: str,
        internal_port: int,
        container_ip: str,
        service_name: Optional[str] = None
    ) -> str:
        """
        注册端口映射
        
        Args:
            user_id: 用户 ID
            thread_id: 线程 ID
            internal_port: 容器内部端口
            container_ip: 容器 IP 地址
            service_name: 服务名称 (可选)
            
        Returns:
            外部访问 URL
            
        Raises:
            PortLimitExceeded: 超过端口限制
            PortAlreadyMapped: 端口已映射
        """
        if internal_port in settings.BLOCKED_PORTS:
            raise PortMappingError(f"Port {internal_port} is blocked")
        
        if not (1024 <= internal_port <= 65535):
            raise PortMappingError(f"Port {internal_port} out of allowed range")
        
        current_count = self._count_user_ports(user_id)
        if current_count >= self.max_ports:
            raise PortLimitExceeded(
                f"User {user_id} has reached max ports limit ({self.max_ports})"
            )
        
        key = self._get_key(user_id, thread_id, internal_port)
        
        if self.redis.exists(key):
            existing = self.redis.hgetall(key)
            if existing.get("status") == "active":
                raise PortAlreadyMapped(
                    f"Port {internal_port} already mapped for user {user_id}"
                )
        
        external_host = self._generate_host(user_id, internal_port)
        now = time.time()
        
        mapping_data = {
            "external_host": external_host,
            "internal_port": internal_port,
            "container_ip": container_ip,
            "service_name": service_name or "",
            "created_at": str(now),
            "last_active": str(now),
            "status": "active"
        }
        
        self.redis.hset(key, mapping={k: str(v) for k, v in mapping_data.items()})
        self.redis.sadd(f"user_ports:{user_id}", internal_port)
        
        self.caddy.add_route(
            host=external_host,
            target_ip=container_ip,
            target_port=internal_port
        )
        
        return f"https://{external_host}"
    
    def unregister(self, user_id: str, internal_port: int) -> bool:
        """取消端口映射"""
        for key in self.redis.scan_iter(f"port_map:{user_id}:*:{internal_port}"):
            mapping = self.redis.hgetall(key)
            if mapping:
                external_host = mapping.get("external_host")
                if external_host:
                    self.caddy.remove_route(external_host)
                
                self.redis.delete(key)
                self.redis.srem(f"user_ports:{user_id}", internal_port)
                return True
        return False
    
    def get_mapping(self, user_id: str, internal_port: int) -> Optional[PortMapping]:
        """获取端口映射信息"""
        for key in self.redis.scan_iter(f"port_map:{user_id}:*:{internal_port}"):
            data = self.redis.hgetall(key)
            if data:
                return PortMapping(
                    user_id=user_id,
                    thread_id=key.split(":")[2],
                    internal_port=int(data["internal_port"]),
                    external_host=data["external_host"],
                    container_ip=data["container_ip"],
                    service_name=data.get("service_name") or None,
                    created_at=float(data["created_at"]),
                    last_active=float(data["last_active"]),
                    status=data.get("status", "active")
                )
        return None
    
    def list_user_ports(self, user_id: str) -> list[PortMapping]:
        """列出用户所有端口映射"""
        mappings = []
        for key in self.redis.scan_iter(f"port_map:{user_id}:*"):
            data = self.redis.hgetall(key)
            if data and data.get("status") == "active":
                parts = key.split(":")
                mappings.append(PortMapping(
                    user_id=user_id,
                    thread_id=parts[2],
                    internal_port=int(data["internal_port"]),
                    external_host=data["external_host"],
                    container_ip=data["container_ip"],
                    service_name=data.get("service_name") or None,
                    created_at=float(data["created_at"]),
                    last_active=float(data["last_active"]),
                    status=data.get("status", "active")
                ))
        return mappings
    
    def update_activity(self, user_id: str, internal_port: int):
        """更新端口活跃时间"""
        for key in self.redis.scan_iter(f"port_map:{user_id}:*:{internal_port}"):
            self.redis.hset(key, "last_active", str(time.time()))
            break
    
    def cleanup_inactive(self, max_inactive_seconds: int) -> int:
        """清理不活跃的端口映射"""
        now = time.time()
        cleaned = 0
        
        for key in self.redis.scan_iter("port_map:*"):
            try:
                data = self.redis.hgetall(key)
                if not data:
                    continue
                
                last_active = float(data.get("last_active", 0))
                if now - last_active > max_inactive_seconds:
                    parts = key.split(":")
                    user_id = parts[1]
                    internal_port = int(parts[3])
                    
                    external_host = data.get("external_host")
                    if external_host:
                        self.caddy.remove_route(external_host)
                    
                    self.redis.delete(key)
                    self.redis.srem(f"user_ports:{user_id}", internal_port)
                    cleaned += 1
                    
            except Exception as e:
                print(f"[PortMapping] Error cleaning up {key}: {e}")
        
        return cleaned


_port_mapping_manager: Optional[PortMappingManager] = None


def get_port_manager() -> PortMappingManager:
    """获取端口映射管理器单例"""
    global _port_mapping_manager
    if _port_mapping_manager is None:
        redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)
        caddy_client = CaddyClient(settings.CADDY_API_URL)
        _port_mapping_manager = PortMappingManager(redis_client, caddy_client)
    return _port_mapping_manager
```

## 3. 端口检测器

```python
# src/port_mapping/detector.py

import docker
from typing import List
from src.config import settings


class PortDetector:
    """容器端口检测器"""
    
    # 系统端口，不应暴露
    SYSTEM_PORTS = {22, 25, 80, 443, 3306, 5432, 6379, 27017}
    
    def __init__(self, docker_client: docker.DockerClient = None):
        self.client = docker_client or docker.from_env()
    
    def detect_listening_ports(self, container_id: str) -> List[int]:
        """
        检测容器内正在监听的端口
        
        Args:
            container_id: 容器 ID
            
        Returns:
            监听端口列表
        """
        try:
            container = self.client.containers.get(container_id)
        except docker.errors.NotFound:
            return []
        
        exit_code, output = container.exec_run(
            cmd=["/bin/bash", "-c",
                 "ss -tln 2>/dev/null | awk 'NR>1 {print $4}' | "
                 "grep -oE '[0-9]+$' | sort -n | uniq"
            ]
        )
        
        if exit_code != 0:
            exit_code, output = container.exec_run(
                cmd=["/bin/bash", "-c",
                     "netstat -tln 2>/dev/null | awk 'NR>2 {print $4}' | "
                     "grep -oE '[0-9]+$' | sort -n | uniq"
                ]
            )
        
        if exit_code != 0:
            return []
        
        ports = []
        for line in output.decode().strip().split('\n'):
            line = line.strip()
            if line.isdigit():
                port = int(line)
                if port not in self.SYSTEM_PORTS and 1024 <= port <= 65535:
                    ports.append(port)
        
        return sorted(set(ports))
    
    def get_container_ip(self, container_id: str) -> str | None:
        """获取容器 IP 地址"""
        try:
            container = self.client.containers.get(container_id)
            container.reload()
            networks = container.attrs.get("NetworkSettings", {}).get("Networks", {})
            
            for network_name, network_info in networks.items():
                if network_name == settings.DOCKER_NETWORK_NAME:
                    return network_info.get("IPAddress")
            
            for network_info in networks.values():
                ip = network_info.get("IPAddress")
                if ip:
                    return ip
            
            return None
        except docker.errors.NotFound:
            return None
```

## 4. Caddy 客户端

```python
# src/port_mapping/caddy_client.py

import httpx
from typing import Optional
from src.port_mapping.exceptions import CaddyError


class CaddyClient:
    """Caddy Admin API 客户端"""
    
    def __init__(self, base_url: str = "http://localhost:2019"):
        self.base_url = base_url
        self.client = httpx.Client(timeout=10.0)
    
    def add_route(
        self,
        host: str,
        target_ip: str,
        target_port: int,
        route_id: Optional[str] = None
    ) -> bool:
        """
        添加反向代理路由
        
        Args:
            host: 外部主机名
            target_ip: 目标容器 IP
            target_port: 目标端口
            route_id: 路由 ID (可选，默认使用 host)
            
        Returns:
            是否成功
        """
        route_id = route_id or host
        target = f"{target_ip}:{target_port}"
        
        route = {
            "@id": route_id,
            "match": [{"host": [host]}],
            "handle": [{
                "handler": "reverse_proxy",
                "upstreams": [{"dial": target}],
                "headers": {
                    "request": {
                        "set": {
                            "X-Real-IP": ["{http.request.remote.host}"],
                            "X-Forwarded-For": ["{http.request.remote.host}"],
                            "X-Forwarded-Proto": ["{http.request.scheme}"]
                        }
                    }
                }
            }]
        }
        
        try:
            resp = self.client.post(
                f"{self.base_url}/config/apps/http/servers/srv0/routes",
                json=route
            )
            
            if resp.status_code in (200, 201):
                return True
            
            if resp.status_code == 409:
                self.remove_route(route_id)
                return self.add_route(host, target_ip, target_port, route_id)
            
            raise CaddyError(f"Failed to add route: {resp.status_code} {resp.text}")
            
        except httpx.RequestError as e:
            raise CaddyError(f"Caddy API error: {e}")
    
    def remove_route(self, route_id: str) -> bool:
        """移除路由"""
        try:
            resp = self.client.delete(f"{self.base_url}/id/{route_id}")
            
            if resp.status_code in (200, 204, 404):
                return True
            
            raise CaddyError(f"Failed to remove route: {resp.status_code}")
            
        except httpx.RequestError as e:
            raise CaddyError(f"Caddy API error: {e}")
    
    def list_routes(self) -> list[dict]:
        """列出所有路由"""
        try:
            resp = self.client.get(
                f"{self.base_url}/config/apps/http/servers/srv0/routes"
            )
            
            if resp.status_code == 200:
                return resp.json()
            
            return []
            
        except httpx.RequestError:
            return []
    
    def health_check(self) -> bool:
        """健康检查"""
        try:
            resp = self.client.get(f"{self.base_url}/config/")
            return resp.status_code == 200
        except httpx.RequestError:
            return False
```

## 5. 异常定义

```python
# src/port_mapping/exceptions.py


class PortMappingError(Exception):
    """端口映射基础异常"""
    pass


class PortLimitExceeded(PortMappingError):
    """超过端口限制"""
    pass


class PortAlreadyMapped(PortMappingError):
    """端口已映射"""
    pass


class CaddyError(Exception):
    """Caddy 相关错误"""
    pass
```

## 6. Docker Sandbox 修改

```python
# src/docker_sandbox.py (修改部分)

from src.port_mapping.detector import PortDetector
from src.port_mapping.manager import PortMappingManager


class DockerSandboxBackend(BaseSandbox):
    
    def __init__(self, thread_id: str, workspace_dir: str):
        self.thread_id = thread_id
        self.workspace_dir = workspace_dir
        self.image = settings.DOCKER_IMAGE
        self.client = docker.from_env()
        self._container = None
        self._detector = PortDetector(self.client)
    
    def detect_listening_ports(self) -> list[int]:
        """检测容器内正在监听的端口"""
        container = self._ensure_container()
        return self._detector.detect_listening_ports(container.id)
    
    def get_container_ip(self) -> str | None:
        """获取容器 IP 地址"""
        container = self._ensure_container()
        return self._detector.get_container_ip(container.id)
    
    def auto_register_ports(
        self,
        port_manager: PortMappingManager,
        service_names: dict[int, str] = None
    ) -> list[str]:
        """
        自动检测并注册所有监听端口
        
        Args:
            port_manager: 端口映射管理器
            service_names: 端口到服务名的映射 (可选)
            
        Returns:
            注册成功的外部 URL 列表
        """
        user_id = self.thread_id[:36]
        container_ip = self.get_container_ip()
        
        if not container_ip:
            print(f"[DockerSandbox] Cannot get container IP for {self.thread_id}")
            return []
        
        ports = self.detect_listening_ports()
        urls = []
        service_names = service_names or {}
        
        for port in ports:
            existing = port_manager.get_mapping(user_id, port)
            
            if existing:
                port_manager.update_activity(user_id, port)
                continue
            
            try:
                service_name = service_names.get(port)
                url = port_manager.register(
                    user_id=user_id,
                    thread_id=self.thread_id,
                    internal_port=port,
                    container_ip=container_ip,
                    service_name=service_name
                )
                urls.append(url)
                print(f"[DockerSandbox] Auto-registered: {url}")
                
            except Exception as e:
                print(f"[DockerSandbox] Failed to register port {port}: {e}")
        
        return urls
    
    def _create_container(self) -> docker.models.containers.Container:
        """创建容器 (修改: 添加网络和资源限制)"""
        shared_dir = str(Path(settings.SHARED_DIR).expanduser().absolute())
        os.makedirs(shared_dir, exist_ok=True)
        
        skills_dir = str(Path(settings.SKILL_DIR).expanduser().absolute())
        os.makedirs(skills_dir, exist_ok=True)
        
        return self.client.containers.create(
            image=self.image,
            command="sleep infinity",
            working_dir=settings.CONTAINER_WORKSPACE_DIR,
            volumes={
                _to_docker_path(self.workspace_dir): {
                    "bind": settings.CONTAINER_WORKSPACE_DIR,
                    "mode": "rw",
                },
                _to_docker_path(shared_dir): {
                    "bind": settings.CONTAINER_SHARED_DIR,
                    "mode": "ro",
                },
                _to_docker_path(skills_dir): {
                    "bind": settings.CONTAINER_SKILLS_DIR,
                    "mode": "ro",
                },
            },
            network=settings.DOCKER_NETWORK_NAME,
            cpu_quota=int(settings.DOCKER_CPU_LIMIT * 100000),
            mem_limit=settings.DOCKER_MEMORY_LIMIT,
            pids_limit=settings.DOCKER_PIDS_LIMIT,
            security_opt=["no-new-privileges:true"],
        )
```

## 7. 初始化 Docker 网络

```python
# src/docker_sandbox.py (新增函数)

def ensure_sandbox_network() -> str:
    """确保沙箱网络存在"""
    client = docker.from_env()
    network_name = settings.DOCKER_NETWORK_NAME
    
    try:
        network = client.networks.get(network_name)
        return network_name
    except docker.errors.NotFound:
        pass
    
    network = client.networks.create(
        network_name,
        driver="bridge",
        internal=False,
        ipam=docker.types.IPAMConfig(
            pool_configs=[
                docker.types.IPAMPool(
                    subnet="172.28.0.0/16",
                    gateway="172.28.0.1"
                )
            ]
        )
    )
    print(f"[DockerSandbox] Created network: {network_name}")
    return network_name
```

## 8. 定时任务

```python
# main.py (新增)

from src.port_mapping import get_port_manager
from src.docker_sandbox import cleanup_idle_containers


async def _cleanup_task():
    """后台清理任务"""
    while True:
        try:
            await asyncio.sleep(300)
            
            cleaned_containers = cleanup_idle_containers()
            if cleaned_containers > 0:
                print(f"[CleanupTask] Cleaned {cleaned_containers} idle containers")
            
            port_manager = get_port_manager()
            cleaned_ports = port_manager.cleanup_inactive(
                settings.PORT_MAPPING_TTL
            )
            if cleaned_ports > 0:
                print(f"[CleanupTask] Cleaned {cleaned_ports} inactive port mappings")
                
        except Exception as e:
            print(f"[CleanupTask] Error: {e}")


# 在 lifespan 中添加
@asynccontextmanager
async def lifespan(app: FastAPI):
    from src.docker_sandbox import ensure_sandbox_network
    ensure_sandbox_network()
    
    cleanup_task = asyncio.create_task(_cleanup_task())
    
    yield
    
    cleanup_task.cancel()
```
