# v0.2.1 官方 langchain-daytona 重构方案（最终版）

> 版本: 0.2.1
> 日期: 2026-02-21
> 状态: 待实施
> 作者: AI Agent

---

## 一、背景与目标

### 1.1 现有问题

| 问题 | 现状 | 影响 |
|------|------|------|
| 造轮子代码 | 自实现 `DaytonaSandboxBackend` | 官方 `langchain-daytona` 已提供 |
| 手动生命周期管理 | `DaytonaSandboxManager` 内存缓存 | Daytona SDK 原生支持自动管理 |
| Skills 无法执行 | Skills 在本地，沙箱在 Daytona | Agent 执行脚本时找不到文件 |
| WebDAV 依赖沙箱 | 操作 Daytona 文件 | 沙箱停止后无法操作 |
| 无文件同步 | 本地与沙箱文件隔离 | 用户需要手动管理 |

### 1.2 目标

1. ✅ 使用官方 `langchain-daytona` 替代自实现代码
2. ✅ 简化 Backend 为单一 `DaytonaSandbox`（不需要 CompositeBackend）
3. ✅ Skills 通过快照内置到沙箱，解决执行问题
4. ✅ WebDAV 操作本地文件，持久化无需沙箱
5. ✅ 实时双向文件同步，Agent 透明感知

---

## 二、最终架构

### 2.1 整体架构

```
┌──────────────────────────────────────────────────────────────────┐
│                         最终架构                                  │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Backend = DaytonaSandbox（单一后端，不需要 CompositeBackend）     │
│                                                                  │
│  ┌─────────────────┐         ┌─────────────────────────────┐    │
│  │   WebDAV        │         │      Daytona Sandbox         │    │
│  │   (本地文件)    │◄──同步──►│   /commod_workspace/         │    │
│  │   持久化存储    │         │   /skills/ (快照内置)        │    │
│  └─────────────────┘         └─────────────────────────────┘    │
│         │                              │                        │
│         │ PUT/DELETE                   │ 轮询(5s)               │
│         ▼                              ▼                        │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │              RealtimeFileSyncService                     │    │
│  │  - 本地→沙箱：WebDAV操作时直接同步                         │    │
│  │  - 沙箱→本地：轮询mod_time变化（每5秒）                    │    │
│  │  - 冲突处理：最后修改时间优先                               │    │
│  │  - Agent透明：直接读写沙箱，后台自动同步                    │    │
│  └─────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────┘
```

### 2.2 模块职责

| 模块 | 职责 |
|------|------|
| `DaytonaSandbox` (官方) | 提供 execute + 文件操作能力 |
| `DaytonaClient` | SDK 封装 + 沙箱创建 + 快照启动 |
| `SnapshotManager` | Skills 快照管理，验证通过后重建 |
| `WebDAVHandler` | 操作本地文件，触发同步 |
| `RealtimeFileSyncService` | 双向文件同步 |

### 2.3 数据流

```
用户上传文件 (WebDAV PUT)
    │
    ├──► 保存到本地: /mutli-user-agent/{user_id}/workspace/{path}
    │
    └──► 触发同步: RealtimeFileSyncService.sync_to_daytona()
            │
            └──► 上传到沙箱: /commod_workspace/{path}

Agent 执行命令
    │
    └──► 直接在沙箱执行 (已是最新文件)

沙箱文件变化 (Agent 写入)
    │
    └──► 轮询检测 mod_time 变化 (每5秒)
            │
            └──► 有变化则同步到本地
```

---

## 三、Skills 快照方案

### 3.1 快照生命周期

