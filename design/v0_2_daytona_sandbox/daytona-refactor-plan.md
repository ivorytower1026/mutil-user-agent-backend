# Daytona 沙箱重构方案

> 版本: 1.1
> 日期: 2026-02-19
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
│ - Volume 持久化 │
│ - Snapshot 管理 │
└────────┬────────┘
         │
┌────────▼────────┐
│ Daytona Server  │  ← 自托管
│   └── MinIO     │  ← S3 兼容存储
└─────────────────┘
```

### 1.3 重构收益

| 维度 | Docker | Daytona |
|------|--------|---------|
| 多线程并发 | 差（共享容器状态冲突） | 好（独立沙箱） |
| 资源利用 | 高（持续占用） | 优（auto-stop/delete） |
| 数据持久化 | 本地文件系统 | MinIO (S3) 云存储 |
| 镜像管理 | docker save/load | Snapshot API |
| 扩展性 | 单机限制 | 可水平扩展 |

---

## 二、技术方案

### 2.1 多租户隔离方案

**选择：每用户 Volume + 每线程动态 Sandbox + WebDAV 专用 Sandbox**

```
用户A
├── Volume-A (持久化到 MinIO)
│   ├── /workspace    # 工作目录
│   ├── /uploads      # 上传文件
│   └── /dependencies # 已安装依赖
│
├── Thread-1 → Sandbox-Agent-1 (挂载 Volume-A)
│   └── auto-stop: 15min, auto-delete: 2h
│
├── Thread-2 → Sandbox-Agent-2 (挂载 Volume-A)
│   └── auto-stop: 15min, auto-delete: 2h
│
├── Thread-3 → Sandbox-Agent-3 (挂载 Volume-A)
│   └── auto-stop: 15min, auto-delete: 2h
│
└── WebDAV → Sandbox-Files-A (按需创建，挂载 Volume-A)
    └── auto-stop: 60min
```

**两种 Sandbox 类型：**

| 类型 | 用途 | 生命周期 | 数量 |
|------|------|----------|------|
| **Agent Sandbox** | Agent 执行命令 | auto-stop 15min, auto-delete 2h | 每线程一个 |
| **Files Sandbox** | WebDAV/文件操作 | auto-stop 60min, 按需创建 | 每用户一个 |

**为什么 Agent 要每线程一个 Sandbox？**
- 避免环境变量污染（不同线程可能设置不同 env）
- 避免进程状态冲突（后台运行的进程）
- 避免工作目录混淆（cd 命令影响全局）
- 避免依赖版本冲突（不同线程可能安装不同版本）

### 2.2 auto-stop 机制详解

**计时逻辑：基于"无活动(idle)"计时，不是绝对时间**

以下操作会**重置计时器**：
- 执行命令 (`sandbox.process.exec`)
- 代码执行 (`sandbox.process.code_run`)
- 文件操作 (`sandbox.fs.*`)
- 任何通过 SDK 的操作

**不会中断正在执行的任务：**
- 正在运行的命令不会被 auto-stop 中断
- 只有在任务完成后、无活动达到阈值才会触发

```
用户发送消息
    ↓
Sandbox 创建/启动 → 重置计时器
    ↓
Agent 执行命令 (execute) → 重置计时器
    ↓
文件操作 (upload/download) → 重置计时器
    ↓
等待用户响应... N分钟无活动 → auto-stop
```

**配置建议：**

```python
# Agent Sandbox
DAYTONA_AUTO_STOP_INTERVAL = 15   # 15 分钟
DAYTONA_AUTO_DELETE_INTERVAL = 120  # 2 小时

# Files Sandbox (WebDAV)
DAYTONA_FILES_SANDBOX_AUTO_STOP = 60  # 60 分钟
```

### 2.3 存储架构详解

**重要：Daytona 使用 MinIO (S3 兼容) 作为后端存储，不支持直接映射本地目录**

#### Daytona 存储架构

```
┌─────────────────────────────────────────────────────────────────────┐
│                   Daytona Server (Docker)                           │
├─────────────────────────────────────────────────────────────────────┤
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────────┐  │
│  │ PostgreSQL  │  │   MinIO     │  │         Registry            │  │
│  │ (元数据)    │  │  (S3存储)   │  │      (Docker镜像)           │  │
│  └─────────────┘  └─────────────┘  └─────────────────────────────┘  │
│                          ↑                                          │
│                          │                                          │
│  ┌───────────────────────┴───────────────────────────────────────┐  │
│  │                        Volume 数据                             │  │
│  │                     存储在 MinIO S3 中                         │  │
│  │                  bucket: daytona-volume-{id}                   │  │
│  └───────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

