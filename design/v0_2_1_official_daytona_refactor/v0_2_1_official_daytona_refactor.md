# v0.2.1 官方 langchain-daytona 重构方案

> 版本: 0.2.1
> 日期: 2026-02-21
> 状态: 待审核
> 作者: AI Agent

---

## 一、背景与问题

### 1.1 现有"造轮子"代码

| 文件 | 代码量 | 问题 |
|------|--------|------|
| `src/daytona_sandbox.py` | ~97行 | 自实现 `BaseSandbox`，官方 `langchain-daytona` 已提供 |
| `src/daytona_sandbox_manager.py` | ~120行 | 手动管理沙箱生命周期，Daytona SDK 原生支持自动管理 |
| `src/daytona_client.py` | ~26行 | 仅封装 SDK，可精简 |

### 1.2 架构问题

1. **Skills 与沙箱分离**：Skills 存储在本地，沙箱在 Daytona，执行时无法访问
2. **WebDAV 操作 Daytona**：需要沙箱持续运行，增加成本
3. **无文件同步机制**：本地文件与沙箱文件无同步

### 1.3 目标

1. 使用官方 `langchain-daytona` 替代自实现代码
2. 使用 `CompositeBackend` 实现多后端路由
3. Skills 通过快照内置到沙箱，解决执行问题
4. WebDAV 操作本地文件，通过同步机制与沙箱交互

---

## 二、目标架构

### 2.1 整体架构

```
┌─────────────────────────────────────────────────────────────────┐
│                      CompositeBackend                            │
│  ┌───────────────────┐  ┌────────────────────────────────────┐  │
│  │ /workspace/       │  │ /commod_workspace/ (Daytona)       │  │
│  │ FilesystemBackend │  │ - /commod_workspace/ 用户工作目录   │  │
│  │ (本地只读预览)     │  │ - /skills/ 快照内置(只读)          │  │
│  └───────────────────┘  └────────────────────────────────────┘  │
│                                                                  │
│  其他路径 → StateBackend (临时状态)                               │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 Skills 快照架构

```
Skill 生命周期：
┌────────────┐    验证     ┌────────────┐    通过     ┌────────────┐
│ 本地待验证  │ ─────────► │ Daytona    │ ─────────► │ 重建全局    │
│ SKILL.md   │            │ 验证沙箱    │            │ 快照       │
│ (本地目录)  │            │ (独立沙箱)  │            │ (含skills) │
└────────────┘            └────────────┘            └────────────┘

快照内容：
/skills/
├── skill-a/
│   └── SKILL.md
├── skill-b/
│   ├── SKILL.md
│   └── helper.py
└── ...
```

### 2.3 会话文件同步流程

```
用户启动会话
    │
    ▼
┌─────────────────────────────────┐
│ POST /api/threads/{id}/sync     │
│ { "direction": "to_daytona",    │
│   "paths": ["src/", "data/"] }  │
└─────────────────────────────────┘
    │
    ▼
本地 /workspace/{user_id}/  ──► Daytona /commod_workspace/
    │
    ▼
Agent 执行任务（读取/执行都在沙箱内）
    │
    ▼
┌─────────────────────────────────┐
│ POST /api/threads/{id}/sync     │
│ { "direction": "from_daytona",  │
│   "paths": ["output/"] }        │
└─────────────────────────────────┘
    │
    ▼
