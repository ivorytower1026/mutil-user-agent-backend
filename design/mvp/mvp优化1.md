# 容器执行性能优化

## 问题描述

当前 `execute` 方法在执行短命令（如 1ms）时，总耗时远大于命令本身执行时间。

## 性能瓶颈分析

`execute` 方法的各阶段耗时分布：

| 阶段 | 操作 | 耗时估计 |
|------|------|----------|
| 1 | 创建容器 (`_create_container()`) | 几百毫秒到几秒 |
| 2 | 启动容器 (`container.start()`) | 几百毫秒到几秒 |
| 3 | 执行命令 (`exec_run()`) | 1ms + 开销 |
| 4 | 删除容器 (`container.remove(force=True)`) | 几十到几百毫秒 |

**总耗时：几百毫秒到几秒**

## 影响因素

- Docker daemon 响应速度
- 镜像是否已加载（未加载需要 pull）
- 宿主机性能
- 容器配置大小

## MVP阶段：接受现状

根据 `plan.md` 的MVP范围定义：
- **容器管理**：按需启停（每次创建新容器）
- **边界**：❌ 容器生命周期自动管理（销毁/回收）

MVP阶段**不做**容器生命周期优化，保持简单：
- 每次执行创建新容器
- 执行完毕立即销毁容器
- 不维护容器池

## 后续迭代：容器池管理

根据 `plan.md` 的后续迭代方向（短期 1-2周），实施容器池优化：

### 优化方案：容器池复用

**核心思路**：
- 预先创建一批容器并保持运行
- 执行命令时从池中获取空闲容器
- 执行完毕后归还到池中而非销毁
- 定期重启容器防止状态污染

**架构设计**：
```python
class ContainerPool:
    def __init__(self, pool_size=5):
        self.pool = Queue(maxsize=pool_size)
        self.thread_containers = {}  # thread_id -> container_id
        self._init_pool()

    def _init_pool(self):
        """初始化容器池"""
        for _ in range(self.pool_size):
            container = self._create_container()
            self.pool.put(container)

    async def get_container(self, thread_id: str):
        """获取容器（线程维度复用）"""
        if thread_id in self.thread_containers:
            return self.thread_containers[thread_id]

        container = self.pool.get()
        self.thread_containers[thread_id] = container
        return container

    def return_container(self, thread_id: str):
        """归还容器到池中"""
        if thread_id in self.thread_containers:
            container = self.thread_containers.pop(thread_id)
            self.pool.put(container)
```

**性能提升预期**：
- 容器启动/销毁开销：**从几百ms-几秒 → 接近0**
- 命令执行总耗时：**从几百ms-几秒 → 1ms + 少量开销**

**注意事项**：
- 需要定期重启容器（防止状态污染）
- 需要设置池大小上限（防止资源耗尽）
- 需要监控容器健康状态
- 线程隔离通过 `exec_run` 的 workdir 实现

### 辅助优化：轻量级镜像

作为补充优化，更换更小的基础镜像：
```python
# 从
DOCKER_IMAGE="python:3.13-slim"  # ~120MB

# 改为
DOCKER_IMAGE="python:3.13-alpine"  # ~50MB
```

**收益**：
- 减少镜像加载时间（首次启动）
- 减少磁盘占用
- 加快容器创建速度

**风险**：
- Alpine使用musl libc，可能存在兼容性问题
- 需要充分测试所有依赖库

## 实施计划

| 阶段 | 内容 | 优先级 |
|------|------|--------|
| MVP | 保持现有实现，接受性能开销 | P0 |
| 迭代1 | 实现容器池（线程维度复用） | P1 |
| 迭代2 | 容器定期重启机制 | P2 |
| 迭代3 | 容器健康监控 | P2 |
| 迭代4 | 切换到alpine镜像 | P3 |