#### 运行时架构

```
┌─────────────────────────────────────────────────────────────────────┐
│                    Sandbox 运行时                                    │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │  Sandbox 容器                                                │    │
│  │  ┌─────────────────────────────────────────────────────┐    │    │
│  │  │  /workspace (挂载的 Volume)                          │    │    │
│  │  │  ├── file1.py                                       │    │    │
│  │  │  ├── file2.txt                                      │    │    │
│  │  │  └── ...                                            │    │    │
│  │  └─────────────────────────────────────────────────────┘    │    │
│  │              ↑ Agent execute() 直接写入                      │    │
│  └─────────────────────────────────────────────────────────────┘    │
│                          │                                          │
│                          ▼                                          │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │  Daytona Runner                                              │    │
│  │  (Volume 的本地缓存层)                                        │    │
│  │  - 实时读写                                                   │    │
│  │  - 后台同步到 MinIO                                           │    │
│  └─────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────┘
                           │
                           ▼ 后台同步
┌─────────────────────────────────────────────────────────────────────┐
│  MinIO (S3 持久化存储)                                               │
│  bucket: daytona-volume-{volume_id}                                 │
│  - Volume 的最终持久化位置                                           │
│  - Sandbox 销毁后数据仍保留                                          │
└─────────────────────────────────────────────────────────────────────┘
```

#### 存储位置对比

| 项目 | Daytona | Docker (现有) |
|------|---------|---------------|
| Volume 存储 | MinIO (S3) | 本地文件系统 |
| Snapshot 存储 | MinIO / Registry | Docker 镜像 |
| 本地目录映射 | ❌ 不支持 | ✅ 支持 |
| 文件访问方式 | Daytona FS API | 直接读写 |

#### MinIO 访问（可选）

```bash
# MinIO Console
http://localhost:9001
用户名: minioadmin
密码: minioadmin

# Volume bucket 命名规则
daytona-volume-{volume_id}
```

### 2.4 文件操作机制

#### deepagents 文件操作分类

**1️⃣ 沙箱内操作（通过 execute）- 无网络开销**

```python
# BaseSandbox 的这些方法都是通过 execute() 在沙箱内执行的
def read(file_path, offset, limit)    # 在沙箱内执行 python 脚本读取
def write(file_path, content)         # 在沙箱内执行 python 脚本写入
def edit(file_path, old, new)         # 在沙箱内执行 python 脚本编辑
def ls_info(path)                     # 在沙箱内执行 python 脚本列出
def grep_raw(pattern, path)           # 在沙箱内执行 grep 命令
def glob_info(pattern, path)          # 在沙箱内执行 python 脚本匹配
```

**数据流：**
```
Agent 调用 write_file
    ↓
DaytonaSandboxBackend.write()
    ↓
self.execute("python3 -c '...写入文件脚本...'")
    ↓
sandbox.process.exec() ← 在沙箱内执行
    ↓
文件直接写入沙箱文件系统（挂载的 Volume）
    ✅ 无网络传输文件内容
```

**2️⃣ 外部文件传输（upload/download）- 有网络开销**

```python
# 只有这两个方法需要实现文件传输
def upload_files(files)               # 从外部上传文件到沙箱
def download_files(paths)             # 从沙箱下载文件到外部
```

**调用时机：**

| 场景 | 调用方法 | 调用者 |
|------|----------|--------|
| Agent 执行 `write_file` | `write()` → `execute()` | deepagents |
| Agent 执行 `read_file` | `read()` → `execute()` | deepagents |
| Agent 执行 `edit_file` | `edit()` → `execute()` | deepagents |
| **用户上传文件到沙箱** | `upload_files()` | **你的代码** |
| **用户从沙箱下载文件** | `download_files()` | **你的代码** |
| **WebDAV 读取文件** | `download_files()` | **你的代码** |

