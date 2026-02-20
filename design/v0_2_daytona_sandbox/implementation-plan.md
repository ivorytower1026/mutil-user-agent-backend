# Daytona 重构实施计划（极简版）

> 版本: 2.0
> 日期: 2026-02-20

---

## 总览

```
Step 1: 配置和依赖 (5 分钟)
    ↓
Step 2: 核心文件 (30 分钟)
    ↓
Step 3: 集成 (30 分钟)
    ↓
Step 4: 测试 (30 分钟)
    ↓
Step 5: 清理 (5 分钟)

总计：约 1.5 小时
```

---

## Step 1: 配置和依赖 (5 分钟)

### 1.1 更新 pyproject.toml

```toml
# 移除
- "docker>=7.1.0"

# 添加
+ "daytona-sdk>=0.10.0"
```

### 1.2 更新 .env

```bash
# 添加 Daytona 配置
DAYTONA_API_KEY=dtn_xxx
DAYTONA_API_URL=http://localhost:3000/api
DAYTONA_AUTO_STOP_INTERVAL=15
DAYTONA_FILES_SANDBOX_AUTO_STOP=60
```

### 1.3 更新 src/config.py

```python
class Settings(BaseSettings):
    # ... existing fields ...
    
    # Daytona 配置
    DAYTONA_API_KEY: str
    DAYTONA_API_URL: str = "http://localhost:3000/api"
    DAYTONA_AUTO_STOP_INTERVAL: int = 15
    DAYTONA_FILES_SANDBOX_AUTO_STOP: int = 60
```

### 1.4 安装依赖

```bash
uv sync
```

### 验收标准

- [ ] `uv run python -c "from daytona import Daytona; print('OK')"` 成功
- [ ] 配置项加载正常

---

## Step 2: 核心文件 (30 分钟)

### 2.1 创建 src/daytona_client.py

```python
"""Daytona SDK 单例客户端"""
from daytona import Daytona, DaytonaConfig
from src.config import settings


class DaytonaClient:
    """Daytona SDK 单例客户端"""
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
    """获取 Daytona 客户端单例"""
    return DaytonaClient()
```

### 2.2 创建 src/daytona_sandbox.py

```python
"""Daytona Sandbox 后端"""
from deepagents.backends.sandbox import BaseSandbox
from deepagents.backends.protocol import (
    ExecuteResponse,
    FileUploadResponse,
    FileDownloadResponse,
)


class DaytonaSandboxBackend(BaseSandbox):
    """Daytona Sandbox 后端，实现 BaseSandbox 接口"""
    
    def __init__(self, sandbox_id: str, sandbox):
        self.sandbox_id = sandbox_id
        self._sandbox = sandbox
    
    @property
    def id(self) -> str:
        return self.sandbox_id
    
    def execute(self, command: str) -> ExecuteResponse:
        """执行命令"""
        response = self._sandbox.process.exec(command, timeout=300)
        return ExecuteResponse(
            output=response.result,
            exit_code=response.exit_code,
            truncated=False
        )
    
    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        """上传文件"""
        results = []
        for file_path, content in files:
            try:
                self._sandbox.fs.upload_file(content, f"/workspace/{file_path}")
                results.append(FileUploadResponse(path=file_path, error=None))
            except Exception as e:
                results.append(FileUploadResponse(path=file_path, error=str(e)))
        return results
    
    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        """下载文件"""
        results = []
        for file_path in paths:
            try:
                content = self._sandbox.fs.download_file(f"/workspace/{file_path}")
                results.append(FileDownloadResponse(path=file_path, content=content, error=None))
            except Exception as e:
                results.append(FileDownloadResponse(path=file_path, content=None, error=str(e)))
        return results
    
    # Files Sandbox 专用方法（WebDAV 用）
    def fs_download(self, path: str) -> bytes:
        """下载文件"""
        return self._sandbox.fs.download_file(f"/workspace/{path}")
    
    def fs_upload(self, path: str, content: bytes):
        """上传文件"""
        self._sandbox.fs.upload_file(content, f"/workspace/{path}")
    
    def fs_list(self, path: str) -> list:
        """列出目录"""
        return self._sandbox.fs.list_files(f"/workspace/{path}")
    
    def fs_delete(self, path: str):
        """删除文件"""
        self._sandbox.fs.delete_file(f"/workspace/{path}")
    
    def destroy(self):
        """销毁 Sandbox"""
        from src.daytona_client import get_daytona_client
        get_daytona_client().client.delete(self._sandbox)
```