```
Skill 验证流程：
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

### 3.2 沙箱启动流程

```python
# 基于快照创建沙箱
sandbox = client.create(CreateSandboxFromSnapshotParams(
    snapshot_id=get_snapshot_manager().get_current_snapshot_id(),
    labels={"type": "agent", "thread_id": thread_id, "user_id": user_id},
    auto_stop_interval=15,  # 15分钟无操作停止
    auto_delete_interval=30, # 30分钟后删除
))
```

---

## 四、实时文件同步方案

### 4.1 同步策略

| 方向 | 触发方式 | 实现方式 | 说明 |
|------|----------|----------|------|
| 本地 → 沙箱 | WebDAV PUT/DELETE | 直接调用 `upload_files()` | 实时同步 |
| 沙箱 → 本地 | 后台轮询 (5s) | 检测 `mod_time` 变化 | 仅同步变化的文件 |

### 4.2 为什么不用 hash 检测？

| 方式 | 优点 | 缺点 |
|------|------|------|
| hash 检测 | 精确 | 需要下载文件内容计算，开销大 |
| **mod_time 检测** | 快速，不需下载 | 可能遗漏极短时间内多次修改 |

**选择 mod_time 检测**：性能优先，场景内足够准确。

### 4.3 冲突处理

```
本地和沙箱同时修改同一文件：
    │
    ├──► 比较最后修改时间 (mod_time)
    │
    └──► 保留最新的版本
```

### 4.4 同步范围

| 路径 | 是否同步 | 说明 |
|------|----------|------|
| `/commod_workspace/` | ✅ 同步 | 用户工作目录 |
| `/skills/` | ❌ 不同步 | 快照内置，只读 |
| 其他路径 | ❌ 不同步 | 临时文件 |

---

## 五、会话恢复策略

### 5.1 沙箱生命周期

```
┌───────────────┐
│   会话活跃     │ ──► 沙箱运行
└───────────────┘
        │
        │ 15分钟无操作
        ▼
┌───────────────┐
│   沙箱停止     │ ──► 状态保留
└───────────────┘
        │
        │ 30分钟后
        ▼
┌───────────────┐
│   沙箱删除     │ ──► 无法恢复
└───────────────┘
```

### 5.2 恢复策略

| 场景 | 沙箱状态 | 处理方式 |
|------|----------|----------|
| 沙箱运行中 | 运行 | 直接复用 |
| 沙箱已停止 | 停止 | 重启沙箱 |
| 沙箱已删除 | 不存在 | 重建沙箱 + 提示用户重新同步 |

---

## 六、文件变更清单

### 6.1 删除文件

| 文件 | 行数 | 删除原因 |
|------|------|----------|
| `src/daytona_sandbox.py` | ~97 | 官方 `langchain-daytona.DaytonaSandbox` 已实现 |
| `src/daytona_sandbox_manager.py` | ~120 | Daytona SDK 原生支持自动生命周期管理 |
| `tests/test_daytona_sandbox.py` | - | 旧测试不再适用 |

**减少代码量：~220 行**

### 6.2 新增文件

| 文件 | 功能 | 预计行数 |
|------|------|----------|
| `src/snapshot_manager.py` | Skills 快照管理服务 | ~80 |
| `src/workspace_sync.py` | 实时双向文件同步服务 | ~120 |
| `api/workspace.py` | 文件同步 API（手动同步保留） | ~50 |

**新增代码量：~250 行**

### 6.3 修改文件

| 文件 | 改动内容 | 改动量 |
|------|----------|--------|
| `src/daytona_client.py` | 精简 + 沙箱创建 + 快照支持 | 大改 |
| `src/webdav.py` | 本地文件操作 + 触发同步 | 大改 |
| `src/agent_manager.py` | Backend = DaytonaSandbox | 中改 |
| `src/config.py` | 新增配置项 | 小改 |
| `src/skill_validator.py` | 验证通过后触发快照重建 | 小改 |
| `pyproject.toml` | 添加 `langchain-daytona` | 小改 |
| `main.py` | 注册 workspace 路由 | 小改 |

---

## 七、核心模块实现

### 7.1 `src/daytona_client.py`

```python
"""Daytona SDK 封装 + 沙箱管理"""
from daytona import Daytona, DaytonaConfig, CreateSandboxFromSnapshotParams
from langchain_daytona import DaytonaSandbox
from src.config import settings