**结论：Agent 的文件操作都在沙箱内通过 `execute()` 完成，不会每次都传输文件内容。`upload_files` 和 `download_files` 只在外部文件传输时调用。**

### 2.5 Snapshot 管理（替代 Docker 镜像）

```
Skill 验证流程:
┌─────────────────┐
│ 1. 创建临时 Sandbox    │
│    (base snapshot)     │
└────────┬────────┘
         │
┌────────▼────────┐
│ 2. 安装 Skill 依赖     │
│    pip install ...     │
└────────┬────────┘
         │
┌────────▼────────┐
│ 3. 创建 Snapshot       │
│    包含已安装依赖      │
└────────┬────────┘
         │
┌────────▼────────┐
│ 4. 保存 Snapshot ID    │
│    到数据库            │
└────────┬────────┘
         │
┌────────▼────────┐
│ 5. 后续使用该 Snapshot │
│    创建 Sandbox        │
└─────────────────┘
```

### 2.6 WebDAV 重构方案

**现状：直接操作本地文件系统**
```python
# 现有实现
target = Path(workspace_root) / user_id / path
content = target.read_bytes()
```

**重构后：使用 Daytona FS API**
```python
# 重构后
sandbox = sandbox_manager.get_files_backend(user_id)
content = sandbox.fs_download(path)
```

**WebDAV Sandbox 策略：**
- 按需创建：用户首次访问 WebDAV 时创建
- 复用 Volume：与 Agent Sandbox 共享同一个 Volume
- 长生命周期：auto-stop 60 分钟
- 不与 Agent Sandbox 混用：避免会话污染

---

## 三、架构设计

### 3.1 整体架构

```
┌─────────────────────────────────────────────────────────────────────┐
│                           API Layer                                  │
│  api/server.py, api/files.py, api/webdav.py, api/admin.py          │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────────┐
│                        Service Layer                                 │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────────┐  │
│  │ AgentManager    │  │ WebDAVHandler   │  │ SkillValidator      │  │
│  └────────┬────────┘  └────────┬────────┘  └──────────┬──────────┘  │
│           │                    │                      │              │
│           ▼                    ▼                      ▼              │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │              DaytonaSandboxManager                           │    │
│  │  - get_thread_backend(thread_id) → Agent Sandbox            │    │
│  │  - get_files_backend(user_id) → Files Sandbox               │    │
│  │  - get_or_create_volume(user_id) → Volume                   │    │
│  │  - destroy_sandbox(thread_id)                               │    │
│  └─────────────────────────────────────────────────────────────┘    │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────────┐
│                     Daytona Abstraction Layer                        │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────────┐  │
│  │ DaytonaClient   │  │ VolumeManager   │  │ SnapshotManager     │  │
│  │ (单例)          │  │ (生命周期)      │  │ (替代 Docker 镜像)   │  │
│  └─────────────────┘  └─────────────────┘  └─────────────────────┘  │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────────┐
│                      DaytonaSandboxBackend                           │
│  implements deepagents.backends.sandbox.BaseSandbox                 │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │  execute(command) → ExecuteResponse                         │    │
│  │  upload_files(files) → list[FileUploadResponse]             │    │
│  │  download_files(paths) → list[FileDownloadResponse]         │    │
│  │  fs_* 方法 (直接访问 Daytona FS API)                         │    │
│  └─────────────────────────────────────────────────────────────┘    │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────────┐
│                    daytona-sdk (Python SDK)                         │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────────┐
│                    Self-hosted Daytona Server                        │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────────┐  │
│  │ PostgreSQL  │  │   MinIO     │  │         Registry            │  │
│  └─────────────┘  └─────────────┘  └─────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

### 3.2 核心类设计

#### 3.2.1 DaytonaClient (单例)

```python
# src/daytona_client.py
from daytona import Daytona, DaytonaConfig

class DaytonaClient:
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._client = Daytona(DaytonaConfig(
                api_key=settings.DAYTONA_API_KEY,
                api_url=settings.DAYTONA_API_URL,
                target=settings.DAYTONA_TARGET
            ))
        return cls._instance
    
    @property
    def client(self) -> Daytona:
        return self._client