### 2.3 创建 src/daytona_sandbox_manager.py

```python
"""Sandbox 生命周期管理（纯内存缓存）"""
from daytona import CreateSandboxParams, VolumeMount
from src.config import settings
from src.daytona_client import get_daytona_client
from src.daytona_sandbox import DaytonaSandboxBackend


class DaytonaSandboxManager:
    """Sandbox 管理器（单例，纯内存缓存）"""
    
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
        """从 thread_id 提取 user_id（假设格式为 {user_id}-{timestamp}）"""
        return thread_id[:36] if len(thread_id) > 36 else thread_id


def get_sandbox_manager() -> DaytonaSandboxManager:
    """获取 Sandbox 管理器单例"""
    return DaytonaSandboxManager()
```

### 验收标准

- [ ] 三个文件创建成功
- [ ] 无语法错误

---

## Step 3: 集成 (30 分钟)

### 3.1 修改 src/agent_manager.py

```python
# 1. 修改导入
# 删除
- from src.docker_sandbox import get_thread_backend, destroy_thread_backend

# 添加
+ from src.daytona_sandbox_manager import get_sandbox_manager

# 2. 修改 backend 获取（约 2 处）
# 原来
- get_thread_backend(thread_id)

# 改为
+ get_sandbox_manager().get_thread_backend(thread_id)

# 3. 修改 destroy 调用
# 原来
- destroy_thread_backend(thread_id)

# 改为
+ get_sandbox_manager().destroy_thread_backend(thread_id)
```

### 3.2 修改 src/webdav.py

```python
# 添加导入
from src.daytona_sandbox_manager import get_sandbox_manager

# 修改各个方法，使用 Daytona FS API

class WebDAVHandler:
    def __init__(self):
        self._sandbox_manager = get_sandbox_manager()
    
    async def get(self, user_id: str, path: str) -> StreamingResponse:
        sandbox = self._sandbox_manager.get_files_backend(user_id)
        content = sandbox.fs_download(path)
        # ... 返回响应
    
    async def put(self, user_id: str, path: str, body: bytes) -> Response:
        sandbox = self._sandbox_manager.get_files_backend(user_id)
        sandbox.fs_upload(path, body)
        return Response(status_code=201)
    
    async def propfind(self, user_id: str, path: str, depth: int = 1) -> Response:
        sandbox = self._sandbox_manager.get_files_backend(user_id)
        files = sandbox.fs_list(path)
        # ... 构建 XML 响应
    
    async def delete(self, user_id: str, path: str) -> Response:
        sandbox = self._sandbox_manager.get_files_backend(user_id)
        sandbox.fs_delete(path)
        return Response(status_code=204)
```

### 3.3 修改 api/server.py

```python
# 修改导入
from src.daytona_sandbox_manager import get_sandbox_manager

# 修改 destroy 调用
get_sandbox_manager().destroy_thread_backend(thread_id)
```

### 验收标准

- [ ] 所有文件修改完成
- [ ] 无语法错误
- [ ] 服务能启动

---

## Step 4: 测试 (30 分钟)

### 4.1 测试脚本

创建 `tests/test_daytona_sandbox.py`:

