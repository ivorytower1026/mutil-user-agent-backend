# Daytona 沙箱重构方案（极简版）

> 版本: 2.0
> 日期: 2026-02-20
> 状态: 待审核

---

## 一、背景与目标

### 1.1 当前架构

```
┌─────────────────┐
│   FastAPI       │
│   Backend       │
└────────┬────────┘
         │
┌────────▼────────┐
│ DockerSandbox   │  ← 本地 Docker 容器
│ - 每用户一容器   │
│ - 本地文件系统   │
│ - docker save   │
└─────────────────┘
```

### 1.2 目标架构

```
┌─────────────────┐
│   FastAPI       │
│   Backend       │
└────────┬────────┘
         │
┌────────▼────────┐
│ DaytonaSandbox  │  ← Daytona 托管沙箱
│ - 每线程一沙箱   │
│ - Volume 自动管理│
│ - Snapshot 自动管理│
└────────┬────────┘
         │
┌────────▼────────┐
│ Daytona Server  │  ← 已部署
│   ├── MinIO     │  ← S3 存储
│   └── 自动管理   │  ← Volume/Snapshot
└─────────────────┘
```

### 1.3 重构收益

| 维度 | Docker | Daytona |
|------|--------|---------|
| 多线程并发 | 差（共享容器状态冲突） | 好（独立沙箱） |
| 资源利用 | 高（持续占用） | 优（auto-stop/delete） |
| 数据持久化 | 本地文件系统 | Daytona Volume (自动管理) |
| 镜像管理 | docker save/load | Daytona Snapshot (自动管理) |
| 扩展性 | 单机限制 | 可水平扩展 |
| **代码复杂度** | 中 | **极低** |

---

## 二、极简设计原则

### 2.1 核心理念：让 Daytona 管理一切

| 功能 | 谁管理 | 说明 |
|------|--------|------|
| Volume 创建/删除 | **Daytona** | 按需自动创建，name 区分用户 |
| Snapshot 创建/删除 | **Daytona** | 按需自动创建 |
| Sandbox 生命周期 | **Daytona** | auto-stop/auto-delete |
| Sandbox 业务映射 | **内存缓存** | thread_id → sandbox 实例 |
| 文件持久化 | **Daytona Volume** | 挂载到 /workspace |

### 2.2 我们只做一件事

```
thread_id → DaytonaSandboxBackend（内存缓存）
```

### 2.3 不需要的东西

- ❌ 数据库表（Volume、Snapshot、Sandbox 都不需要）
- ❌ VolumeManager
- ❌ SnapshotManager
- ❌ 复杂的状态同步

---

## 三、技术方案

### 3.1 多租户隔离方案

```
用户A
├── Volume: "user-abc12345" (Daytona 自动管理)
│
├── Thread-1 → Sandbox (labels: {thread_id, user_id, type: agent})
│   └── 挂载 Volume "user-abc12345" → /workspace
│   └── auto-stop: 15min
│
├── Thread-2 → Sandbox (labels: {thread_id, user_id, type: agent})
│   └── 挂载 Volume "user-abc12345" → /workspace
│   └── auto-stop: 15min
│
└── Files → Sandbox (labels: {user_id, type: files})
    └── 挂载 Volume "user-abc12345" → /workspace
    └── auto-stop: 60min
```

**Volume 命名规则**：`user-{user_id前8位}`

**Sandbox Labels**：
```python
{
    "type": "agent" | "files",
    "thread_id": "xxx",  # 仅 agent 类型
    "user_id": "xxx"
}
```

### 3.2 auto-stop 机制

Daytona 原生支持，无需我们管理：
- 有操作时自动刷新计时器
- 超时自动停止
- 再超时自动删除

### 3.3 文件操作机制

**Agent 文件操作**：通过 `execute()` 在沙箱内执行，无网络开销
```python
sandbox.process.exec("echo 'hello' > /workspace/file.txt")
```

**外部文件传输**：通过 Daytona FS API
```python
sandbox.fs.upload_file(content, "/workspace/path")
sandbox.fs.download_file("/workspace/path")
```

---

## 四、核心实现

### 4.1 文件清单

**只需要 3 个新文件：**

| 文件 | 功能 | 代码量 |
|------|------|--------|
| `src/daytona_client.py` | SDK 单例 | ~20 行 |
| `src/daytona_sandbox.py` | BaseSandbox 实现 | ~80 行 |
| `src/daytona_sandbox_manager.py` | 内存缓存管理 | ~80 行 |

**修改 3 个现有文件：**

