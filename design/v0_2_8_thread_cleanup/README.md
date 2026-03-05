# Thread 生命周期管理与自动清理方案

## 版本信息
- 版本号: v0.2.8
- 日期: 2026-03-05
- 状态: 设计中

## 背景与问题

LangGraph 使用 PostgreSQL 存储 checkpoint 数据，但**没有提供自动清理机制**。长期运行后：

1. **Checkpoint 数据膨胀**: 每个 thread 的对话历史、状态快照累积在 PostgreSQL
2. **内存压力**: 大量不活跃的 thread 占用数据库存储
3. **资源泄漏**: Docker 容器有清理机制，但 checkpoint 数据没有配套清理

### 当前清理状态

| 组件 | 清理机制 | 状态 |
|------|---------|------|
| PostgreSQL checkpoint | 无 | ❌ |
| Thread 表记录 | 无 | ❌ |
| Docker 容器 | `cleanup_idle_containers()` | ⚠️ 有缺陷 |
| Redis 缓存 | 随容器清理 | ⚠️ 有缺陷 |

### LangGraph 提供的能力

```python
# 手动删除 thread 的所有 checkpoint
await checkpointer.adelete_thread(thread_id)
```

**没有** TTL 或自动过期机制，需要自行实现。

## 潜在僵尸场景分析

### 问题根源

1. **Redis 是缓存，不是真实来源** - 重启后数据可能丢失
2. **容器名是随机生成的** - 无法从容器反推 thread_id
3. **多数据源不一致** - Thread 表、Redis、Docker 三者需要保持一致

### 僵尸场景

| 场景 | 原因 | 后果 |
|------|------|------|
| Redis 无持久化 | Redis 默认不持久化，服务重启后数据丢失 | Docker 容器还在，但 Redis 无记录 → 清理任务扫不到 → **僵尸容器** |
| Thread/Docker 不一致 | Thread 表和 Redis 两个时间源 | 可能只清理了一半 |
| 孤儿容器 | 容器存在但 Thread 已被删除 | 无法被任何清理任务发现 |
| 服务崩溃 | 服务异常退出，内存中的 `_thread_backends` 丢失 | 下次启动无法恢复映射 |

### 解决方案：容器命名 + 启动同步

```
核心思路：
1. 容器命名: sandbox-{thread_id} (可从容器名反推 thread_id)
2. 启动时同步: 扫描所有容器，重建 Redis 映射，清理孤儿容器
3. Thread 表为唯一真实来源: 所有清理都以 Thread 表为准
```

## 解决方案

### 核心设计原则

1. **Thread 表为唯一真实来源**: 所有清理判断基于 Thread 表的 `last_active_at`
2. **容器命名规范化**: 使用 `sandbox-{thread_id}` 作为容器名
3. **启动时同步**: 服务启动时扫描容器，重建 Redis 映射，清理孤儿
4. **幂等清理**: 清理操作可以安全重复执行

### 架构设计

```
┌──────────────────────────────────────────────────────────────────┐
│                       服务启动                                    │
└─────────────────────────┬────────────────────────────────────────┘
                          │
                          ▼
┌──────────────────────────────────────────────────────────────────┐
│                    启动时同步 (sync_on_startup)                   │
│                                                                   │
│  1. 扫描所有 sandbox-* 容器                                       │
│  2. 从容器名提取 thread_id                                        │
│  3. 检查 Thread 表是否存在该 thread_id                            │
│     ├─ 存在: 重建 Redis 映射                                      │
│     └─ 不存在: 删除孤儿容器                                       │
└──────────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌──────────────────────────────────────────────────────────────────┐
│                         API 请求                                  │
│  POST /api/chat/{thread_id}                                      │
│  POST /api/resume/{thread_id}                                    │
└─────────────────────────┬────────────────────────────────────────┘
                          │
                          ▼
┌──────────────────────────────────────────────────────────────────┐
│                    更新 last_active_at                           │
│  Thread 表: last_active_at = now()                               │
│  Redis: sandbox:{thread_id}.last_active_at = now()               │
└──────────────────────────────────────────────────────────────────┘
                          │
                          │
┌─────────────────────────▼────────────────────────────────────────┐
│                    后台清理任务 (每 5 分钟)                        │
│                                                                   │
│  以 Thread 表为唯一真实来源:                                       │
│  1. 查询超时 threads: last_active_at < now() - THREAD_TTL        │
│  2. 对每个超时 thread:                                            │
│     ├─ checkpointer.adelete_thread(thread_id)  # 清理 checkpoint │
│     ├─ 删除容器 sandbox-{thread_id}             # 清理 Docker     │
│     ├─ r.delete(f"sandbox:{thread_id}")        # 清理 Redis      │
│     └─ db.delete(Thread)                       # 清理记录        │
└──────────────────────────────────────────────────────────────────┘
```