def get_daytona_client() -> DaytonaClient:
    return DaytonaClient()
```

#### 3.2.2 DaytonaSandboxBackend

```python
# src/daytona_sandbox.py
from daytona import Sandbox as DaytonaSandbox
from deepagents.backends.sandbox import BaseSandbox
from deepagents.backends.protocol import ExecuteResponse, FileUploadResponse, FileDownloadResponse

class DaytonaSandboxBackend(BaseSandbox):
    def __init__(self, sandbox_id: str, sandbox: DaytonaSandbox, volume_path: str = "/workspace"):
        self.sandbox_id = sandbox_id
        self._sandbox = sandbox
        self._volume_path = volume_path

    @property
    def id(self) -> str:
        return self.sandbox_id

    def execute(self, command: str) -> ExecuteResponse:
        response = self._sandbox.process.exec(
            command=command,
            cwd=self._volume_path,
            timeout=300
        )
        return ExecuteResponse(
            output=response.result,
            exit_code=response.exit_code,
            truncated=False
        )

    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        results = []
        for file_path, content in files:
            try:
                full_path = f"{self._volume_path}/{file_path.lstrip('/')}"
                self._sandbox.fs.upload_file(content, full_path)
                results.append(FileUploadResponse(path=file_path, error=None))
            except Exception as e:
                results.append(FileUploadResponse(path=file_path, error=str(e)))
        return results

    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        results = []
        for file_path in paths:
            try:
                full_path = f"{self._volume_path}/{file_path.lstrip('/')}"
                content = self._sandbox.fs.download_file(full_path)
                results.append(FileDownloadResponse(path=file_path, content=content, error=None))
            except Exception as e:
                results.append(FileDownloadResponse(path=file_path, content=None, error=str(e)))
        return results

    # WebDAV 专用方法（直接访问 FS API）
    def fs_download(self, path: str) -> bytes:
        full_path = f"{self._volume_path}/{path.lstrip('/')}"
        return self._sandbox.fs.download_file(full_path)
    
    def fs_upload(self, path: str, content: bytes) -> None:
        full_path = f"{self._volume_path}/{path.lstrip('/')}"
        self._sandbox.fs.upload_file(content, full_path)
    
    def fs_list(self, path: str) -> list[dict]:
        full_path = f"{self._volume_path}/{path.lstrip('/')}"
        return self._sandbox.fs.list_files(full_path)
    
    def fs_delete(self, path: str) -> None:
        full_path = f"{self._volume_path}/{path.lstrip('/')}"
        self._sandbox.fs.delete_file(full_path)

    def destroy(self) -> None:
        from src.daytona_client import get_daytona_client
        client = get_daytona_client().client
        client.delete(self._sandbox)
```

#### 3.2.3 DaytonaSandboxManager

```python
# src/daytona_sandbox_manager.py
from daytona import CreateSandboxFromSnapshotParams, VolumeMount

