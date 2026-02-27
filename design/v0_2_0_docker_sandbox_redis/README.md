# Docker 沙箱资源限制与 Redis 管理方案

## 版本信息
- 版本号: v0.2.0
- 日期: 2026-02-27
- 状态: 设计中

## 背景与问题

当前 Docker 沙箱存在以下问题：

1. **无资源限制**: 容器没有 CPU、内存限制，可能导致单个用户占用过多资源
2. **内存管理**: `_user_backends` 使用内存字典管理，服务重启后丢失
3. **用户级沙箱**: 一个用户的所有线程共享一个容器，隔离性不足
4. **无自动清理**: 容器不会自动销毁，可能造成资源泄漏

## 解决方案

### 1. 资源限制

在容器创建时添加 CPU 和内存限制：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `cpu_quota` | 100000 | CPU 时间配额（配合 cpu_period=100000 = 1核） |
| `mem_limit` | "2g" | 内存上限 |

```python
self.client.containers.create(
    image=self.image,
    cpu_quota=int(settings.DOCKER_CPU_LIMIT * 100000),  # 1核 = 100000
    mem_limit=settings.DOCKER_MEMORY_LIMIT,              # "2g"
    ...
)
```

### 2. Redis 管理

使用 Redis 存储沙箱元数据，实现持久化和跨服务共享：

**Redis Key 设计**:
```
sandbox:{thread_id} -> {
    "container_id": "abc123...",
    "last_active_at": 1709012345.123
}
```

**TTL 策略**: 不设置 Redis TTL，由后台任务统一清理

### 3. 线程级沙箱

将沙箱从用户级改为线程级：

| 改动前 | 改动后 |
|--------|--------|
| `workspaces/{user_id}/` | `workspaces/{thread_id}/` |
| 用户所有线程共享容器 | 每个线程独立容器 |

### 4. 自动清理机制

**后台定时任务**:
- 间隔: 每 60 秒扫描一次
- 超时: 10 分钟（600 秒）无操作
- 动作: 删除容器 + 删除 Redis 记录

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│  API 请求   │────▶│  更新 Redis  │────▶│  执行操作   │
│             │     │ last_active  │     │             │
└─────────────┘     └──────────────┘     └─────────────┘
                           │
                           ▼
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│ 后台任务    │────▶│  扫描 Redis  │────▶│ 清理超时    │
│ (60s/次)    │     │  检查时间戳   │     │   容器      │
└─────────────┘     └──────────────┘     └─────────────┘
```

## 文件改动

### 1. pyproject.toml (+1 行)
```diff
  dependencies = [
      ...
+     "redis>=5.0.0",
  ]
```

### 2. src/config.py (+5 行)
```python
# Docker 资源限制
DOCKER_CPU_LIMIT: float = 1.0        # CPU 核数
DOCKER_MEMORY_LIMIT: str = "2g"      # 内存限制

# 沙箱超时配置  
DOCKER_IDLE_TIMEOUT_SECONDS: int = 600  # 10 分钟
REDIS_URL: str = "redis://localhost:6379/0"
```

### 3. src/docker_sandbox.py (~40 行改动)

| 改动点 | 说明 |
|--------|------|
| `_user_backends` → `_thread_backends` | 本地缓存改为线程级别 |
| `get_thread_backend()` | workspace 改为 `{thread_id}/` |
| 新增 `_get_redis()` | 获取 Redis 连接 |
| `_create_container()` | 添加 `cpu_quota`, `mem_limit` |
| `_update_activity()` | 更新 Redis 活动时间 |
| `execute()` 等方法 | 调用 `_update_activity()` |
| `cleanup_idle_containers()` | 静态方法，清理超时容器 |

**核心代码结构**:
```python
import redis
import json
import time

_redis_client = None

def _get_redis():
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.from_url(settings.REDIS_URL)
    return _redis_client

class DockerSandboxBackend:
    def _update_activity(self):
        r = _get_redis()
        r.hset(f"sandbox:{self.thread_id}", mapping={
            "container_id": self._container.id if self._container else "",
            "last_active_at": time.time()
        })
    
    def _create_container(self):
        return self.client.containers.create(
            image=self.image,
            cpu_quota=int(settings.DOCKER_CPU_LIMIT * 100000),
            mem_limit=settings.DOCKER_MEMORY_LIMIT,
            ...
        )
    
    def execute(self, command):
        self._update_activity()  # 更新活动时间
        ...
    
    @staticmethod
    def cleanup_idle_containers():
        """清理超时容器，由后台任务调用"""
        r = _get_redis()
        now = time.time()
        timeout = settings.DOCKER_IDLE_TIMEOUT_SECONDS
        
        for key in r.scan_iter("sandbox:*"):
            last_active = float(r.hget(key, "last_active_at") or 0)
            if now - last_active > timeout:
                container_id = r.hget(key, "container_id")
                # 删除容器
                try:
                    container = docker.from_env().containers.get(container_id)
                    container.remove(force=True)
                except:
                    pass
                # 删除 Redis 记录
                r.delete(key)
```

### 4. main.py (+15 行)

```python
import asyncio
from src.docker_sandbox import DockerSandboxBackend

async def cleanup_task():
    """后台清理任务"""
    while True:
        await asyncio.sleep(60)  # 每 60 秒
        try:
            DockerSandboxBackend.cleanup_idle_containers()
        except Exception as e:
            print(f"[CleanupTask] Error: {e}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    create_tables()
    await agent_manager.init()
    
    # 启动后台清理任务
    task = asyncio.create_task(cleanup_task())
    
    try:
        yield
    finally:
        task.cancel()
        await agent_manager.close()
```

## 环境变量

`.env` 新增配置:
```env
# Docker 资源限制
DOCKER_CPU_LIMIT=1.0
DOCKER_MEMORY_LIMIT=2g

# 沙箱超时（秒）
DOCKER_IDLE_TIMEOUT_SECONDS=600

# Redis 连接
REDIS_URL=redis://localhost:6379/0
```

## 兼容性说明

### API 层无改动
- `get_thread_backend(thread_id)` 接口不变
- `destroy_thread_backend(thread_id)` 接口不变

### 工作目录变更
- 旧: `workspaces/{user_id}/`
- 新: `workspaces/{thread_id}/`

**注意**: 此变更会导致旧数据不兼容，需要迁移或清理

### 容器命名
- 容器名称保持自动生成（Docker 默认行为）
- 通过 Redis 映射 `thread_id` -> `container_id`

## 测试要点

1. **资源限制验证**: 在容器内运行 CPU/内存密集任务，确认被限制
2. **Redis 持久化**: 重启服务后，通过 Redis 恢复容器映射
3. **自动清理**: 等待 10 分钟后确认容器被删除
4. **并发安全**: 多线程同时操作不同沙箱

## 改动量估算

| 文件 | 新增行 | 修改行 |
|------|--------|--------|
| pyproject.toml | 1 | 0 |
| src/config.py | 5 | 0 |
| src/docker_sandbox.py | 30 | 15 |
| main.py | 15 | 2 |
| **总计** | **51** | **17** |