## 文件改动

### 1. src/database.py (+2 行)

```python
class Thread(Base):
    __tablename__ = "threads"

    thread_id = Column(String(100), primary_key=True)
    user_id = Column(String(50), nullable=False, index=True)
    title = Column(String(20), nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    last_active_at = Column(DateTime, server_default=func.now())  # 新增
```

### 2. src/config.py (+3 行)

```python
# Thread 生命周期配置
THREAD_IDLE_TIMEOUT_HOURS: int = 72  # 72 小时无活动则清理
THREAD_CLEANUP_INTERVAL_SECONDS: int = 300  # 每 5 分钟检查一次
```

### 3. src/docker_sandbox.py (~10 行改动)

**关键改动**: 容器命名规范化

```python
class DockerSandboxBackend(BaseSandbox):
    def _create_container(self) -> docker.models.containers.Container:
        """Create a new container with fixed naming convention."""
        # ... 其他参数不变
        
        return self.client.containers.create(
            image=self.image,
            name=f"sandbox-{self.thread_id}",  # 关键：固定命名
            command="sleep infinity",
            working_dir=settings.CONTAINER_WORKSPACE_DIR,
            # ... 其他参数
        )

    def destroy(self) -> None:
        """Destroy container by name."""
        try:
            # 通过名称查找并删除，更可靠
            container = self.client.containers.get(f"sandbox-{self.thread_id}")
            container.remove(force=True)
        except docker.errors.NotFound:
            pass
        finally:
            self._container = None
        
        r = _get_redis()
        r.delete(f"sandbox:{self.thread_id}")
```

### 4. src/agent_utils/session.py (+10 行)

```python
from datetime import datetime

class SessionManager:
    async def _update_thread_activity(self, thread_id: str):
        """更新 thread 最后活动时间"""
        with SessionLocal() as db:
            thread = db.query(Thread).filter(Thread.thread_id == thread_id).first()
            if thread:
                thread.last_active_at = datetime.utcnow()
                db.commit()

    async def create(self, user_id: str) -> str:
        thread_id = f"{user_id}-{uuid.uuid4()}"
        get_thread_backend(thread_id)
        with SessionLocal() as db:
            db.add(Thread(
                thread_id=thread_id, 
                user_id=user_id,
                last_active_at=datetime.utcnow()  # 新增
            ))
            db.commit()
        return thread_id
```

### 5. src/thread_cleanup.py (新增 ~120 行)