```python
"""Daytona Sandbox 集成测试"""
import sys
sys.path.insert(0, ".")

from src.daytona_sandbox_manager import get_sandbox_manager


def test_agent_sandbox():
    """测试 Agent Sandbox"""
    print("测试 Agent Sandbox...")
    
    manager = get_sandbox_manager()
    
    # 创建 Sandbox
    backend = manager.get_thread_backend("test-user-001-test-thread-001")
    print(f"  ✅ 创建成功: {backend.id}")
    
    # 执行命令
    result = backend.execute("echo 'Hello Daytona!'")
    print(f"  ✅ 执行命令: {result.output.strip()}")
    assert "Hello Daytona!" in result.output
    
    # 写文件
    backend.execute("echo 'test content' > /workspace/test.txt")
    result = backend.execute("cat /workspace/test.txt")
    print(f"  ✅ 写文件: {result.output.strip()}")
    
    # 清理
    manager.destroy_thread_backend("test-user-001-test-thread-001")
    print("  ✅ 销毁成功")


def test_files_sandbox():
    """测试 Files Sandbox"""
    print("\n测试 Files Sandbox...")
    
    manager = get_sandbox_manager()
    
    # 创建 Sandbox
    backend = manager.get_files_backend("test-user-001")
    print(f"  ✅ 创建成功: {backend.id}")
    
    # 上传文件
    backend.fs_upload("webdav_test.txt", b"WebDAV test content")
    print("  ✅ 上传文件成功")
    
    # 下载文件
    content = backend.fs_download("webdav_test.txt")
    print(f"  ✅ 下载文件: {content}")
    assert content == b"WebDAV test content"
    
    # 列出目录
    files = backend.fs_list("")
    print(f"  ✅ 列出目录: {files}")
    
    # 删除文件
    backend.fs_delete("webdav_test.txt")
    print("  ✅ 删除文件成功")


def test_volume_persistence():
    """测试 Volume 持久化"""
    print("\n测试 Volume 持久化...")
    
    manager = get_sandbox_manager()
    
    # 第一个 Sandbox 写入文件
    backend1 = manager.get_thread_backend("test-user-002-thread-001")
    backend1.execute("echo 'persistent data' > /workspace/persist.txt")
    print("  ✅ Sandbox 1 写入文件")
    
    # 销毁第一个 Sandbox
    manager.destroy_thread_backend("test-user-002-thread-001")
    print("  ✅ Sandbox 1 已销毁")
    
    # 第二个 Sandbox 读取文件（同一个 Volume）
    backend2 = manager.get_thread_backend("test-user-002-thread-002")
    result = backend2.execute("cat /workspace/persist.txt")
    print(f"  ✅ Sandbox 2 读取文件: {result.output.strip()}")
    assert "persistent data" in result.output
    
    # 清理
    manager.destroy_thread_backend("test-user-002-thread-002")


if __name__ == "__main__":
    print("=" * 50)
    print("Daytona Sandbox 集成测试")
    print("=" * 50)
    
    test_agent_sandbox()
    test_files_sandbox()
    test_volume_persistence()
    
    print("\n" + "=" * 50)
    print("✅ 所有测试通过！")
    print("=" * 50)
```

### 4.2 运行测试

```bash
uv run python tests/test_daytona_sandbox.py
```

### 验收标准

- [ ] Agent Sandbox 创建/执行/销毁正常
- [ ] Files Sandbox 上传/下载/列出/删除正常
- [ ] Volume 持久化正常（不同 Sandbox 共享数据）

---

## Step 5: 清理 (5 分钟)

### 5.1 删除旧文件

```bash
rm src/docker_sandbox.py
```

### 5.2 更新 AGENTS.md

更新沙箱相关说明。

### 验收标准

- [ ] 旧文件已删除
- [ ] 文档已更新
- [ ] 服务正常运行

---

## 文件变更汇总

### 新建 (3 个)

| 文件 | 功能 |
|------|------|
| `src/daytona_client.py` | SDK 单例 |
| `src/daytona_sandbox.py` | BaseSandbox 实现 |
| `src/daytona_sandbox_manager.py` | 内存缓存管理 |

### 修改 (4 个)

| 文件 | 改动 |
|------|------|
| `pyproject.toml` | docker → daytona-sdk |
| `src/config.py` | 添加 Daytona 配置 |
| `src/agent_manager.py` | 改用新 SandboxManager |
| `src/webdav.py` | 改用 Daytona FS API |

### 删除 (1 个)

| 文件 |
|------|
| `src/docker_sandbox.py` |

---

## 验收总表

| 验收项 | 状态 |
|--------|------|
| 依赖安装成功 | [ ] |
| 配置项加载正常 | [ ] |
| 核心文件创建成功 | [ ] |
| 服务能正常启动 | [ ] |
| Agent Sandbox 创建正常 | [ ] |
| Agent 命令执行正常 | [ ] |
| Agent 文件操作正常 | [ ] |
| Files Sandbox 创建正常 | [ ] |
| WebDAV 上传正常 | [ ] |
| WebDAV 下载正常 | [ ] |
| WebDAV 列出正常 | [ ] |
| WebDAV 删除正常 | [ ] |
| Volume 持久化正常 | [ ] |
| 旧代码已清理 | [ ] |
