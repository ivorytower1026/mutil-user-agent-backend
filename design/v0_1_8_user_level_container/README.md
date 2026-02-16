# v0.1.8 用户级容器共享

> 将 Docker 容器从 thread 级别改为 user 级别共享，解决多对话创建大量容器的问题

---

## 一、现象（实际）

### 1.1 当前问题

用户开启多个对话时，创建了大量 Docker 容器：

```
用户A - 对话1 → 容器 container_abc
用户A - 对话2 → 容器 container_def  ← 同一用户，挂载相同目录
用户A - 对话3 → 容器 container_ghi  ← 同一用户，挂载相同目录
用户B - 对话1 → 容器 container_jkl
```

### 1.2 相关代码

| 文件 | 行号 | 问题 |
|------|------|------|
| `src/docker_sandbox.py` | 27 | `_thread_backends = {}` 按 thread_id 存储 |
| `src/docker_sandbox.py` | 36 | `if thread_id not in _thread_backends` 每个 thread 创建新容器 |

### 1.3 问题分析

| # | 问题 | 影响 |
|---|------|------|
| 1 | **容器数量爆炸** | N 个对话 = N 个容器，内存占用大 |
| 2 | **挂载同一目录** | 同用户的多个容器挂载 `workspaces/{user_id}/`，隔离无意义 |
| 3 | **无清理机制** | 容器只增不减，`_thread_backends` 字典无限增长 |
| 4 | **资源浪费** | 每个容器占用 ~50-100MB 内存 |

---

## 二、意图（期望）

### 2.1 目标架构

```
用户A - 对话1 ─┐
用户A - 对话2 ─┼─→ 共享容器 container_userA → workspaces/userA/
用户A - 对话3 ─┘
用户B - 对话1 ───→ 容器 container_userB → workspaces/userB/
```

### 2.2 期望效果

| # | 期望 | 效果 |
|---|------|------|
| 1 | **容器数 = 用户数** | 100 用户最多 100 个容器，而非 N×对话数 |
| 2 | **资源共享** | 同用户的 pip 安装、环境变量在对话间共享 |
| 3 | **文件同步** | 已实现 (v0.1.6)，所有对话共享 `workspaces/{user_id}/` |
| 4 | **API 兼容** | `get_thread_backend(thread_id)` 接口不变 |

### 2.3 架构对比

```
┌─────────────────────────────────────────────────────────────────────┐
│                    当前架构 (v0.1.7)                                  │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  用户A 开启 3 个对话：                                                │
│                                                                     │
│  thread-1 ──→ Container A ──┐                                       │
│  thread-2 ──→ Container B ──┼──→ workspaces/userA/  (同一目录)       │
│  thread-3 ──→ Container C ──┘                                       │
│                                                                     │
│  问题：3 个容器，资源浪费，隔离无意义                                   │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│                    目标架构 (v0.1.8)                                  │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  用户A 开启 3 个对话：                                                │
│                                                                     │
│  thread-1 ──┐                                                       │
│  thread-2 ──┼──→ Container (shared) ──→ workspaces/userA/           │
│  thread-3 ──┘                                                       │
│                                                                     │
│  优势：1 个容器，资源节省，环境共享                                     │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 三、情境（环境约束）

### 3.1 技术约束

| 约束 | 说明 |
|------|------|
| v0.1.6 已实现 | 工作目录已是用户级，所有 thread 共享 `workspaces/{user_id}/` |
| Thread ID 格式 | `{user_id}-{uuid}`，可提取 user_id |
| API 稳定 | `get_thread_backend(thread_id)` 被多处调用 |

### 3.2 影响范围

| 文件 | 是否修改 | 说明 |
|------|----------|------|
| `src/docker_sandbox.py` | ✅ 是 | 核心修改 |
| `src/agent_manager.py` | ❌ 否 | 接口不变 |
| `api/server.py` | ❌ 否 | 接口不变 |
| 前端 | ❌ 否 | 无感知 |

---

## 四、边界（明确不做）

| # | 不做 | 原因 |
|---|------|------|
| 1 | 不做 LRU 淘汰 | 用户级共享后容器数量可控 |
| 2 | 不做并发锁 | 单容器内代码执行本身是同步的 |
| 3 | 不做容器计数限制 | 用户数即上限 |
| 4 | 不改 API 签名 | 保持 `get_thread_backend(thread_id)` |

---

## 五、方案选择

### 5.1 方案对比

| 方案 | 容器粒度 | 容器数 | 资源占用 | 并发安全 | 推荐 |
|------|----------|--------|----------|----------|------|
| A. 保持现状 | thread | N×对话 | 高 | ✅ | |
| B. 用户级共享 | user | N×用户 | 低 | ✅ | ✓ |
| C. LRU 淘汰 | thread | 可控 | 中 | ✅ | |
| D. 定时清理 | thread | 不可控 | 中 | ✅ | |

### 5.2 选择方案 B：用户级共享

**理由**：
1. v0.1.6 已实现文件共享，容器隔离已无意义
2. 容器数量直接绑定用户数，完全可控
3. 代码改动量小，仅修改 `docker_sandbox.py`
4. API 完全兼容，无破坏性变更

---

## 六、风险评估

### 6.1 环境污染 (低风险)

**场景**：对话A安装的包影响对话B

**分析**：
- 这其实是**期望行为**：同用户的对话本就应该共享环境
- 如需隔离，用户应使用不同账号

### 6.2 并发执行 (无风险)

**场景**：两个对话同时执行代码

**分析**：
- Agent 代码执行是同步的，通过 `exec_run` 串行执行
- Docker 容器内 bash 也是单进程的

### 6.3 长时间运行任务 (低风险)

**场景**：对话A执行训练，用户切换到对话B

**缓解**：
- 前端应提示用户当前有任务运行
- 或增加任务队列机制（后续版本）

---

## 七、实施计划

### 7.1 代码修改

**文件**：`src/docker_sandbox.py`

```python
# 改动前
_thread_backends = {}  # key: thread_id