```python
"""Thread lifecycle management and cleanup."""

import asyncio
import time
from datetime import datetime, timedelta
from sqlalchemy import select
import docker

from src.config import settings
from src.database import SessionLocal, Thread
from src.docker_sandbox import _get_redis
from src.utils.get_logger import get_logger

logger = get_logger("thread-cleanup")


class ThreadCleanupManager:
    """Manages thread lifecycle and cleanup.
    
    Thread 表是唯一真实来源，所有清理判断基于 Thread 表。
    """
    
    def __init__(self, checkpointer):
        self.checkpointer = checkpointer
        self.docker_client = docker.from_env()
    
    async def sync_on_startup(self) -> dict:
        """服务启动时同步容器状态，清理孤儿容器。
        
        Returns:
            {"restored": N, "orphans_removed": M}
        """
        r = _get_redis()
        restored = 0
        orphans_removed = 0
        
        # 扫描所有 sandbox-* 容器
        containers = self.docker_client.containers.list(
            all=True, 
            filters={"name": "sandbox-"}
        )
        
        for container in containers:
            name = container.name
            thread_id = name.replace("sandbox-", "")
            
            # 检查 Thread 表是否存在
            with SessionLocal() as db:
                thread = db.query(Thread).filter(
                    Thread.thread_id == thread_id
                ).first()
            
            if thread:
                # 重建 Redis 映射
                r.hset(f"sandbox:{thread_id}", mapping={
                    "container_id": container.id,
                    "last_active_at": str(time.time())
                })
                restored += 1
                logger.info(f"[ThreadCleanup] Restored mapping: {thread_id}")
            else:
                # 孤儿容器，删除
                try:
                    container.remove(force=True)
                    r.delete(f"sandbox:{thread_id}")
                    orphans_removed += 1
                    logger.info(f"[ThreadCleanup] Removed orphan container: {name}")
                except Exception as e:
                    logger.error(f"[ThreadCleanup] Failed to remove orphan {name}: {e}")
        
        logger.info(
            f"[ThreadCleanup] Startup sync complete: "
            f"restored={restored}, orphans_removed={orphans_removed}"
        )
        return {"restored": restored, "orphans_removed": orphans_removed}
    
    async def cleanup_expired_threads(self) -> int:
        """
        Clean up threads that have been idle for too long.
        Thread 表是唯一真实来源。
        
        Returns:
            Number of threads cleaned up
        """
        timeout_hours = settings.THREAD_IDLE_TIMEOUT_HOURS
        cutoff_time = datetime.utcnow() - timedelta(hours=timeout_hours)
        
        cleaned = 0
        
        with SessionLocal() as db:
            expired_threads = db.execute(
                select(Thread).where(Thread.last_active_at < cutoff_time)
            ).scalars().all()
            
            for thread in expired_threads:
                try:
                    await self._cleanup_single_thread(thread.thread_id, db)
                    cleaned += 1
                    logger.info(f"[ThreadCleanup] Cleaned up thread: {thread.thread_id}")
                except Exception as e:
                    logger.error(f"[ThreadCleanup] Failed to cleanup {thread.thread_id}: {e}")
            
            db.commit()
        
        return cleaned
    
    async def _cleanup_single_thread(self, thread_id: str, db):
        """Clean up a single thread and all associated resources."""
        r = _get_redis()
        
        # 1. Delete checkpoints from LangGraph
        await self.checkpointer.adelete_thread(thread_id)
        
        # 2. Delete Docker container by name
        try:
            container = self.docker_client.containers.get(f"sandbox-{thread_id}")
            container.remove(force=True)
        except docker.errors.NotFound:
            pass
        
        # 3. Delete Redis record
        r.delete(f"sandbox:{thread_id}")
        
        # 4. Delete thread record from database
        thread = db.query(Thread).filter(Thread.thread_id == thread_id).first()
        if thread:
            db.delete(thread)
    
    async def run_cleanup_loop(self):
        """Background task that periodically cleans up expired threads."""
        interval = settings.THREAD_CLEANUP_INTERVAL_SECONDS
        
        while True:
            await asyncio.sleep(interval)
            try:
                cleaned = await self.cleanup_expired_threads()
                if cleaned > 0:
                    logger.info(f"[ThreadCleanup] Cleaned {cleaned} expired threads")
            except Exception as e:
                logger.error(f"[ThreadCleanup] Cleanup loop error: {e}")
```

### 6. main.py (~20 行改动)

