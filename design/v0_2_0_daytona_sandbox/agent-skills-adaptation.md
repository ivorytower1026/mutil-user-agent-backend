# agent_skills 包 Daytona 适配方案

> 版本: 2.0
> 日期: 2026-02-20
> 状态: 待实施

---

## 一、概述

### 1.1 改动目标

将 `agent_skills` 包从 **Docker** 后端迁移到 **Daytona** 后端。

### 1.2 核心变更

| 变更类型 | 涉及文件 | 说明 |
|---------|---------|------|
| **删除** | `skill_validator.py` | 移除 `disconnect_network()` / `reconnect_network()` |
| **删除** | `skill_metrics.py` | 移除资源监控采集逻辑 |
| **删除** | `skill_image_manager.py` | 移除 docker save/load |
| **新增** | `daytona_sandbox_manager.py` | 新增验证专用方法 |
| **修改** | `skill_validator.py` | 改用双 Sandbox 方案 |
| **修改** | `skill_metrics.py` | 精简为占位实现 |
| **修改** | `skill_image_manager.py` | 精简为占位实现 |

---

## 二、接口变更详情

### 2.1 删除的接口

#### 2.1.1 DockerSandboxBackend 网络控制方法

**文件**: ~~`src/docker_sandbox.py`~~ (已删除)

| 接口 | 状态 | 原因 |
|------|------|------|
| `disconnect_network()` | **删除** | Daytona 不支持动态断网 |
| `reconnect_network()` | **删除** | Daytona 不支持动态重连 |

**现状**：
```python
# DockerSandboxBackend 中存在
def disconnect_network(self) -> bool:
    """断开容器网络"""
    self.client.networks.get("bridge").disconnect(self._container)

def reconnect_network(self) -> bool:
    """重新连接网络"""
    self.client.networks.get("bridge").connect(self._container)
```

**期望**：
- 不再需要这两个方法
- 改用 `network_block_all=True` 创建独立的离线 Sandbox

---

#### 2.1.2 MetricsCollector 资源采集

**文件**: `src/agent_skills/skill_metrics.py`

| 接口 | 状态 | 原因 |
|------|------|------|
| `_get_system_stats()` | **删除** | 移除资源监控 |
| `_get_cpu_stats()` | **删除** | 移除 CPU 采集 |
| `_get_memory_stats()` | **删除** | 移除内存采集 |
| `_calculate_cpu_usage()` | **删除** | 移除 CPU 计算 |
| `_calculate_memory_mb()` | **删除** | 移除内存计算 |

**现状**：
```python
class MetricsCollector:
    def __init__(self, backend):
        self.backend = backend
        self.samples = []
        
    def _get_system_stats(self) -> dict:
        stats = self.backend.get_container_stats()  # Docker API
        return {"cpu_percent": stats["cpu"], "memory_mb": stats["memory"]}
```

**期望**：
```python
class MetricsCollector:
    def __init__(self, backend):
        self.start_time = None
        
    async def start_collecting(self, interval: float = 1.0):
        """No-op - 只记录开始时间"""
        self.start_time = time.time()
    
    def stop_collecting(self):
        """No-op"""
        pass
    
    def get_summary(self) -> dict:
        """只返回执行时间"""
        return {"execution_time_sec": ...}
```

---

#### 2.1.3 LocalFileImageBackend Docker 方法

**文件**: `src/agent_skills/skill_image_manager.py`

| 接口 | 状态 | 原因 |
|------|------|------|
| `client = docker.from_env()` | **删除** | 移除 docker 依赖 |
| `container.commit()` | **删除** | 改用 Daytona Snapshot |
| `image.save()` | **删除** | 改用 Daytona Snapshot |
| `subprocess.run(["docker", "load"])` | **删除** | 改用 Daytona Snapshot |

**现状**：
```python
import docker

class LocalFileImageBackend:
    def __init__(self):
        self.client = docker.from_env()  # Docker 客户端
        
    def save(self, container_id: str, version: str) -> str:
        container = self.client.containers.get(container_id)
        image = container.commit(repository=self.prefix, tag=version)
        with open(tar_file, 'wb') as f:
            for chunk in image.save():
                f.write(chunk)
```