class DaytonaClient:
    """Daytona 客户端单例"""
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
        """基于 Skills 快照创建 Agent 沙箱"""
        from src.snapshot_manager import get_snapshot_manager
        
        snapshot_id = get_snapshot_manager().get_current_snapshot_id()
        params = CreateSandboxFromSnapshotParams(
            labels={"type": "agent", "thread_id": thread_id, "user_id": user_id},
            auto_stop_interval=settings.DAYTONA_AUTO_STOP_INTERVAL,
            auto_delete_interval=settings.DAYTONA_AUTO_STOP_INTERVAL * 2,
        )
        
        if snapshot_id:
            params.snapshot_id = snapshot_id
        
        sandbox = self._client.create(params)
        return DaytonaSandbox(sandbox=sandbox)
    
    def find_sandbox(self, labels: dict):
        """根据标签查找沙箱"""
        try:
            return self._client.find_one(labels=labels)
        except Exception:
            return None
    
    def get_or_create_sandbox(self, thread_id: str, user_id: str) -> DaytonaSandbox:
        """获取或创建沙箱（支持会话恢复）"""
        existing = self.find_sandbox({"thread_id": thread_id, "type": "agent"})
        if existing:
            return DaytonaSandbox(sandbox=existing)
        return self.create_agent_sandbox(thread_id, user_id)


def get_daytona_client() -> DaytonaClient:
    return DaytonaClient()
```

### 7.2 `src/snapshot_manager.py`

```python
"""Skills 快照管理服务"""
import logging
from datetime import datetime
from pathlib import Path

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
            cls._instance._current_snapshot_id: str | None = None
        return cls._instance
    
    def get_current_snapshot_id(self) -> str | None:
        """获取当前快照 ID"""
        if self._current_snapshot_id:
            return self._current_snapshot_id
        if settings.DAYTONA_SKILLS_SNAPSHOT_ID:
            self._current_snapshot_id = settings.DAYTONA_SKILLS_SNAPSHOT_ID
        return self._current_snapshot_id
    
    def rebuild_skills_snapshot(self) -> str | None:
        """重建包含所有已验证 Skills 的快照"""
        from src.daytona_client import get_daytona_client
        
        client = get_daytona_client().client
        
        # 1. 获取所有已验证的 Skills
        with SessionLocal() as db:
            approved_skills = db.query(Skill).filter(
                Skill.status == "approved"
            ).all()
        
        if not approved_skills:
            logger.warning("[SnapshotManager] No approved skills")
            return None
        
        # 2. 创建临时沙箱
        sandbox = client.create()
        logger.info(f"[SnapshotManager] Created temp sandbox {sandbox.id}")
        
        try:
            # 3. 上传所有 Skills
            for skill in approved_skills:
                skill_path = Path(settings.SKILLS_DIR) / skill.name
                if skill_path.exists():
                    self._upload_skill(sandbox, skill_path)
            
            # 4. 创建快照
            snapshot_name = f"skills-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
            snapshot = client.create_snapshot(sandbox.id, name=snapshot_name)
            logger.info(f"[SnapshotManager] Created snapshot {snapshot.id}")
            
            # 5. 更新当前快照 ID
            self._current_snapshot_id = snapshot.id
            
            # 6. 清理旧快照
            self._cleanup_old_snapshots(keep=3)
            
            return snapshot.id
            
        finally:
            client.delete(sandbox)
    
    def _upload_skill(self, sandbox, skill_path: Path):
        """上传单个 Skill 到 /skills/ 目录"""
        for file_path in skill_path.rglob("*"):
            if file_path.is_file():
                relative = file_path.relative_to(skill_path.parent)
                sandbox_path = f"/skills/{relative}"
                content = file_path.read_bytes()
                sandbox.fs.upload_file(content, sandbox_path)
    
    def _cleanup_old_snapshots(self, keep: int = 3):
        """清理旧快照"""
        try:
            client = get_daytona_client().client
            snapshots = client.list_snapshots()
            skills_snapshots = [s for s in snapshots if s.name.startswith("skills-")]
            skills_snapshots.sort(key=lambda x: x.created_at, reverse=True)
            
            for snapshot in skills_snapshots[keep:]:
                client.delete_snapshot(snapshot.id)
                logger.info(f"[SnapshotManager] Deleted old snapshot {snapshot.id}")
        except Exception as e:
            logger.warning(f"[SnapshotManager] Cleanup failed: {e}")