Daytona /commod_workspace/  ──► 本地 /workspace/{user_id}/
```

### 2.4 WebDAV 定位

```
WebDAV /dav/{user_id}/*
    │
    ▼
本地 /mutli-user-agent/{user_id}/workspace/
    │
    ├─ 用户通过 WebDAV 管理本地文件
    │
    └─ 需要执行时，通过同步 API 传到 Daytona
```

---

## 三、文件变更清单

### 3.1 删除文件

| 文件 | 原因 |
|------|------|
| `src/daytona_sandbox.py` | 官方 `langchain-daytona.DaytonaSandbox` 已实现相同功能 |
| `src/daytona_sandbox_manager.py` | Daytona SDK 支持自动生命周期管理，无需手动管理 |
| `tests/test_daytona_sandbox.py` | 测试需重写，旧测试不再适用 |

**删除原因**：
- 官方 `langchain-daytona` 包提供 `DaytonaSandbox` 类，继承自 `BaseSandbox`
- Daytona SDK 支持 `auto_stop_interval` / `auto_delete_interval`，无需手动管理
- 减少约 200+ 行维护代码

### 3.2 新增文件

| 文件 | 功能 | 代码量 |
|------|------|--------|
| `src/backends/__init__.py` | Backend 模块初始化 | ~5行 |
| `src/backends/composite.py` | CompositeBackend 工厂函数 | ~50行 |
| `src/snapshot_manager.py` | Skills 快照管理服务 | ~80行 |
| `src/workspace_sync.py` | 本地 ↔ Daytona 文件同步服务 | ~60行 |
| `api/workspace.py` | 文件同步 API 端点 | ~40行 |

**新增原因**：
- `composite.py`: 配置多后端路由，支持 `/workspace/` 和 `/commod_workspace/`
- `snapshot_manager.py`: 管理全局 Skills 快照，验证通过后自动重建
- `workspace_sync.py`: 封装文件同步逻辑，支持双向同步
- `workspace.py`: 提供 REST API 供前端调用

### 3.3 修改文件

| 文件 | 改动内容 | 改动量 |
|------|----------|--------|
| `src/daytona_client.py` | 精简为 SDK 封装 + 沙箱创建辅助 | 大改 |
| `src/agent_manager.py` | 使用 CompositeBackend + 快照启动 | 中改 |
| `src/webdav.py` | 改为操作本地文件系统 | 大改 |
| `src/config.py` | 添加新配置项 | 小改 |
| `src/skill_validator.py` | 验证通过后触发快照重建 | 中改 |
| `pyproject.toml` | 添加 `langchain-daytona` 依赖 | 小改 |
| `api/__init__.py` | 注册 workspace 路由 | 小改 |

#### 3.3.1 `src/daytona_client.py` 改动详情

**改动原因**：
- 移除沙箱管理逻辑（由 CompositeBackend 管理）
- 添加基于快照创建沙箱的方法
- 添加查找沙箱的方法（用于会话恢复）

**改动前**：
```python
class DaytonaClient:
    def __init__(self):
        self._client = Daytona(...)
    
    @property
    def client(self) -> Daytona:
        return self._client
```

**改动后**：
```python
class DaytonaClient:
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._client = Daytona(DaytonaConfig(
                api_key=settings.DAYTONA_API_KEY,
                api_url=settings.DAYTONA_API_URL,
            ))
        return cls._instance
    
    @property
    def client(self) -> Daytona:
        return self._client
    
    def create_agent_sandbox(self, thread_id: str, user_id: str) -> DaytonaSandbox:
        """基于全局 Skills 快照创建沙箱"""
        snapshot_id = get_snapshot_manager().get_current_snapshot_id()
        
        sandbox = self._client.create(CreateSandboxFromSnapshotParams(
            snapshot_id=snapshot_id,
            labels={"type": "agent", "thread_id": thread_id, "user_id": user_id},
            auto_stop_interval=settings.DAYTONA_AUTO_STOP_INTERVAL,
            auto_delete_interval=settings.DAYTONA_AUTO_STOP_INTERVAL * 2,
        ))
        return DaytonaSandbox(sandbox=sandbox)
    
    def find_sandbox(self, labels: dict) -> Sandbox | None:
        """根据标签查找沙箱"""
        try:
            return self._client.find_one(labels=labels)
        except Exception:
            return None
    
    def get_or_create_sandbox(self, thread_id: str, user_id: str) -> DaytonaSandbox:
        """获取或创建沙箱（支持会话恢复）"""
        existing = self.find_sandbox({"thread_id": thread_id})
        if existing:
            return DaytonaSandbox(sandbox=existing)
        return self.create_agent_sandbox(thread_id, user_id)
```

#### 3.3.2 `src/agent_manager.py` 改动详情

**改动原因**：
- 使用 CompositeBackend 替代单一后端
- Backend 工厂需要 user_id 和 thread_id

**改动前**：
```python
self.compiled_agent = create_deep_agent(
    model=big_llm,
    backend=lambda runtime: get_sandbox_manager().get_thread_backend(
        self._get_thread_id(runtime) or "default"
    ),
    skills=[settings.CONTAINER_SKILLS_DIR],
    ...
)
```

**改动后**：
```python
from src.backends.composite import create_backend_factory

# 在 stream_chat 中传递 user_id
config = {
    "configurable": {
        "thread_id": thread_id,
        "user_id": user_id,  # 新增
    },
    ...
}

# init 中
self.compiled_agent = create_deep_agent(
    model=big_llm,
    backend=lambda runtime: create_backend_factory(
        user_id=runtime.config.get("configurable", {}).get("user_id"),
        thread_id=runtime.config.get("configurable", {}).get("thread_id"),
    )(runtime),
    # skills 参数移除，通过快照内置
    ...
)
```

#### 3.3.3 `src/webdav.py` 改动详情

**改动原因**：
- WebDAV 操作本地文件，而非 Daytona
- 简化实现，移除对沙箱的依赖

**改动前**：
```python
from src.daytona_sandbox_manager import get_sandbox_manager

class WebDAVHandler:
    def _get_sandbox(self, user_id: str):
        return self._sandbox_manager.get_files_backend(user_id)
    
    async def get(self, user_id: str, path: str):
        sandbox = self._get_sandbox(user_id)
        content = sandbox.fs_download(path)
        ...
```

**改动后**：
```python
from pathlib import Path

class WebDAVHandler:
    def __init__(self):
        self._base_dir = Path(settings.WORKSPACE_BASE_DIR)
    
    def _get_user_dir(self, user_id: str) -> Path:
        return self._base_dir / user_id / "workspace"
    
    def _get_path(self, user_id: str, path: str) -> Path:
        return self._get_user_dir(user_id) / path
    
    async def get(self, user_id: str, path: str) -> StreamingResponse:
        file_path = self._get_path(user_id, path)
        if not file_path.exists():
            raise HTTPException(status_code=404, detail="Not found")
        
        def iter_content():
            yield file_path.read_bytes()
        
        return StreamingResponse(iter_content(), media_type="application/octet-stream")
    
    async def put(self, user_id: str, path: str, body: bytes) -> Response:
        file_path = self._get_path(user_id, path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_bytes(body)
        return Response(status_code=201)
    
    async def propfind(self, user_id: str, path: str, depth: int = 1) -> Response:
        dir_path = self._get_path(user_id, path)
        files = list(dir_path.iterdir()) if dir_path.exists() else []
        # 构建 XML 响应...
```

#### 3.3.4 `src/config.py` 改动详情

**新增配置**：
```python
# 工作空间配置
WORKSPACE_BASE_DIR: str = "/mutli-user-agent"
SKILLS_DIR: str = "/mutli-user-agent/skills"

# Daytona
DAYTONA_API_KEY: str
DAYTONA_API_URL: str
DAYTONA_AUTO_STOP_INTERVAL: int = 15  # 分钟
DAYTONA_SKILLS_SNAPSHOT_ID: str = ""  # 全局 Skills 快照 ID
```

#### 3.3.5 `src/skill_validator.py` 改动详情

**新增逻辑**：
```python
from src.snapshot_manager import get_snapshot_manager

class SkillValidator:
    async def _on_validation_complete(self, skill_id: str, approved: bool):
        if approved:
            # 触发快照重建
            await get_snapshot_manager().rebuild_skills_snapshot()
```

#### 3.3.6 `pyproject.toml` 改动详情

```diff
dependencies = [
    ...
    "daytona>=0.143.0",
+   "langchain-daytona>=0.1.0",
]
```

---

## 四、核心模块实现

### 4.1 `src/backends/composite.py`

```python
"""CompositeBackend 工厂函数"""
from deepagents.backends import CompositeBackend, StateBackend, FilesystemBackend
from langchain_daytona import DaytonaSandbox
from src.config import settings
from src.daytona_client import get_daytona_client


def create_backend_factory(user_id: str, thread_id: str):
    """
    创建 CompositeBackend 工厂函数
    
    路由规则：
    - /workspace/* → FilesystemBackend (本地用户工作区，只读预览)
    - /commod_workspace/* → DaytonaSandbox (沙箱执行环境，含 Skills)
    - 其他路径 → StateBackend (临时状态)
    """
    def factory(runtime) -> CompositeBackend:
        client = get_daytona_client()
        daytona_backend = client.get_or_create_sandbox(thread_id, user_id)
        
        return CompositeBackend(
            default=StateBackend(runtime),
            routes={
                "/workspace/": FilesystemBackend(
                    root_dir=f"{settings.WORKSPACE_BASE_DIR}/{user_id}/workspace",
                    virtual_mode=True
                ),
                "/commod_workspace/": daytona_backend,
            }
        )
    
    return factory
```

### 4.2 `src/snapshot_manager.py`

```python
"""Skills 快照管理服务"""
import logging
from datetime import datetime
from pathlib import Path

from daytona import CreateSandboxFromSnapshotParams
from langchain_daytona import DaytonaSandbox

from src.config import settings
from src.daytona_client import get_daytona_client
from src.database import SessionLocal, Skill

logger = logging.getLogger(__name__)


class SnapshotManager:
    """管理全局 Skills 快照"""
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._client = get_daytona_client().client
            cls._instance._current_snapshot_id: str | None = None
        return cls._instance
    
    def get_current_snapshot_id(self) -> str:
        """获取当前快照 ID，优先从配置读取"""
        if self._current_snapshot_id:
            return self._current_snapshot_id
        
        # 从配置读取
        if settings.DAYTONA_SKILLS_SNAPSHOT_ID:
            self._current_snapshot_id = settings.DAYTONA_SKILLS_SNAPSHOT_ID
            return self._current_snapshot_id
        
        # 如果没有快照，返回 None（使用默认镜像）
        logger.warning("[SnapshotManager] No skills snapshot configured, using default image")
        return None
    
    def rebuild_skills_snapshot(self) -> str:
        """
        重建包含所有已验证 Skills 的快照
        
        流程：
        1. 创建临时沙箱
        2. 上传所有已验证的 Skills
        3. 创建快照
        4. 清理旧快照
        5. 更新当前快照 ID
        """
        logger.info("[SnapshotManager] Starting skills snapshot rebuild...")
        
        # 1. 获取所有已验证的 Skills
        with SessionLocal() as db:
            approved_skills = db.query(Skill).filter(
                Skill.status == "approved"
            ).all()
        
        if not approved_skills:
            logger.warning("[SnapshotManager] No approved skills, skipping snapshot rebuild")
            return self._current_snapshot_id or ""
        
        # 2. 创建临时沙箱
        sandbox = self._client.create()
        logger.info(f"[SnapshotManager] Created temporary sandbox {sandbox.id}")
        
        try:
            # 3. 上传所有 Skills 到沙箱
            for skill in approved_skills:
                skill_path = Path(settings.SKILLS_DIR) / skill.name
                if skill_path.exists():
                    self._upload_skill_to_sandbox(sandbox, skill_path)
                    logger.info(f"[SnapshotManager] Uploaded skill: {skill.name}")
            
            # 4. 创建快照
            snapshot_name = f"skills-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
            snapshot = self._client.create_snapshot(sandbox.id, name=snapshot_name)
            logger.info(f"[SnapshotManager] Created snapshot: {snapshot.id}")
            
            # 5. 更新当前快照 ID
            old_snapshot_id = self._current_snapshot_id
            self._current_snapshot_id = snapshot.id
            
            # 6. 清理旧快照（保留最近 3 个）
            self._cleanup_old_snapshots(keep=3)
            
            # 7. 更新配置（可选：持久化到数据库）
            self._save_snapshot_id(snapshot.id)
            
            return snapshot.id
            
        finally:
            # 清理临时沙箱
            self._client.delete(sandbox)
            logger.info(f"[SnapshotManager] Cleaned up temporary sandbox")
    
    def _upload_skill_to_sandbox(self, sandbox, skill_path: Path):
        """上传单个 Skill 到沙箱 /skills/ 目录"""
        for file_path in skill_path.rglob("*"):
            if file_path.is_file():
                relative_path = file_path.relative_to(skill_path.parent)
                sandbox_path = f"/skills/{relative_path}"
                content = file_path.read_bytes()
                sandbox.fs.upload_file(content, sandbox_path)
    
    def _cleanup_old_snapshots(self, keep: int = 3):
        """清理旧快照，保留最近的 N 个"""
        try:
            snapshots = self._client.list_snapshots()
            skills_snapshots = [s for s in snapshots if s.name.startswith("skills-")]
            skills_snapshots.sort(key=lambda x: x.created_at, reverse=True)
            
            for snapshot in skills_snapshots[keep:]:
                self._client.delete_snapshot(snapshot.id)
                logger.info(f"[SnapshotManager] Deleted old snapshot: {snapshot.id}")
        except Exception as e:
            logger.warning(f"[SnapshotManager] Failed to cleanup old snapshots: {e}")
    
    def _save_snapshot_id(self, snapshot_id: str):
        """保存快照 ID（更新 .env 或数据库）"""
        # 方案1: 更新 .env 文件
        # 方案2: 保存到数据库配置表
        # 这里选择更新内存中的配置，重启后从 .env 读取
        self._current_snapshot_id = snapshot_id
        logger.info(f"[SnapshotManager] Saved snapshot ID: {snapshot_id}")


def get_snapshot_manager() -> SnapshotManager:
    return SnapshotManager()
```

### 4.3 `src/workspace_sync.py`

```python
"""本地 ↔ Daytona 文件同步服务"""
import logging
from pathlib import Path
from enum import Enum

from langchain_daytona import DaytonaSandbox

from src.config import settings

logger = logging.getLogger(__name__)


class SyncDirection(str, Enum):
    TO_DAYTONA = "to_daytona"
    FROM_DAYTONA = "from_daytona"


class WorkspaceSyncService:
    """文件同步服务"""
    
    def __init__(self):
        self._base_dir = Path(settings.WORKSPACE_BASE_DIR)
    
    def _get_user_workspace(self, user_id: str) -> Path:
        return self._base_dir / user_id / "workspace"
    
    def sync_to_daytona(
        self, 
        user_id: str, 
        sandbox: DaytonaSandbox, 
        paths: list[str]
    ) -> dict:
        """
        同步本地文件到 Daytona 沙箱
        
        Args:
            user_id: 用户 ID
            sandbox: Daytona 沙箱实例
            paths: 相对路径列表，如 ["src/", "data/file.csv"]
        
        Returns:
            {"synced": 5, "failed": 1, "errors": [...]}
        """
        workspace = self._get_user_workspace(user_id)
        files = []
        errors = []
        
        for path in paths:
            local_path = workspace / path
            
            if local_path.is_file():
                try:
                    files.append((
                        f"/commod_workspace/{path}",
                        local_path.read_bytes()
                    ))
                except Exception as e:
                    errors.append({"path": path, "error": str(e)})
            
            elif local_path.is_dir():
                for file_path in local_path.rglob("*"):
                    if file_path.is_file():
                        relative = file_path.relative_to(workspace)
                        try:
                            files.append((
                                f"/commod_workspace/{relative}",
                                file_path.read_bytes()
                            ))
                        except Exception as e:
                            errors.append({"path": str(relative), "error": str(e)})
        
        if files:
            results = sandbox.upload_files(files)
            failed = sum(1 for r in results if r.error)
        else:
            failed = 0
        
        logger.info(f"[WorkspaceSync] Synced {len(files)} files to Daytona, {failed} failed")
        
        return {
            "synced": len(files) - failed,
            "failed": failed,
            "errors": errors
        }
    
    def sync_from_daytona(
        self, 
        user_id: str, 
        sandbox: DaytonaSandbox, 
        paths: list[str]
    ) -> dict:
        """
        从 Daytona 沙箱同步文件到本地
        
        Args:
            user_id: 用户 ID
            sandbox: Daytona 沙箱实例
            paths: 相对路径列表
        
        Returns:
            {"synced": 5, "failed": 1, "errors": [...]}
        """
        workspace = self._get_user_workspace(user_id)
        sandbox_paths = [f"/commod_workspace/{p}" for p in paths]
        
        results = sandbox.download_files(sandbox_paths)
        
        synced = 0
        failed = 0
        errors = []
        
        for result in results:
            if result.content is not None:
                relative_path = result.path.replace("/commod_workspace/", "")
                local_path = workspace / relative_path
                try:
                    local_path.parent.mkdir(parents=True, exist_ok=True)
                    local_path.write_bytes(result.content)
                    synced += 1
                except Exception as e:
                    failed += 1
                    errors.append({"path": relative_path, "error": str(e)})
            else:
                failed += 1
                errors.append({"path": result.path, "error": result.error or "download failed"})
        
        logger.info(f"[WorkspaceSync] Synced {synced} files from Daytona, {failed} failed")
        
        return {
            "synced": synced,
            "failed": failed,
            "errors": errors
        }


def get_sync_service() -> WorkspaceSyncService:
    return WorkspaceSyncService()
```

### 4.4 `api/workspace.py`

```python
"""工作区文件同步 API"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Literal

from src.auth import get_current_user
from src.daytona_client import get_daytona_client
from src.workspace_sync import get_sync_service, SyncDirection

router = APIRouter(prefix="/api/workspace", tags=["workspace"])


class SyncRequest(BaseModel):
    direction: Literal["to_daytona", "from_daytona"]
    paths: list[str]  # 相对路径列表


class SyncResponse(BaseModel):
    status: str
    synced: int
    failed: int
    errors: list[dict]


@router.post("/threads/{thread_id}/sync", response_model=SyncResponse)
async def sync_workspace(
    thread_id: str,
    request: SyncRequest,
    user_id: str = Depends(get_current_user)
):
    """
    同步工作区文件
    
    - direction: "to_daytona" (上传到沙箱) 或 "from_daytona" (下载到本地)
    - paths: 要同步的文件/目录路径列表
    """
    # 验证 thread_id 归属
    if not thread_id.startswith(f"{user_id}-"):
        raise HTTPException(status_code=403, detail="Access denied")
    
    # 获取或创建沙箱
    client = get_daytona_client()
    sandbox = client.get_or_create_sandbox(thread_id, user_id)
    
    sync_service = get_sync_service()
    
    if request.direction == "to_daytona":
        result = sync_service.sync_to_daytona(user_id, sandbox, request.paths)
    else:
        result = sync_service.sync_from_daytona(user_id, sandbox, request.paths)
    
    return SyncResponse(
        status="completed",
        synced=result["synced"],
        failed=result["failed"],
        errors=result["errors"]
    )


@router.get("/threads/{thread_id}/sandbox/status")
async def get_sandbox_status(
    thread_id: str,
    user_id: str = Depends(get_current_user)
):
    """获取沙箱状态"""
    if not thread_id.startswith(f"{user_id}-"):
        raise HTTPException(status_code=403, detail="Access denied")
    
    client = get_daytona_client()
    sandbox = client.find_sandbox({"thread_id": thread_id})
    
    if sandbox is None:
        return {"exists": False, "status": "not_created"}
    
    return {
        "exists": True,
        "status": sandbox.state,
        "sandbox_id": sandbox.id
    }
```

---

## 五、API 变更说明

### 5.1 新增 API

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/workspace/threads/{thread_id}/sync` | 同步文件到/从沙箱 |
| GET | `/api/workspace/threads/{thread_id}/sandbox/status` | 获取沙箱状态 |

### 5.2 变更 API

| 方法 | 路径 | 变更 |
|------|------|------|
| POST | `/api/chat` | 请求体新增可选字段 `sync_paths: list[str]`（自动同步） |

### 5.3 不变 API

| 方法 | 路径 | 说明 |
|------|------|------|
| PROPFIND/GET/PUT/DELETE | `/dav/{user_id}/{path}` | WebDAV 接口不变，但操作本地文件 |

---

## 六、测试方案

### 6.1 单元测试

| 测试文件 | 测试内容 |
|----------|----------|
| `tests/test_backends_composite.py` | CompositeBackend 路由测试 |
| `tests/test_snapshot_manager.py` | 快照创建/删除/恢复测试 |
| `tests/test_workspace_sync.py` | 文件同步测试 |
| `tests/test_webdav_local.py` | WebDAV 本地文件操作测试 |

### 6.2 集成测试

```python
# tests/test_integration_v021.py

class TestDaytonaIntegration:
    """Daytona 集成测试"""
    
    def test_create_sandbox_with_snapshot(self):
        """测试基于快照创建沙箱"""
        client = get_daytona_client()
        sandbox = client.create_agent_sandbox("test-thread", "test-user")
        
        # 验证沙箱存在
        assert sandbox.id is not None
        
        # 验证 skills 目录存在
        result = sandbox.execute("ls /skills")
        assert result.exit_code == 0
        
        # 清理
        client.client.delete(sandbox._sandbox)
    
    def test_file_sync_to_daytona(self):
        """测试文件同步到沙箱"""
        # 1. 创建测试文件
        # 2. 同步到沙箱
        # 3. 验证沙箱中存在文件
        pass
    
    def test_file_sync_from_daytona(self):
        """测试从沙箱同步文件"""
        # 1. 在沙箱中创建文件
        # 2. 同步到本地
        # 3. 验证本地存在文件
        pass
    
    def test_webdav_local_operations(self):
        """测试 WebDAV 本地文件操作"""
        # 1. PUT 文件
        # 2. GET 文件
        # 3. DELETE 文件
        pass
    
    def test_skill_execution_in_sandbox(self):
        """测试 Skill 在沙箱中执行"""
        # 1. 验证 skill 存在于 /skills/
        # 2. 执行 skill 脚本
        # 3. 验证执行结果
        pass
```

### 6.3 手动测试清单

- [ ] 创建新会话，验证沙箱自动创建
- [ ] 上传文件到 WebDAV，验证本地存储
- [ ] 调用同步 API，验证文件传输到沙箱
- [ ] Agent 执行命令，验证在沙箱中运行
- [ ] 验证 Skills 可被读取和执行
- [ ] 会话恢复，验证沙箱复用
- [ ] 等待 auto_stop_interval，验证沙箱自动停止
- [ ] Skill 验证通过，验证快照重建

---

## 七、前端变更说明

### 7.1 需要修改

| 功能 | 变更 |
|------|------|
| **会话初始化** | 新增可选步骤：选择要同步的文件/目录 |
| **文件操作** | WebDAV 行为不变，但提示用户需要同步到沙箱才能执行 |
| **沙箱状态** | 可选：显示沙箱运行状态 |

### 7.2 新增 API 调用

```typescript
// 同步文件到沙箱（会话开始时调用）
async function syncToSandbox(threadId: string, paths: string[]) {
  const response = await fetch(`/api/workspace/threads/${threadId}/sync`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      direction: 'to_daytona',
      paths: paths
    })
  });
  return response.json();
}

// 从沙箱同步文件（会话结束时调用）
async function syncFromSandbox(threadId: string, paths: string[]) {
  const response = await fetch(`/api/workspace/threads/${threadId}/sync`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      direction: 'from_daytona',
      paths: paths
    })
  });
  return response.json();
}

// 获取沙箱状态
async function getSandboxStatus(threadId: string) {
  const response = await fetch(`/api/workspace/threads/${threadId}/sandbox/status`);
  return response.json();
}
```

### 7.3 前端实现建议

**方案 A：自动同步（推荐）**
- 会话开始时，自动同步 WebDAV 目录下的所有文件
- 用户体验无感知

**方案 B：手动同步**
- 会话开始时，弹窗让用户选择要同步的目录
- 适合大文件场景

**方案 C：按需同步**
- Agent 需要文件时，自动触发同步
- 需要后端配合

### 7.4 UI 变更建议

```
会话界面
├── 文件浏览器（WebDAV）
│   └── 右键菜单新增：[同步到沙箱]
├── 沙箱状态指示器（可选）
│   ├── 🟢 运行中
│   ├── 🟡 已停止
│   └── ⚪ 未创建
└── 会话设置
    └── 自动同步开关
```

---

## 八、风险评估

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|----------|
| langchain-daytona 不稳定 | 低 | 高 | 保留回滚能力，充分测试 |
| 快照创建失败 | 中 | 中 | 降级到默认镜像，记录日志 |
| 文件同步大文件超时 | 中 | 低 | 限制单文件大小，分批同步 |
| 沙箱启动慢 | 低 | 中 | 添加加载状态提示 |

---

## 九、实施计划

### 阶段一：核心重构（2小时）

| 步骤 | 任务 | 文件 |
|------|------|------|
| 1 | 添加依赖 | `pyproject.toml` |
| 2 | 精简 Daytona 客户端 | `src/daytona_client.py` |
| 3 | 创建 Backend 工厂 | `src/backends/composite.py` |
| 4 | 重写 WebDAV | `src/webdav.py` |
| 5 | 修改 Agent Manager | `src/agent_manager.py` |

### 阶段二：快照管理（1小时）

| 步骤 | 任务 | 文件 |
|------|------|------|
| 6 | 创建快照管理器 | `src/snapshot_manager.py` |
| 7 | 修改 Skill 验证器 | `src/skill_validator.py` |
| 8 | 更新配置 | `src/config.py` |

### 阶段三：文件同步（1小时）

| 步骤 | 任务 | 文件 |
|------|------|------|
| 9 | 创建同步服务 | `src/workspace_sync.py` |
| 10 | 创建同步 API | `api/workspace.py` |
| 11 | 注册路由 | `api/__init__.py` |

### 阶段四：清理与测试（1小时）

| 步骤 | 任务 | 文件 |
|------|------|------|
| 12 | 删除旧文件 | `src/daytona_sandbox.py`, `src/daytona_sandbox_manager.py` |
| 13 | 更新测试 | `tests/` |
| 14 | 集成测试 | 手动测试 |
| 15 | 更新文档 | `AGENTS.md` |

---

## 十、验收标准

- [ ] 所有旧代码已删除
- [ ] Agent 可正常创建会话
- [ ] WebDAV 可正常操作本地文件
- [ ] 文件同步 API 正常工作
- [ ] Skills 通过快照内置到沙箱
- [ ] Skills 可在沙箱中正常执行
- [ ] 会话恢复时沙箱可复用
- [ ] 沙箱自动停止/删除正常
- [ ] 所有测试通过

---

## 十一、决策记录

| 决策点 | 选择 | 理由 |
|--------|------|------|
| Skills 存储 | Daytona 快照 | 解决沙箱无法访问本地 Skills 的问题 |
| WebDAV 目标 | 本地文件系统 | 持久化无需沙箱运行，降低成本 |
| 沙箱生命周期 | 官方自动管理 | 减少代码复杂度 |
| 文件同步时机 | 会话级初始化 | 用户可控，适合大文件场景 |
| 快照管理位置 | Skill 验证模块 | 验证通过后立即更新，逻辑内聚 |