**期望**：
```python
# 移除 docker import
# class DaytonaSnapshotBackend:
#     def save(self, sandbox_id: str, version: str) -> str:
#         TODO: 使用 Daytona Snapshot API
```

---

### 2.2 新增的接口

#### 2.2.1 DaytonaSandboxManager 验证专用方法

**文件**: `src/daytona_sandbox_manager.py`

| 接口 | 状态 | 说明 |
|------|------|------|
| `_validation_sandboxes` | **新增** | 缓存验证 Sandbox |
| `_offline_sandboxes` | **新增** | 缓存离线 Sandbox |
| `get_validation_backend(skill_id)` | **新增** | 获取联网验证 Sandbox |
| `get_offline_backend(skill_id)` | **新增** | 获取离线验证 Sandbox |
| `destroy_validation_backends(skill_id)` | **新增** | 销毁验证相关 Sandbox |

**现状**：
```python
class DaytonaSandboxManager:
    def __new__(cls):
        cls._instance._agent_sandboxes = {}
        cls._instance._files_sandboxes = {}
        # 没有验证相关缓存
```

**期望**：
```python
class DaytonaSandboxManager:
    def __new__(cls):
        cls._instance._agent_sandboxes = {}
        cls._instance._files_sandboxes = {}
        cls._instance._validation_sandboxes = {}  # 新增
        cls._instance._offline_sandboxes = {}      # 新增
    
    def get_validation_backend(self, skill_id: str) -> DaytonaSandboxBackend:
        """创建/获取联网验证 Sandbox"""
        sandbox_id = f"validation_{skill_id}"
        if sandbox_id in self._validation_sandboxes:
            return self._validation_sandboxes[sandbox_id]
        sandbox = self._client.create()
        backend = DaytonaSandboxBackend(sandbox_id, sandbox)
        self._validation_sandboxes[sandbox_id] = backend
        return backend
    
    def get_offline_backend(self, skill_id: str) -> DaytonaSandboxBackend:
        """创建/获取离线验证 Sandbox (network_block_all=True)"""
        sandbox_id = f"offline_{skill_id}"
        if sandbox_id in self._offline_sandboxes:
            return self._offline_sandboxes[sandbox_id]
        from daytona import CreateSandboxParams
        sandbox = self._client.create(CreateSandboxParams(
            network_block_all=True
        ))
        backend = DaytonaSandboxBackend(sandbox_id, sandbox)
        self._offline_sandboxes[sandbox_id] = backend
        return backend
    
    def destroy_validation_backends(self, skill_id: str):
        """销毁验证相关所有 Sandbox"""
        for sid in [f"validation_{skill_id}", f"offline_{skill_id}"]:
            for cache in [self._validation_sandboxes, self._offline_sandboxes]:
                if sid in cache:
                    cache[sid].destroy()
                    del cache[sid]
```

---

### 2.3 修改的接口

#### 2.3.1 skill_validator.py 导入

| 变更 | 现状 | 期望 |
|------|------|------|
| 导入 | `from src.docker_sandbox import DockerSandboxBackend, _to_docker_path` | `from src.daytona_sandbox_manager import get_sandbox_manager` |
| Backend 创建 | `DockerSandboxBackend(user_id, workspace_dir)` | `manager.get_validation_backend(skill_id)` |
| 离线测试 | `backend.disconnect_network()` | `manager.get_offline_backend(skill_id)` |

---

#### 2.3.2 skill_validator.py _validate_layer1 方法

**现状流程**：
```
创建 DockerSandboxBackend
        ↓
联网验证
        ↓
disconnect_network()    ← 动态断网
        ↓
离线验证
        ↓
reconnect_network()     ← 恢复网络
        ↓
销毁容器
```

**期望流程**：
```
manager.get_validation_backend(skill_id)  ← 联网 Sandbox
        ↓
联网验证
        ↓
manager.get_offline_backend(skill_id)     ← 独立离线 Sandbox
        ↓
离线验证
        ↓
manager.destroy_validation_backends(skill_id)  ← 销毁两个 Sandbox
```