def get_thread_backend(thread_id: str) -> 'DockerSandboxBackend':
    if thread_id not in _thread_backends:
        user_id = thread_id.split('-')[0]
        workspace_dir = os.path.join(settings.WORKSPACE_ROOT, user_id)
        _thread_backends[thread_id] = DockerSandboxBackend(thread_id, workspace_dir)
    return _thread_backends[thread_id]

# 改动后
_user_backends = {}  # key: user_id

def get_thread_backend(thread_id: str) -> 'DockerSandboxBackend':
    user_id = thread_id.split('-')[0]
    if user_id not in _user_backends:
        workspace_dir = os.path.join(settings.WORKSPACE_ROOT, user_id)
        _user_backends[user_id] = DockerSandboxBackend(user_id, workspace_dir)
    return _user_backends[user_id]

def destroy_user_backend(user_id: str) -> bool:
    """Destroy a user's container."""
    if user_id in _user_backends:
        _user_backends[user_id].destroy()
        del _user_backends[user_id]
        return True
    return False
```

### 7.2 改动清单

| # | 位置 | 改动 |
|---|------|------|
| 1 | 27行 | `_thread_backends` → `_user_backends` |
| 2 | 30-44行 | `get_thread_backend` 按 user_id 缓存 |
| 3 | 48-61行 | `destroy_thread_backend` → `destroy_user_backend` |
| 4 | 71行 | `__init__(thread_id, ...)` → `__init__(user_id, ...)` |
| 5 | 79行 | `id` 属性返回 user_id |

---

## 八、测试验证

### 8.1 功能测试

| # | 测试 | 预期 |
|---|------|------|
| 1 | 用户A创建对话1，再创建对话2 | 容器数=1 |
| 2 | 对话1 pip install numpy | 对话2 可 import numpy |
| 3 | 对话1创建文件 test.txt | 对话2 可读取 |
| 4 | 用户B创建对话1 | 容器数=2（A和B各一个）|

### 8.2 回归测试

- 运行现有测试确保无破坏性变更
- 验证 WebDAV 与 Agent 文件同步正常

---

## 九、文件清单

| 文件 | 说明 |
|------|------|
| [README.md](./README.md) | 本文档 |
| [实现计划.md](./实现计划.md) | 详细代码修改 |
| [测试用例.md](./测试用例.md) | 测试验证方案 |