def get_snapshot_manager() -> SnapshotManager:
    return SnapshotManager()
```

### 7.3 `src/workspace_sync.py`

```python
"""实时双向文件同步服务"""
import asyncio
import logging
from pathlib import Path
from datetime import datetime

from langchain_daytona import DaytonaSandbox

from src.config import settings
from src.daytona_client import get_daytona_client

logger = logging.getLogger(__name__)

SYNC_WORKSPACE = "/commod_workspace"


class RealtimeFileSyncService:
    """实时双向文件同步"""
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._base_dir = Path(settings.WORKSPACE_BASE_DIR)
            cls._instance._sync_tasks: dict[str, asyncio.Task] = {}
            cls._instance._file_mtimes: dict[str, dict[str, float]] = {}  # thread_id -> {path: mtime}
        return cls._instance
    
    def _get_user_workspace(self, user_id: str) -> Path:
        return self._base_dir / user_id / "workspace"
    
    # ==================== 本地 → 沙箱（实时触发）====================
    
    def on_local_file_change(self, user_id: str, thread_id: str, path: str, content: bytes):
        """本地文件变化时触发（WebDAV PUT 调用）"""
        try:
            client = get_daytona_client()
            sandbox = client.get_or_create_sandbox(thread_id, user_id)
            sandbox.upload_files([(
                f"{SYNC_WORKSPACE}/{path}",
                content
            )])
            logger.info(f"[FileSync] Synced to sandbox: {path}")
        except Exception as e:
            logger.error(f"[FileSync] Sync to sandbox failed: {e}")
    
    def on_local_file_delete(self, user_id: str, thread_id: str, path: str):
        """本地文件删除时触发（WebDAV DELETE 调用）"""
        try:
            client = get_daytona_client()
            sandbox = client.get_or_create_sandbox(thread_id, user_id)
            sandbox._sandbox.fs.delete_file(f"{SYNC_WORKSPACE}/{path}")
            logger.info(f"[FileSync] Deleted from sandbox: {path}")
        except Exception as e:
            logger.error(f"[FileSync] Delete from sandbox failed: {e}")
    
    # ==================== 沙箱 → 本地（轮询检测）====================
    
    def start_polling(self, thread_id: str, user_id: str):
        """启动轮询任务"""
        if thread_id in self._sync_tasks:
            return
        
        task = asyncio.create_task(self._poll_sandbox_changes(thread_id, user_id))
        self._sync_tasks[thread_id] = task
        logger.info(f"[FileSync] Started polling for {thread_id}")
    
    def stop_polling(self, thread_id: str):
        """停止轮询任务"""
        if thread_id in self._sync_tasks:
            self._sync_tasks[thread_id].cancel()
            del self._sync_tasks[thread_id]
            logger.info(f"[FileSync] Stopped polling for {thread_id}")
    
    async def _poll_sandbox_changes(self, thread_id: str, user_id: str):
        """轮询检测沙箱文件变化（每5秒）"""
        while True:
            try:
                await asyncio.sleep(5)
                
                client = get_daytona_client()
                sandbox_info = client.find_sandbox({"thread_id": thread_id, "type": "agent"})
                
                if not sandbox_info:
                    continue
                
                sandbox = client.get_or_create_sandbox(thread_id, user_id)
                await self._check_and_sync_changes(sandbox, user_id, thread_id)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[FileSync] Polling error: {e}")
                await asyncio.sleep(10)  # 出错后等待更长时间
    
    async def _check_and_sync_changes(self, sandbox: DaytonaSandbox, user_id: str, thread_id: str):
        """检测并同步变化的文件"""
        local_workspace = self._get_user_workspace(user_id)
        
        # 获取沙箱文件列表
        try:
            files = sandbox._sandbox.fs.list_files(SYNC_WORKSPACE)
        except Exception:
            return
        
        # 初始化或获取该会话的 mtime 缓存
        if thread_id not in self._file_mtimes:
            self._file_mtimes[thread_id] = {}
        mtimes = self._file_mtimes[thread_id]
        
        changes = []
        for file_info in files:
            if file_info.is_dir:
                continue
            
            path = file_info.name
            remote_mtime = file_info.mod_time.timestamp() if file_info.mod_time else 0
            
            # 检测变化
            if path not in mtimes or mtimes[path] < remote_mtime:
                # 冲突检测：比较本地文件时间
                local_path = local_workspace / path
                if local_path.exists():
                    local_mtime = local_path.stat().st_mtime
                    if local_mtime > remote_mtime:
                        continue  # 本地更新，不同步
                
                changes.append(path)
                mtimes[path] = remote_mtime
        
        # 同步变化的文件
        if changes:
            await self._sync_from_sandbox(sandbox, user_id, changes)
    
    async def _sync_from_sandbox(self, sandbox: DaytonaSandbox, user_id: str, paths: list[str]):
        """从沙箱同步文件到本地"""
        local_workspace = self._get_user_workspace(user_id)
        sandbox_paths = [f"{SYNC_WORKSPACE}/{p}" for p in paths]
        
        try:
            results = sandbox.download_files(sandbox_paths)
            
            for result in results:
                if result.content:
                    relative = result.path.replace(f"{SYNC_WORKSPACE}/", "")
                    local_path = local_workspace / relative
                    local_path.parent.mkdir(parents=True, exist_ok=True)
                    local_path.write_bytes(result.content)
                    logger.info(f"[FileSync] Synced from sandbox: {relative}")
        except Exception as e:
            logger.error(f"[FileSync] Sync from sandbox failed: {e}")
    
    # ==================== 手动同步（API 调用）====================
    
    def sync_to_daytona(self, user_id: str, thread_id: str, paths: list[str]) -> dict:
        """手动同步本地文件到沙箱"""
        local_workspace = self._get_user_workspace(user_id)
        client = get_daytona_client()
        sandbox = client.get_or_create_sandbox(thread_id, user_id)
        
        files = []
        errors = []
        
        for path in paths:
            local_path = local_workspace / path
            if local_path.is_file():
                try:
                    files.append((f"{SYNC_WORKSPACE}/{path}", local_path.read_bytes()))
                except Exception as e:
                    errors.append({"path": path, "error": str(e)})
            elif local_path.is_dir():
                for fp in local_path.rglob("*"):
                    if fp.is_file():
                        relative = fp.relative_to(local_workspace)
                        try:
                            files.append((f"{SYNC_WORKSPACE}/{relative}", fp.read_bytes()))
                        except Exception as e:
                            errors.append({"path": str(relative), "error": str(e)})
        
        if files:
            results = sandbox.upload_files(files)
            failed = sum(1 for r in results if r.error)
        else:
            failed = 0
        
        return {"synced": len(files) - failed, "failed": failed, "errors": errors}
    
    def sync_from_daytona(self, user_id: str, thread_id: str, paths: list[str]) -> dict:
        """手动从沙箱同步文件到本地"""
        local_workspace = self._get_user_workspace(user_id)
        client = get_daytona_client()
        sandbox = client.get_or_create_sandbox(thread_id, user_id)
        
        sandbox_paths = [f"{SYNC_WORKSPACE}/{p}" for p in paths]
        results = sandbox.download_files(sandbox_paths)
        
        synced = 0
        failed = 0
        errors = []
        
        for result in results:
            if result.content:
                relative = result.path.replace(f"{SYNC_WORKSPACE}/", "")
                local_path = local_workspace / relative
                try:
                    local_path.parent.mkdir(parents=True, exist_ok=True)
                    local_path.write_bytes(result.content)
                    synced += 1
                except Exception as e:
                    failed += 1
                    errors.append({"path": relative, "error": str(e)})
            else:
                failed += 1
                errors.append({"path": result.path, "error": result.error or "download failed"})
        
        return {"synced": synced, "failed": failed, "errors": errors}