**代码变更**：

```python
# 现状
async def _validate_layer1(self, skill, config, resume=False):
    backend = DockerSandboxBackend(user_id, workspace_dir)
    try:
        # 联网验证
        validation_result = await self._run_validation_agent(backend, skill, config)
        
        # 断网
        backend.disconnect_network()
        
        # 离线验证
        offline_result = await self._run_offline_test(backend, skill)
        
        # 恢复网络（不再需要）
        # backend.reconnect_network()
        
        # 计算评分（4维）
        scores = calculate_overall_score(
            completion_score, trigger_score, offline_score, resource_score
        )
    finally:
        backend.destroy()

# 期望
async def _validate_layer1(self, skill, config, resume=False):
    manager = get_sandbox_manager()
    try:
        # 联网 Sandbox
        online_backend = manager.get_validation_backend(skill.skill_id)
        validation_result = await self._run_validation_agent(online_backend, skill, config)
        
        # 离线 Sandbox (network_block_all=True)
        offline_backend = manager.get_offline_backend(skill.skill_id)
        offline_result = await self._run_offline_test(offline_backend, skill)
        
        # 计算评分（3维，移除 resource_score）
        scores = calculate_overall_score(
            completion_score, trigger_score, offline_score
        )
    finally:
        manager.destroy_validation_backends(skill.skill_id)
```

---

#### 2.3.3 skill_validator.py _run_offline_test 方法

**现状**：
```python
async def _run_offline_test(self, backend, skill):
    # 依赖外部已调用 disconnect_network()
    disconnected = backend.disconnect_network()  # 或者假设已断网
    # 测试网络调用
    test_result = backend.execute("curl http://google.com")
    # 恢复网络
    backend.reconnect_network()
```

**期望**：
```python
async def _run_offline_test(self, backend, skill):
    # backend 已是 network_block_all=True 的 Sandbox
    # 无需断网/恢复操作
    test_result = backend.execute("curl -s --connect-timeout 2 http://google.com 2>&1 || echo 'NETWORK_BLOCKED'")
    if "NETWORK_BLOCKED" in test_result.output:
        blocked_network_calls = 0  # 预期行为
    else:
        blocked_network_calls = 1
```

---

#### 2.3.4 skill_metrics.py 评分函数

**现状（4维评分）**：
```python
def calculate_overall_score(completion, trigger, offline, resource) -> dict:
    weights = {
        "completion": 0.40,
        "trigger": 0.30,
        "offline": 0.20,
        "resource": 0.10  # ← 将移除
    }
    overall = completion * 0.40 + trigger * 0.30 + offline * 0.20 + resource * 0.10
    return {"overall": overall, "weights": weights}
```

**期望（3维评分）**：
```python
def calculate_overall_score(completion, trigger, offline, resource=0) -> dict:
    weights = {
        "completion": 0.50,  # 40% → 50%
        "trigger": 0.35,     # 30% → 35%
        "offline": 0.15      # 20% → 15%
        # resource 移除
    }
    overall = completion * 0.50 + trigger * 0.35 + offline * 0.15
    return {"overall": overall, "weights": weights}
```

---

#### 2.3.5 skill_image_manager.py Backend 类

**现状**：
```python
class LocalFileImageBackend:
    def __init__(self):
        self.client = docker.from_env()  # Docker 依赖
        
    def save(self, container_id: str, version: str) -> str:
        # docker commit + docker save
        ...
```

**期望**：
```python
class DaytonaSnapshotBackend:
    """占位实现，后续使用 Daytona Snapshot API"""
    
    def __init__(self):
        self._versions = []  # 内存中维护版本列表
        
    def save(self, sandbox_id: str, version: str) -> str:
        # TODO: 使用 Daytona Snapshot API
        print(f"[ImageManager] TODO: Create snapshot for {sandbox_id}")
        self._versions.append(version)
        return version
    
    def load(self, version: str) -> str:
        # TODO: 使用 Daytona Snapshot API
        print(f"[ImageManager] TODO: Load snapshot {version}")
        return version
```

---