```python
from src.thread_cleanup import ThreadCleanupManager

# 全局清理管理器
cleanup_manager: ThreadCleanupManager | None = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global cleanup_manager
    
    create_tables()
    await agent_manager.init()
    
    # 启动清理管理器
    cleanup_manager = ThreadCleanupManager(agent_manager.checkpointer)
    
    # 启动时同步容器状态
    await cleanup_manager.sync_on_startup()
    
    # 启动后台清理任务
    cleanup_task = asyncio.create_task(cleanup_manager.run_cleanup_loop())
    
    try:
        yield
    finally:
        cleanup_task.cancel()
        await agent_manager.close()
```

### 7. src/agent_manager.py (~5 行改动)

在 `stream_chat` 和 `stream_resume_interrupt` 方法中更新活动时间:

```python
async def stream_chat(self, thread_id: str, ...):
    # 更新最后活动时间
    await self.session_manager._update_thread_activity(thread_id)
    
    # ... 原有逻辑

async def stream_resume_interrupt(self, thread_id: str, ...):
    # 更新最后活动时间
    await self.session_manager._update_thread_activity(thread_id)
    
    # ... 原有逻辑
```

## 环境变量

`.env` 新增配置:
```env
# Thread 生命周期配置
THREAD_IDLE_TIMEOUT_HOURS=72        # 72 小时无活动则清理
THREAD_CLEANUP_INTERVAL_SECONDS=300 # 每 5 分钟检查一次
```

## 数据库迁移

对于已有的 Thread 记录，需要设置默认的 `last_active_at`:

```sql
-- 为已有记录设置 last_active_at 为 created_at
ALTER TABLE threads ADD COLUMN last_active_at TIMESTAMP DEFAULT NOW();
UPDATE threads SET last_active_at = created_at WHERE last_active_at IS NULL;
```

或者通过 Alembic 迁移:
```bash
alembic revision --autogenerate -m "add last_active_at to threads"
alembic upgrade head
```

## 改动量估算

| 文件 | 新增行 | 修改行 |
|------|--------|--------|
| src/database.py | 2 | 0 |
| src/config.py | 3 | 0 |
| src/docker_sandbox.py | 5 | 10 |
| src/agent_utils/session.py | 10 | 2 |
| src/thread_cleanup.py | 120 | 0 |
| main.py | 15 | 5 |
| src/agent_manager.py | 4 | 0 |
| **总计** | **159** | **17** |

## 测试要点

1. **活动时间更新**: chat/resume 后检查 `last_active_at` 是否更新
2. **自动清理**: 修改 TTL 为短时间（如 1 分钟），验证超时 thread 被清理
3. **完整清理**: 确认 checkpoint、Thread 记录、Docker、Redis 全部清理
4. **不影响活跃 thread**: 确保活跃 thread 不会被误删
5. **错误处理**: 单个 thread 清理失败不影响其他 thread
6. **启动时同步**: 
   - 模拟 Redis 数据丢失，验证容器映射被恢复
   - 创建孤儿容器，验证启动时被清理
7. **容器命名**: 验证新创建的容器名称为 `sandbox-{thread_id}`

## 风险与注意事项

1. **数据丢失**: 清理后对话历史无法恢复，需确保 TTL 设置合理
2. **用户通知**: 可考虑在清理前通过邮件/通知提醒用户
3. **白名单机制**: 未来可添加 `pinned` 字段，标记重要 thread 不被清理
4. **备份策略**: 清理前可先归档到冷存储
5. **容器命名冲突**: 如果已存在同名容器（异常情况），创建会失败，需要先清理

## 兼容性说明

### 现有容器处理

服务启动时，会扫描所有 `sandbox-*` 容器：
- 如果 Thread 记录存在 → 保留容器，重建 Redis 映射
- 如果 Thread 记录不存在 → 删除孤儿容器

### 旧容器（无命名规范）

如果存在未使用 `sandbox-*` 命名的旧容器：
- 不会被 `sync_on_startup` 发现
- 需要手动清理或等待它们被 Docker 自身清理

建议：首次部署后检查是否有孤儿容器
```bash
docker ps -a --filter "name=sandbox-"
```