class DaytonaSandboxManager:
    def __init__(self):
        self._volume_manager = DaytonaVolumeManager()
        self._agent_sandboxes: dict[str, DaytonaSandboxBackend] = {}  # thread_id -> sandbox
        self._files_sandboxes: dict[str, DaytonaSandboxBackend] = {}  # user_id -> sandbox
    
    def get_thread_backend(self, thread_id: str) -> DaytonaSandboxBackend:
        """获取 Agent 专用 Sandbox（每线程一个）"""
        user_id = thread_id[:36]
        
        if thread_id in self._agent_sandboxes:
            return self._agent_sandboxes[thread_id]
        
        volume = self._volume_manager.get_or_create_volume(user_id)
        sandbox = self._create_agent_sandbox(thread_id, volume)
        self._agent_sandboxes[thread_id] = sandbox
        return sandbox
    
    def get_files_backend(self, user_id: str) -> DaytonaSandboxBackend:
        """获取 WebDAV 专用 Sandbox（每用户一个，按需创建）"""
        if user_id in self._files_sandboxes:
            return self._files_sandboxes[user_id]
        
        volume = self._volume_manager.get_or_create_volume(user_id)
        sandbox = self._create_files_sandbox(user_id, volume)
        self._files_sandboxes[user_id] = sandbox
        return sandbox
    
    def _create_agent_sandbox(self, thread_id: str, volume: Volume) -> DaytonaSandboxBackend:
        """创建 Agent 专用 Sandbox"""
        client = get_daytona_client().client
        sandbox = client.create(CreateSandboxFromSnapshotParams(
            snapshot=settings.DAYTONA_BASE_SNAPSHOT,
            volumes=[VolumeMount(name=volume.name, mount_path="/workspace")],
            auto_stop_interval=settings.DAYTONA_AUTO_STOP_INTERVAL,  # 15 min
            auto_delete_interval=settings.DAYTONA_AUTO_DELETE_INTERVAL,  # 2 h
            labels={"type": "agent", "thread_id": thread_id, "user_id": thread_id[:36]}
        ))
        
        with SessionLocal() as db:
            db.add(Sandbox(
                sandbox_id=str(uuid.uuid4()),
                thread_id=thread_id,
                user_id=thread_id[:36],
                volume_id=volume.volume_id,
                daytona_sandbox_id=sandbox.id,
                sandbox_type='agent',
                state='started'
            ))
            db.commit()
        
        return DaytonaSandboxBackend(thread_id, sandbox, "/workspace")
    
    def _create_files_sandbox(self, user_id: str, volume: Volume) -> DaytonaSandboxBackend:
        """创建 WebDAV 专用 Sandbox"""
        client = get_daytona_client().client
        sandbox = client.create(CreateSandboxFromSnapshotParams(
            snapshot=settings.DAYTONA_BASE_SNAPSHOT,
            volumes=[VolumeMount(name=volume.name, mount_path="/workspace")],
            auto_stop_interval=settings.DAYTONA_FILES_SANDBOX_AUTO_STOP,  # 60 min
            labels={"type": "files", "user_id": user_id}
        ))
        
        return DaytonaSandboxBackend(f"files-{user_id[:8]}", sandbox, "/workspace")
    
    def destroy_thread_backend(self, thread_id: str) -> bool:
        if thread_id not in self._agent_sandboxes:
            return False
        self._agent_sandboxes[thread_id].destroy()
        del self._agent_sandboxes[thread_id]
        return True
```

#### 3.2.4 WebDAVHandler 重构

```python
# src/webdav.py 重构
from src.daytona_sandbox_manager import get_sandbox_manager

class WebDAVHandler:
    def __init__(self):
        self._sandbox_manager = get_sandbox_manager()
    
    async def get(self, user_id: str, path: str) -> StreamingResponse:
        """GET - Download file via Daytona FS API"""
        sandbox = self._sandbox_manager.get_files_backend(user_id)
        content = sandbox.fs_download(path)
        
        def iter_content():
            yield content
        
        return StreamingResponse(
            iter_content(),
            media_type="application/octet-stream",
            headers={"Content-Disposition": f"attachment; filename={path.split('/')[-1]}"}
        )
    
    async def put(self, user_id: str, path: str, body: bytes) -> Response:
        """PUT - Upload file via Daytona FS API"""
        sandbox = self._sandbox_manager.get_files_backend(user_id)
        sandbox.fs_upload(path, body)
        return Response(status_code=201)
    
    async def propfind(self, user_id: str, path: str, depth: int = 1) -> Response:
        """PROPFIND - List directory via Daytona FS API"""
        sandbox = self._sandbox_manager.get_files_backend(user_id)
        files = sandbox.fs_list(path)
        # ... build XML response