## 三、文件变更清单

### 3.1 需要修改的文件

| 文件路径 | 改动类型 | 改动量 |
|---------|---------|-------|
| `src/daytona_sandbox_manager.py` | 扩展 | +50 行 |
| `src/agent_skills/skill_validator.py` | 重构 | ~100 行 |
| `src/agent_skills/skill_metrics.py` | 精简 | -80 行 |
| `src/agent_skills/skill_image_manager.py` | 精简 | -60 行 |

### 3.2 无需改动的文件

| 文件路径 | 原因 |
|---------|------|
| `src/agent_skills/skill_command_history.py` | `execute()` 方法签名兼容 |
| `src/agent_skills/skill_manager.py` | 无 Sandbox 依赖 |

---

## 四、验证流程对比

### 4.1 现状流程（单容器动态断网）

```
┌─────────────────────────────────────────┐
│ 创建 DockerSandboxBackend               │
│ - 挂载 skill 目录                        │
│ - 网络正常                               │
└────────────────┬────────────────────────┘
                 ↓
┌─────────────────────────────────────────┐
│ 联网验证                                 │
│ - Agent 安装依赖                         │
│ - Agent 执行盲测任务                     │
│ - MetricsCollector 采集 CPU/内存         │
└────────────────┬────────────────────────┘
                 ↓
┌─────────────────────────────────────────┐
│ disconnect_network()                    │
│ - Docker: network disconnect            │
└────────────────┬────────────────────────┘
                 ↓
┌─────────────────────────────────────────┐
│ 离线验证                                 │
│ - 在同一容器中执行                       │
│ - 网络已被阻断                           │
└────────────────┬────────────────────────┘
                 ↓
┌─────────────────────────────────────────┐
│ reconnect_network()                     │
│ - Docker: network connect               │
└────────────────┬────────────────────────┘
                 ↓
┌─────────────────────────────────────────┐
│ backend.destroy()                       │
│ - 销毁单个容器                           │
└─────────────────────────────────────────┘
```

### 4.2 期望流程（双 Sandbox）

```
┌─────────────────────────────────────────┐
│ manager.get_validation_backend(skill_id)│
│ - 创建 Daytona Sandbox                   │
│ - 网络正常                               │
└────────────────┬────────────────────────┘
                 ↓
┌─────────────────────────────────────────┐
│ 联网验证                                 │
│ - Agent 安装依赖                         │
│ - Agent 执行盲测任务                     │
│ - MetricsCollector 只记录时间            │
└────────────────┬────────────────────────┘
                 ↓
┌─────────────────────────────────────────┐
│ manager.get_offline_backend(skill_id)   │
│ - 创建新的 Daytona Sandbox               │
│ - network_block_all=True                │
└────────────────┬────────────────────────┘
                 ↓
┌─────────────────────────────────────────┐
│ 离线验证                                 │
│ - 在独立容器中执行                       │
│ - 网络创建时已被阻断                     │
└────────────────┬────────────────────────┘
                 ↓
┌─────────────────────────────────────────┐
│ manager.destroy_validation_backends()   │
│ - 销毁联网 Sandbox                       │
│ - 销毁离线 Sandbox                       │
└─────────────────────────────────────────┘
```

---

## 五、评分机制变更

### 5.1 现状（4维评分）

| 维度 | 权重 | 计算方式 |
|------|------|---------|
| completion_score | 40% | Agent 评估任务完成度 |
| trigger_score | 30% | 正确触发 skill 的比例 |
| offline_score | 20% | 离线环境下无网络调用 |
| resource_score | 10% | CPU 使用率低于阈值 |

### 5.2 期望（3维评分）

| 维度 | 权重 | 变化 | 计算方式 |
|------|------|------|---------|
| completion_score | **50%** | 40% → 50% | Agent 评估任务完成度 |
| trigger_score | **35%** | 30% → 35% | 正确触发 skill 的比例 |
| offline_score | **15%** | 20% → 15% | 离线环境下无网络调用 |
| ~~resource_score~~ | ~~移除~~ | - | - |

### 5.3 代码变更