def get_sync_service() -> RealtimeFileSyncService:
    return RealtimeFileSyncService()
```

### 7.4 `src/webdav.py`

```python
"""WebDAV 处理器 - 操作本地文件系统"""
from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree as ET
from urllib.parse import quote
from io import BytesIO

from fastapi import HTTPException
from fastapi.responses import Response, StreamingResponse

from src.config import settings
from src.workspace_sync import get_sync_service


class WebDAVHandler:
    """WebDAV 协议处理器 - 本地文件系统"""
    
    WEBDAV_NS = "{DAV:}"
    
    def __init__(self):
        self._base_dir = Path(settings.WORKSPACE_BASE_DIR)
    
    def _get_user_dir(self, user_id: str) -> Path:
        return self._base_dir / user_id / "workspace"
    
    def _get_path(self, user_id: str, path: str) -> Path:
        return self._get_user_dir(user_id) / path
    
    def _format_datetime(self, dt: datetime) -> str:
        return dt.strftime("%a, %d %b %Y %H:%M:%S GMT")
    
    def _build_propfind_xml(self, user_id: str, path: str, files: list) -> str:
        ET.register_namespace('D', 'DAV:')
        multistatus = ET.Element(f"{self.WEBDAV_NS}multistatus")
        
        for file_info in files:
            self._add_response_element(multistatus, user_id, path, file_info)
        
        return '<?xml version="1.0" encoding="utf-8"?>' + ET.tostring(
            multistatus, encoding='unicode'
        )
    
    def _add_response_element(self, parent, user_id: str, base_path: str, file_info: dict):
        response = ET.SubElement(parent, f"{self.WEBDAV_NS}response")
        
        href = ET.SubElement(response, f"{self.WEBDAV_NS}href")
        name = file_info["name"]
        is_dir = file_info["is_dir"]
        href_path = f"/dav/{user_id}/{base_path}/{name}".replace("//", "/")
        if is_dir and not href_path.endswith('/'):
            href_path += '/'
        href.text = href_path
        
        propstat = ET.SubElement(response, f"{self.WEBDAV_NS}propstat")
        prop = ET.SubElement(propstat, f"{self.WEBDAV_NS}prop")
        
        displayname = ET.SubElement(prop, f"{self.WEBDAV_NS}displayname")
        displayname.text = name
        
        resourcetype = ET.SubElement(prop, f"{self.WEBDAV_NS}resourcetype")
        if is_dir:
            ET.SubElement(resourcetype, f"{self.WEBDAV_NS}collection")
        
        getlastmodified = ET.SubElement(prop, f"{self.WEBDAV_NS}getlastmodified")
        getlastmodified.text = self._format_datetime(file_info.get("mtime", datetime.now()))
        
        if not is_dir:
            getcontentlength = ET.SubElement(prop, f"{self.WEBDAV_NS}getcontentlength")
            getcontentlength.text = str(file_info.get("size", 0))
        
        status = ET.SubElement(propstat, f"{self.WEBDAV_NS}status")
        status.text = "HTTP/1.1 200 OK"
    
    async def propfind(self, user_id: str, path: str, depth: int = 1) -> Response:
        dir_path = self._get_path(user_id, path)
        
        files = []
        if dir_path.exists() and dir_path.is_dir():
            for item in dir_path.iterdir():
                files.append({
                    "name": item.name,
                    "is_dir": item.is_dir(),
                    "size": item.stat().st_size if item.is_file() else 0,
                    "mtime": datetime.fromtimestamp(item.stat().st_mtime)
                })
        
        xml = self._build_propfind_xml(user_id, path, files)
        return Response(
            content=xml,
            media_type="application/xml; charset=utf-8",
            status_code=207,
            headers={"DAV": "1"}
        )
    
    async def get(self, user_id: str, path: str) -> StreamingResponse:
        file_path = self._get_path(user_id, path)
        
        if not file_path.exists() or file_path.is_dir():
            raise HTTPException(status_code=404, detail="Not found")
        
        def iter_content():
            yield file_path.read_bytes()
        
        filename = path.split('/')[-1]
        filename_ascii = filename.encode('ascii', 'replace').decode('ascii')
        filename_utf8 = quote(filename, safe='')
        
        return StreamingResponse(
            iter_content(),
            media_type="application/octet-stream",
            headers={
                "Content-Disposition": f"attachment; filename=\"{filename_ascii}\"; filename*=UTF-8''{filename_utf8}"
            }
        )
    
    async def put(self, user_id: str, path: str, body: bytes, thread_id: str | None = None) -> Response:
        file_path = self._get_path(user_id, path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_bytes(body)
        
        # 触发同步到沙箱
        if thread_id:
            get_sync_service().on_local_file_change(user_id, thread_id, path, body)
        
        return Response(status_code=201)
    
    async def mkcol(self, user_id: str, path: str) -> Response:
        dir_path = self._get_path(user_id, path)
        dir_path.mkdir(parents=True, exist_ok=True)
        return Response(status_code=201)
    
    async def delete(self, user_id: str, path: str, thread_id: str | None = None) -> Response:
        file_path = self._get_path(user_id, path)
        
        if not file_path.exists():
            raise HTTPException(status_code=404, detail="Not found")
        
        if file_path.is_dir():
            import shutil
            shutil.rmtree(file_path)
        else:
            file_path.unlink()
        
        # 触发沙箱删除
        if thread_id:
            get_sync_service().on_local_file_delete(user_id, thread_id, path)
        
        return Response(status_code=204)
    
    async def move(self, user_id: str, src: str, dst: str) -> Response:
        src_path = self._get_path(user_id, src)
        dst_path = self._get_path(user_id, dst)
        
        if not src_path.exists():
            raise HTTPException(status_code=404, detail="Source not found")
        
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        src_path.rename(dst_path)
        
        return Response(status_code=201)
```

### 7.5 `api/workspace.py`

```python
"""工作区文件同步 API"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Literal

from src.auth import get_current_user
from src.workspace_sync import get_sync_service

router = APIRouter(prefix="/api/workspace", tags=["workspace"])


class SyncRequest(BaseModel):
    direction: Literal["to_daytona", "from_daytona"]
    paths: list[str]


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
    """手动同步工作区文件"""
    if not thread_id.startswith(f"{user_id}-"):
        raise HTTPException(status_code=403, detail="Access denied")
    
    sync_service = get_sync_service()
    
    if request.direction == "to_daytona":
        result = sync_service.sync_to_daytona(user_id, thread_id, request.paths)
    else:
        result = sync_service.sync_from_daytona(user_id, thread_id, request.paths)
    
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
    from src.daytona_client import get_daytona_client
    
    if not thread_id.startswith(f"{user_id}-"):
        raise HTTPException(status_code=403, detail="Access denied")
    
    client = get_daytona_client()
    sandbox = client.find_sandbox({"thread_id": thread_id, "type": "agent"})
    
    if sandbox is None:
        return {"exists": False, "status": "not_created"}
    
    return {
        "exists": True,
        "status": getattr(sandbox, "state", "unknown"),
        "sandbox_id": sandbox.id
    }
```

---

## 八、配置更新

### 8.1 `src/config.py` 新增配置

```python
# 工作空间配置
WORKSPACE_BASE_DIR: str = "/mutli-user-agent"
SKILLS_DIR: str = "/mutli-user-agent/skills"

# Daytona 配置
DAYTONA_API_KEY: str
DAYTONA_API_URL: str
DAYTONA_AUTO_STOP_INTERVAL: int = 15  # 分钟
DAYTONA_SKILLS_SNAPSHOT_ID: str = ""  # 全局 Skills 快照 ID

# 文件同步配置
SYNC_POLL_INTERVAL: int = 5  # 轮询间隔（秒）
```

### 8.2 `pyproject.toml` 新增依赖

```diff
dependencies = [
    ...
    "daytona>=0.143.0",
+   "langchain-daytona>=0.1.0",
]
```

---

## 九、测试方案

### 9.1 测试用例

| 测试项 | 测试内容 | 预期结果 |
|--------|----------|----------|
| 沙箱创建 | 创建新会话 | 基于快照创建成功 |
| WebDAV 上传 | PUT 文件 | 保存到本地 + 同步到沙箱 |
| WebDAV 下载 | GET 文件 | 从本地读取文件 |
| 实时同步 | WebDAV PUT 后 Agent 读取 | Agent 读到最新内容 |
| 轮询同步 | Agent 写入后等待 5 秒 | 本地文件自动更新 |
| Skills 执行 | Agent 执行 skill 脚本 | 脚本在沙箱中正常运行 |
| 快照重建 | Skill 验证通过 | 新快照创建成功 |
| 会话恢复 | 沙箱删除后继续对话 | 新沙箱创建 + 提示同步 |

### 9.2 手动测试流程

```bash
# 1. 启动服务
uv run python main.py

# 2. 创建会话
curl -X POST http://localhost:8002/api/threads \
  -H "Authorization: Bearer {token}" \
  -H "Content-Type: application/json" \
  -d '{}'

# 3. 上传文件 (WebDAV)
curl -X PUT http://localhost:8002/dav/{user_id}/test.py \
  -H "Authorization: Bearer {token}" \
  -d 'print("hello")'

# 4. 发送消息让 Agent 执行
curl -X POST http://localhost:8002/api/chat \
  -H "Authorization: Bearer {token}" \
  -H "Content-Type: application/json" \
  -d '{"thread_id": "{thread_id}", "message": "运行 test.py"}'

# 5. 检查沙箱状态
curl http://localhost:8002/api/workspace/threads/{thread_id}/sandbox/status \
  -H "Authorization: Bearer {token}"
```

---

## 十、实施计划

### 阶段一：核心重构（1.5 小时）

| 步骤 | 任务 | 文件 |
|------|------|------|
| 1 | 添加依赖 | `pyproject.toml` |
| 2 | 重写 Daytona 客户端 | `src/daytona_client.py` |
| 3 | 重写 WebDAV | `src/webdav.py` |
| 4 | 修改 Agent Manager | `src/agent_manager.py` |

### 阶段二：快照管理（0.5 小时）

| 步骤 | 任务 | 文件 |
|------|------|------|
| 5 | 创建快照管理器 | `src/snapshot_manager.py` |
| 6 | 修改 Skill 验证器 | `src/skill_validator.py` |
| 7 | 更新配置 | `src/config.py` |

### 阶段三：文件同步（1 小时）

| 步骤 | 任务 | 文件 |
|------|------|------|
| 8 | 创建同步服务 | `src/workspace_sync.py` |
| 9 | 创建同步 API | `api/workspace.py` |
| 10 | 注册路由 | `main.py` |

### 阶段四：清理与测试（0.5 小时）

| 步骤 | 任务 | 文件 |
|------|------|------|
| 11 | 删除旧文件 | `src/daytona_sandbox.py`, `src/daytona_sandbox_manager.py` |
| 12 | 更新测试 | `tests/` |
| 13 | 更新文档 | `AGENTS.md` |

---

## 十一、前端变更

### 11.1 API 变更

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/workspace/threads/{id}/sync` | 手动同步文件（可选） |
| GET | `/api/workspace/threads/{id}/sandbox/status` | 获取沙箱状态（可选） |

### 11.2 WebDAV 行为

- WebDAV 接口不变（`/dav/{user_id}/{path}`）
- 文件保存到本地，自动同步到沙箱
- 前端无需修改

### 11.3 可选增强

1. 显示沙箱状态指示器
2. 会话开始时自动同步
3. 右键菜单"同步到沙箱"

---

## 十二、决策记录

| 决策点 | 选择 | 理由 |
|--------|------|------|
| Backend 类型 | 单一 DaytonaSandbox | 简化架构，不需要 CompositeBackend |
| 同步方向 | 双向同步 | 本地↔沙箱互通 |
| 本地→沙箱 | WebDAV PUT 时触发 | 实时，无额外依赖 |
| 沙箱→本地 | 轮询 mod_time (5s) | 不需下载，高效 |
| 冲突处理 | 最后修改时间优先 | 简单有效 |
| Agent 感知 | 透明 | 后台自动处理 |
| Skills 存储 | 快照内置 | 解决沙箱无法访问本地 Skills |
| 会话恢复 | 重建沙箱 | 节省资源 |
| 快照管理 | Skill 验证模块 | 验证通过后立即更新 |