```

---

## 四、数据库设计

### 4.1 新增表

#### Volume 表（用户级持久化存储）

```sql
CREATE TABLE volumes (
    volume_id VARCHAR(50) PRIMARY KEY,
    user_id VARCHAR(50) NOT NULL UNIQUE,
    daytona_volume_name VARCHAR(100) NOT NULL,
    size_gb INTEGER DEFAULT 10,
    status VARCHAR(20) DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_volumes_user_id ON volumes(user_id);
```

#### Sandbox 表（线程级动态沙箱）

```sql
CREATE TABLE sandboxes (
    sandbox_id VARCHAR(50) PRIMARY KEY,
    thread_id VARCHAR(100) UNIQUE,  -- Agent Sandbox 才有，Files Sandbox 为 NULL
    user_id VARCHAR(50) NOT NULL,
    volume_id VARCHAR(50) REFERENCES volumes(volume_id),
    daytona_sandbox_id VARCHAR(100),
    snapshot_id VARCHAR(50),
    sandbox_type VARCHAR(20) NOT NULL,  -- 'agent' 或 'files'
    state VARCHAR(20) DEFAULT 'pending',
    auto_stop_interval INTEGER DEFAULT 15,
    auto_delete_interval INTEGER DEFAULT 120,
    created_at TIMESTAMP DEFAULT NOW(),
    last_activity_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_sandboxes_thread_id ON sandboxes(thread_id);
CREATE INDEX idx_sandboxes_user_id ON sandboxes(user_id);
CREATE INDEX idx_sandboxes_type ON sandboxes(sandbox_type);
```

#### Snapshot 表（Skill 运行时镜像）

```sql
CREATE TABLE snapshots (
    snapshot_id VARCHAR(50) PRIMARY KEY,
    name VARCHAR(100) NOT NULL UNIQUE,
    skill_id VARCHAR(50) REFERENCES skills(skill_id),
    daytona_snapshot_id VARCHAR(100),
    dependencies JSON,
    status VARCHAR(20) DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT NOW(),
    is_current BOOLEAN DEFAULT FALSE
);

CREATE INDEX idx_snapshots_skill_id ON snapshots(skill_id);
```

### 4.2 修改表

```sql
-- Skills 表添加 snapshot 字段
ALTER TABLE skills ADD COLUMN snapshot_id VARCHAR(50) REFERENCES snapshots(snapshot_id);
```

### 4.3 SQLAlchemy 模型

```python
# src/database.py 新增内容

class Volume(Base):
    __tablename__ = "volumes"

    volume_id = Column(String(50), primary_key=True)
    user_id = Column(String(50), unique=True, nullable=False, index=True)
    daytona_volume_name = Column(String(100), nullable=False)
    size_gb = Column(Integer, default=10)
    status = Column(String(20), default='pending')
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class Sandbox(Base):
    __tablename__ = "sandboxes"

    sandbox_id = Column(String(50), primary_key=True)
    thread_id = Column(String(100), unique=True, nullable=True, index=True)  # Files Sandbox 为 NULL
    user_id = Column(String(50), nullable=False, index=True)
    volume_id = Column(String(50), ForeignKey("volumes.volume_id"))
    daytona_sandbox_id = Column(String(100))
    snapshot_id = Column(String(50))
    sandbox_type = Column(String(20), nullable=False)  # 'agent' 或 'files'
    state = Column(String(20), default='pending')
    auto_stop_interval = Column(Integer, default=15)
    auto_delete_interval = Column(Integer, default=120)
    created_at = Column(DateTime, server_default=func.now())
    last_activity_at = Column(DateTime, server_default=func.now())


class Snapshot(Base):
    __tablename__ = "snapshots"

    snapshot_id = Column(String(50), primary_key=True)
    name = Column(String(100), unique=True, nullable=False)
    skill_id = Column(String(50), ForeignKey("skills.skill_id"))
    daytona_snapshot_id = Column(String(100))
    dependencies = Column(JSON)
    status = Column(String(20), default='pending')
    created_at = Column(DateTime, server_default=func.now())
    is_current = Column(Boolean, default=False)


# Skill 模型添加字段
class Skill(Base):
    # ... existing fields ...
    snapshot_id = Column(String(50), ForeignKey("snapshots.snapshot_id"))  # 新增
```

---

## 五、配置设计

### 5.1 环境变量

```bash
# .env 新增内容

# Daytona 配置
DAYTONA_API_KEY=your-api-key-here
DAYTONA_API_URL=http://localhost:3986
DAYTONA_TARGET=local

# Agent Sandbox 生命周期（分钟）
DAYTONA_AUTO_STOP_INTERVAL=15
DAYTONA_AUTO_DELETE_INTERVAL=120

# Files Sandbox 生命周期（分钟）
DAYTONA_FILES_SANDBOX_AUTO_STOP=60

# Volume 配置
DAYTONA_VOLUME_SIZE_GB=10

# Snapshot 配置
DAYTONA_BASE_SNAPSHOT=python-3.13-slim
```

### 5.2 Settings 模型

```python
# src/config.py 新增内容

class Settings(BaseSettings):
    # ... existing fields ...
    
    # Daytona 配置
    DAYTONA_API_KEY: str
    DAYTONA_API_URL: str = "http://localhost:3986"
    DAYTONA_TARGET: str = "local"
    
    # Agent Sandbox 生命周期
    DAYTONA_AUTO_STOP_INTERVAL: int = 15
    DAYTONA_AUTO_DELETE_INTERVAL: int = 120
    
    # Files Sandbox 生命周期
    DAYTONA_FILES_SANDBOX_AUTO_STOP: int = 60
    
    # Volume 配置
    DAYTONA_VOLUME_SIZE_GB: int = 10
    
    # Snapshot 配置
    DAYTONA_BASE_SNAPSHOT: str = "python-3.13-slim"
```

---

## 六、文件变更清单

### 6.1 删除文件 (2 个)

| 文件 | 原因 |
|------|------|
| `src/docker_sandbox.py` | 被 Daytona 沙箱替代 |
| `src/agent_skills/skill_image_manager.py` | 被 Snapshot 管理替代 |

### 6.2 新增文件 (5 个)

| 文件 | 功能 |
|------|------|
| `src/daytona_client.py` | Daytona SDK 单例客户端 |
| `src/daytona_sandbox.py` | 实现 BaseSandbox 接口 |
| `src/daytona_sandbox_manager.py` | Sandbox 生命周期管理（Agent + Files） |
| `src/daytona_volume_manager.py` | Volume 生命周期管理 |
| `src/daytona_snapshot_manager.py` | Snapshot 创建/管理 |

### 6.3 修改文件 (11 个)

| 文件 | 变更内容 |
|------|----------|
| `pyproject.toml` | 移除 docker，添加 daytona-sdk |
| `src/config.py` | 添加 Daytona 配置，移除 Docker 配置 |
| `src/database.py` | 添加 Volume, Sandbox, Snapshot 模型 |
| `src/agent_manager.py` | 适配新沙箱接口（约 10 行改动） |
| `src/webdav.py` | 改用 Daytona FS API |
| `src/chunk_upload.py` | 改用 Daytona Volume 存储 |
| `src/agent_skills/skill_validator.py` | 适配新沙箱接口 |
| `api/server.py` | 改 destroy 引用（2 行） |
| `api/files.py` | 适配 Daytona Volume |
| `api/admin.py` | images → snapshots |
| `api/models.py` | 可选：添加 Snapshot 相关响应模型 |

### 6.4 不变文件

```
src/auth.py
src/agent_utils/*
src/utils/*
src/agent_skills/skill_manager.py
src/agent_skills/skill_metrics.py
src/agent_skills/skill_command_history.py
api/auth.py
main.py
```

---

## 七、API 接口变化

### 7.1 完全不变（前端无需修改）

| API | 路径 | 说明 |
|-----|------|------|
| 会话管理 | `/api/sessions` | 创建/列表/删除会话 |
| 聊天 | `/api/chat/{thread_id}` | SSE 流式响应 |
| 中断恢复 | `/api/resume/{thread_id}` | HITL 恢复 |
| 状态/历史 | `/api/status/{thread_id}`, `/api/history/{thread_id}` | 查询 |
| 认证 | `/api/auth/*` | 登录/注册 |
| Skill 管理 | `/api/admin/skills/*` | 上传/验证/审批 |
| 文件上传 | `/api/files/*` | 接口签名不变 |
| WebDAV | `/dav/*` | 协议不变 |

### 7.2 响应格式变化（可选保持兼容）

| API | 变化 | 兼容方案 |
|-----|------|----------|
| `/api/admin/images` | → `/api/admin/snapshots` | 保留旧路由重定向 |
| `/api/admin/images/rollback` | → `/api/admin/snapshots/rollback` | 保留旧路由重定向 |

---

## 八、依赖变更

```toml
# pyproject.toml

# 移除
- "docker>=7.1.0"

# 添加
+ "daytona-sdk>=0.10.0"
```

---

## 九、实施计划

### Phase 1: 基础设施准备 (0.5 天)

**任务：**
1. 部署 Daytona Server（Docker Compose）
2. 更新 `pyproject.toml` 添加 `daytona-sdk`
3. 更新 `src/config.py` 添加 Daytona 配置
4. 创建 `.env.example` 添加 Daytona 环境变量

**交付物：**
- Daytona Server 运行正常
- 依赖安装成功
- 配置项可用

### Phase 2: 数据库模型 (0.5 天)

**任务：**
1. 更新 `src/database.py` 添加 Volume, Sandbox, Snapshot 模型
2. 运行应用自动创建表

**交付物：**
- 数据库表创建成功
- 模型可正常使用

### Phase 3: Daytona 集成层 (1 天)

**任务：**
1. 创建 `src/daytona_client.py`
2. 创建 `src/daytona_sandbox.py`（实现 BaseSandbox）
3. 创建 `src/daytona_sandbox_manager.py`
4. 创建 `src/daytona_volume_manager.py`
5. 创建 `src/daytona_snapshot_manager.py`

**交付物：**
- Daytona SDK 集成完成
- 沙箱后端可用
- Volume/Snapshot 管理可用

### Phase 4: 服务层适配 (1 天)

**任务：**
1. 更新 `src/agent_manager.py`
2. 更新 `src/webdav.py`
3. 更新 `src/chunk_upload.py`
4. 更新 `src/agent_skills/skill_validator.py`

**交付物：**
- Agent 使用 Daytona 沙箱
- WebDAV 使用 Daytona FS
- 文件上传使用 Daytona Volume

### Phase 5: API 层适配 (0.5 天)

**任务：**
1. 更新 `api/server.py`（2 行）
2. 更新 `api/files.py`
3. 更新 `api/admin.py`（images → snapshots）

**交付物：**
- API 接口正常工作
- 响应格式正确

### Phase 6: 清理与测试 (0.5 天)

**任务：**
1. 删除 `src/docker_sandbox.py`
2. 删除 `src/agent_skills/skill_image_manager.py`
3. 更新 `AGENTS.md`
4. 运行测试

**交付物：**
- 旧代码清理完成
- 文档更新
- 测试通过

---

## 十、风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| Daytona API 变更 | 高 | 使用固定版本的 SDK |
| 网络延迟 | 中 | 自托管本地部署，延迟 <10ms |
| Volume 数据丢失 | 高 | MinIO 定期备份策略 |
| 并发 Sandbox 数量限制 | 中 | 配置资源限制，实施限流 |
| 依赖安装时间长 | 低 | Snapshot 预装常用依赖 |
| WebDAV 首次访问慢 | 低 | Sandbox 启动 ~5-10 秒，可接受 |

---

## 十一、附录

### 11.1 Daytona Server 部署

```yaml
# docker-compose.daytona.yaml
version: '3.8'
services:
  daytona:
    image: daytonaio/daytona:latest
    ports:
      - "3986:3986"
    environment:
      - DAYTONA_API_KEY=${DAYTONA_API_KEY}
    volumes:
      - daytona_data:/data
volumes:
  daytona_data:
```

### 11.2 迁移检查清单

- [ ] Daytona Server 部署并验证
- [ ] 依赖更新 (`uv sync`)
- [ ] 数据库迁移
- [ ] 单元测试通过
- [ ] 集成测试通过
- [ ] WebDAV 功能验证
- [ ] 文件上传功能验证
- [ ] Skill 验证流程验证
- [ ] 文档更新

---

## 十二、决策记录

| 决策点 | 选择 | 理由 |
|--------|------|------|
| 部署方式 | 自托管 | 完全控制，数据安全 |
| Agent Sandbox 粒度 | 每线程一个 | 避免会话污染（环境变量、进程、工作目录） |
| Files Sandbox 粒度 | 每用户一个，按需创建 | WebDAV 访问频率低，无需常驻 |
| 镜像管理 | Daytona Snapshot | 替代 Docker save/load |
| 文件存储 | MinIO (S3) | Daytona 内置，开箱即用 |
| SDK 版本 | 最新版 | 与官方文档一致 |
| auto-stop 机制 | Agent 15min, Files 60min | 平衡资源利用和响应速度 |