```python
# skill_metrics.py

def calculate_overall_score(
    completion_score: float,
    trigger_score: float,
    offline_score: float,
    resource_score: float = 0  # 忽略此参数
) -> dict:
    weights = {
        "completion": 0.50,
        "trigger": 0.35,
        "offline": 0.15
    }
    
    overall = (
        completion_score * weights["completion"] +
        trigger_score * weights["trigger"] +
        offline_score * weights["offline"]
    )
    
    return {
        "completion_score": round(completion_score, 1),
        "trigger_score": round(trigger_score, 1),
        "offline_score": offline_score,
        "overall": round(overall, 1),
        "weights": weights
    }
```

---

## 六、完整代码参考

### 6.1 daytona_sandbox_manager.py 新增内容

```python
class DaytonaSandboxManager:
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._client = get_daytona_client().client
            cls._instance._agent_sandboxes = {}
            cls._instance._files_sandboxes = {}
            # 新增
            cls._instance._validation_sandboxes = {}
            cls._instance._offline_sandboxes = {}
        return cls._instance
    
    def get_validation_backend(self, skill_id: str) -> DaytonaSandboxBackend:
        """获取验证 Sandbox（联网环境）"""
        sandbox_id = f"validation_{skill_id}"
        if sandbox_id in self._validation_sandboxes:
            return self._validation_sandboxes[sandbox_id]
        
        sandbox = self._client.create()
        backend = DaytonaSandboxBackend(sandbox_id, sandbox)
        self._validation_sandboxes[sandbox_id] = backend
        return backend
    
    def get_offline_backend(self, skill_id: str) -> DaytonaSandboxBackend:
        """获取离线 Sandbox（network_block_all=True）"""
        sandbox_id = f"offline_{skill_id}"
        if sandbox_id in self._offline_sandboxes:
            return self._offline_sandboxes[sandbox_id]
        
        from daytona import CreateSandboxParams
        sandbox = self._client.create(CreateSandboxParams(
            network_block_all=True
        ))
        backend = DaytonaSandboxBackend(sandbox_id, sandbox)
        self._offline_sandboxes[sandbox_id] = backend
        return backend
    
    def destroy_validation_backends(self, skill_id: str):
        """销毁验证相关的所有 Sandbox"""
        sandbox_ids = [f"validation_{skill_id}", f"offline_{skill_id}"]
        
        for sid in sandbox_ids:
            for cache in [self._validation_sandboxes, self._offline_sandboxes]:
                if sid in cache:
                    try:
                        cache[sid].destroy()
                    except Exception as e:
                        print(f"[SandboxManager] Warning: destroy {sid} failed: {e}")
                    del cache[sid]
```

### 6.2 skill_metrics.py 精简版

```python
"""Metrics collector - resource monitoring removed."""
import time


class MetricsCollector:
    """占位实现 - 资源监控已移除。
    
    评分改为 3 维：
    - completion_score (50%)
    - trigger_score (35%)
    - offline_score (15%)
    """
    
    def __init__(self, backend):
        self.backend = backend
        self.start_time = None
    
    async def start_collecting(self, interval: float = 1.0):
        """No-op - 只记录开始时间"""
        self.start_time = time.time()
    
    def stop_collecting(self):
        """No-op"""
        pass
    
    def get_summary(self) -> dict:
        """只返回执行时间"""
        execution_time = time.time() - self.start_time if self.start_time else 0.0
        return {
            "execution_time_sec": round(execution_time, 2),
            "sample_count": 0
        }


def calculate_resource_score(metrics: dict) -> int:
    """已移除 - 返回 0"""
    return 0


def calculate_offline_score(blocked_network_calls: int) -> int:
    """计算离线能力评分"""
    if blocked_network_calls == 0:
        return 100
    elif blocked_network_calls <= 2:
        return 70
    else:
        return 0


def calculate_trigger_score(task_results: list[dict]) -> float:
    """计算触发准确性评分"""
    if not task_results:
        return 0.0
    correct = sum(1 for r in task_results if r.get("correct_skill_used", False))
    return (correct / len(task_results)) * 100


def calculate_completion_score(task_evaluations: list[dict]) -> float:
    """计算任务完成度评分"""
    if not task_evaluations:
        return 0.0
    scores = [e.get("converted_score", 0) for e in task_evaluations]
    return sum(scores) / len(scores)


def calculate_overall_score(
    completion_score: float,
    trigger_score: float,
    offline_score: float,
    resource_score: float = 0
) -> dict:
    """计算总分（3维）"""
    
    weights = {
        "completion": 0.50,
        "trigger": 0.35,
        "offline": 0.15
    }
    
    overall = (
        completion_score * weights["completion"] +
        trigger_score * weights["trigger"] +
        offline_score * weights["offline"]
    )
    
    return {
        "completion_score": round(completion_score, 1),
        "trigger_score": round(trigger_score, 1),
        "offline_score": offline_score,
        "overall": round(overall, 1),
        "weights": weights
    }
```