| 文件 | 改动 |
|------|------|
| `src/config.py` | 添加 Daytona 配置 |
| `src/agent_manager.py` | 改用新 SandboxManager |
| `src/webdav.py` | 改用 Daytona FS API |

**删除 1 个文件：**
- `src/docker_sandbox.py`

### 4.2 配置项

```python
# src/config.py 添加

class Settings(BaseSettings):
    # Daytona 配置
    DAYTONA_API_KEY: str
    DAYTONA_API_URL: str = "http://localhost:3000/api"
    
    # Agent Sandbox 生命周期（分钟）
    DAYTONA_AUTO_STOP_INTERVAL: int = 15
    
    # Files Sandbox 生命周期（分钟）
    DAYTONA_FILES_SANDBOX_AUTO_STOP: int = 60
```

### 4.3 核心类设计

#### DaytonaClient（单例）

```python
# src/daytona_client.py

from daytona import Daytona, DaytonaConfig
from src.config import settings


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


def get_daytona_client() -> DaytonaClient:
    return DaytonaClient()
```

#### DaytonaSandboxBackend

```python
# src/daytona_sandbox.py

from deepagents.backends.sandbox import BaseSandbox
from deepagents.backends.protocol import (
    ExecuteResponse,
    FileUploadResponse,
    FileDownloadResponse,
)


class DaytonaSandboxBackend(BaseSandbox):
    def __init__(self, sandbox_id: str, sandbox):
        self.sandbox_id = sandbox_id
        self._sandbox = sandbox
    
    @property
    def id(self) -> str:
        return self.sandbox_id
    
    def execute(self, command: str) -> ExecuteResponse:
        response = self._sandbox.process.exec(command, timeout=300)
        return ExecuteResponse(
            output=response.result,
            exit_code=response.exit_code,
            truncated=False
        )
    
    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        results = []
        for file_path, content in files:
            try:
                self._sandbox.fs.upload_file(content, f"/workspace/{file_path}")
                results.append(FileUploadResponse(path=file_path, error=None))
            except Exception as e:
                results.append(FileUploadResponse(path=file_path, error=str(e)))
        return results
    
    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        results = []
        for file_path in paths:
            try:
                content = self._sandbox.fs.download_file(f"/workspace/{file_path}")
                results.append(FileDownloadResponse(path=file_path, content=content, error=None))
            except Exception as e:
                results.append(FileDownloadResponse(path=file_path, content=None, error=str(e)))
        return results
    
    # Files Sandbox 专用方法
    def fs_download(self, path: str) -> bytes:
        return self._sandbox.fs.download_file(f"/workspace/{path}")
    
    def fs_upload(self, path: str, content: bytes):
        self._sandbox.fs.upload_file(content, f"/workspace/{path}")
    
    def fs_list(self, path: str) -> list:
        return self._sandbox.fs.list_files(f"/workspace/{path}")
    
    def fs_delete(self, path: str):
        self._sandbox.fs.delete_file(f"/workspace/{path}")
    
    def destroy(self):
        from src.daytona_client import get_daytona_client
        get_daytona_client().client.delete(self._sandbox)
```

#### DaytonaSandboxManager（纯内存缓存）

```python
# src/daytona_sandbox_manager.py

from daytona import CreateSandboxParams, VolumeMount
from src.config import settings
from src.daytona_client import get_daytona_client
from src.daytona_sandbox import DaytonaSandboxBackend


class DaytonaSandboxManager:
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._client = get_daytona_client().client
            cls._instance._agent_sandboxes = {}  # thread_id -> backend
            cls._instance._files_sandboxes = {}  # user_id -> backend
        return cls._instance
    
    def get_thread_backend(self, thread_id: str) -> DaytonaSandboxBackend:
        """获取 Agent Sandbox（每线程一个）"""
        if thread_id in self._agent_sandboxes:
            return self._agent_sandboxes[thread_id]
        
        user_id = self._extract_user_id(thread_id)
        sandbox = self._client.create(CreateSandboxParams(
            volumes=[VolumeMount(
                name=f"user-{user_id[:8]}",
                mount_path="/workspace"
            )],
            auto_stop_interval=settings.DAYTONA_AUTO_STOP_INTERVAL,
            labels={"type": "agent", "thread_id": thread_id, "user_id": user_id}
        ))
        
        backend = DaytonaSandboxBackend(thread_id, sandbox)
        self._agent_sandboxes[thread_id] = backend
        return backend
    
    def get_files_backend(self, user_id: str) -> DaytonaSandboxBackend:
        """获取 Files Sandbox（每用户一个，按需创建）"""
        if user_id in self._files_sandboxes:
            return self._files_sandboxes[user_id]
        
        sandbox = self._client.create(CreateSandboxParams(
            volumes=[VolumeMount(
                name=f"user-{user_id[:8]}",
                mount_path="/workspace"
            )],
            auto_stop_interval=settings.DAYTONA_FILES_SANDBOX_AUTO_STOP,
            labels={"type": "files", "user_id": user_id}
        ))
        
        backend = DaytonaSandboxBackend(f"files-{user_id[:8]}", sandbox)
        self._files_sandboxes[user_id] = backend
        return backend
    
    def destroy_thread_backend(self, thread_id: str) -> bool:
        """销毁 Agent Sandbox"""
        if thread_id not in self._agent_sandboxes:
            return False
        self._agent_sandboxes[thread_id].destroy()
        del self._agent_sandboxes[thread_id]
        return True
    
    def _extract_user_id(self, thread_id: str) -> str:
        """从 thread_id 提取 user_id"""
        return thread_id[:36] if len(thread_id) > 36 else thread_id


def get_sandbox_manager() -> DaytonaSandboxManager:
    return DaytonaSandboxManager()
```