### 6.3 skill_image_manager.py 精简版

```python
"""Skill image management - Snapshot 集成占位."""
from typing import Protocol

from src.config import settings


class ImageBackend(Protocol):
    """镜像存储后端接口"""
    
    def save(self, sandbox_id: str, version: str) -> str: ...
    def load(self, version: str) -> str: ...
    def list_versions(self) -> list[str]: ...
    def delete(self, version: str) -> bool: ...
    def get_current(self) -> str | None: ...


class DaytonaSnapshotBackend:
    """Daytona Snapshot 后端（占位实现）"""
    
    def __init__(self):
        self.max_versions = settings.SKILL_IMAGE_VERSIONS_TO_KEEP
        self._versions = []
    
    def save(self, sandbox_id: str, version: str) -> str:
        """TODO: 使用 Daytona Snapshot API"""
        print(f"[ImageManager] TODO: Create snapshot for sandbox {sandbox_id} as {version}")
        self._versions.append(version)
        return version
    
    def load(self, version: str) -> str:
        """TODO: 使用 Daytona Snapshot API"""
        print(f"[ImageManager] TODO: Load snapshot {version}")
        return version
    
    def list_versions(self) -> list[str]:
        return sorted(self._versions)
    
    def delete(self, version: str) -> bool:
        if version in self._versions:
            print(f"[ImageManager] TODO: Delete snapshot {version}")
            self._versions.remove(version)
            return True
        return False
    
    def get_current(self) -> str | None:
        versions = self.list_versions()
        return versions[-1] if versions else None


def get_image_backend() -> ImageBackend:
    return DaytonaSnapshotBackend()
```

---

## 七、验收标准

| 验收项 | 状态 |
|--------|------|
| DaytonaSandboxManager 新增 3 个方法 | [ ] |
| `get_validation_backend()` 正常创建联网 Sandbox | [ ] |
| `get_offline_backend()` 正常创建离线 Sandbox | [ ] |
| `destroy_validation_backends()` 正常销毁 | [ ] |
| skill_validator.py 移除 Docker 导入 | [ ] |
| 联网验证流程正常 | [ ] |
| 离线验证流程正常 | [ ] |
| 评分改为 3 维 | [ ] |
| skill_metrics.py 精简完成 | [ ] |
| skill_image_manager.py 精简完成 | [ ] |
| 移除 docker 依赖（skill_image_manager.py） | [ ] |
| 回归测试流程正常 | [ ] |

---

## 八、注意事项

1. **Sandbox 命名规范**：
   - 联网验证：`validation_{skill_id}`
   - 离线验证：`offline_{skill_id}`
   - 回归测试：`regression_{skill_name}`

2. **资源清理**：
   - 务必在 `finally` 块调用 `destroy_validation_backends()`
   - 避免 Sandbox 泄漏

3. **评分变更**：
   - resource_score 移除后，通过阈值（>=70）保持不变
   - 但实际分数计算逻辑已变更

4. **Snapshot 集成**：
   - 当前 `skill_image_manager.py` 为占位实现
   - 完整 Snapshot 功能需后续迭代

5. **并发限制**：
   - Daytona Sandbox 创建有并发限制
   - 回归测试控制并发数（建议 max 5）