### 4.4 AgentManager 改动

```python
# src/agent_manager.py

# 原来
from src.docker_sandbox import get_thread_backend, destroy_thread_backend

# 改为
from src.daytona_sandbox_manager import get_sandbox_manager

# 使用
backend = get_sandbox_manager().get_thread_backend(thread_id)
get_sandbox_manager().destroy_thread_backend(thread_id)
```

### 4.5 WebDAV 改动

```python
# src/webdav.py

from src.daytona_sandbox_manager import get_sandbox_manager


class WebDAVHandler:
    async def get(self, user_id: str, path: str):
        sandbox = get_sandbox_manager().get_files_backend(user_id)
        content = sandbox.fs_download(path)
        # ...
    
    async def put(self, user_id: str, path: str, body: bytes):
        sandbox = get_sandbox_manager().get_files_backend(user_id)
        sandbox.fs_upload(path, body)
        # ...
    
    async def propfind(self, user_id: str, path: str):
        sandbox = get_sandbox_manager().get_files_backend(user_id)
        files = sandbox.fs_list(path)
        # ...
```

---

## 五、实施步骤

### Step 1: 配置和依赖 (5 分钟)

1. 更新 `src/config.py` 添加 Daytona 配置
2. 更新 `.env` 添加 `DAYTONA_API_KEY` 和 `DAYTONA_API_URL`
3. 更新 `pyproject.toml` 移除 docker，添加 daytona-sdk
4. 运行 `uv sync`

### Step 2: 核心文件 (30 分钟)

1. 创建 `src/daytona_client.py`
2. 创建 `src/daytona_sandbox.py`
3. 创建 `src/daytona_sandbox_manager.py`

### Step 3: 集成 (30 分钟)

1. 修改 `src/agent_manager.py`
2. 修改 `src/webdav.py`
3. 修改 `api/server.py`（destroy 调用）

### Step 4: 测试 (30 分钟)

1. 测试 Agent 执行
2. 测试 WebDAV 文件操作
3. 测试多线程隔离

### Step 5: 清理 (5 分钟)

1. 删除 `src/docker_sandbox.py`
2. 更新 `AGENTS.md`

---

## 六、与原方案对比

| 项目 | 原方案 | 极简方案 |
|------|--------|----------|
| 新建数据库表 | 3 个 | **0 个** |
| 新建 Python 文件 | 5 个 | **3 个** |
| 代码量 | ~500 行 | **~180 行** |
| 复杂度 | 中 | **极低** |
| 依赖 Daytona | 部分 | **完全** |

---

## 七、环境变量

```bash
# .env

# Daytona 配置
DAYTONA_API_KEY=dtn_xxx
DAYTONA_API_URL=http://localhost:3000/api

# Sandbox 生命周期（分钟）
DAYTONA_AUTO_STOP_INTERVAL=15
DAYTONA_FILES_SANDBOX_AUTO_STOP=60
```

---

## 八、验收标准

- [ ] Agent 能正常执行命令
- [ ] Agent 能正常读写文件
- [ ] WebDAV 能正常列出/上传/下载/删除文件
- [ ] 多线程隔离正常
- [ ] 旧代码已清理

---

## 九、决策记录

| 决策点 | 选择 | 理由 |
|--------|------|------|
| 数据库表 | 不创建 | Daytona 自己管理 Volume/Snapshot |
| 缓存策略 | 纯内存 | 简单，服务重启后自动重建 |
| Volume 命名 | `user-{id前8位}` | 简短且唯一 |
| Labels | 存储业务信息 | 便于调试和追踪 |
