# Agent Skill 验证系统设计文档

> 版本: 2.1
> 日期: 2026-02-20
> 状态: 待实施

---

## 一、需求概述

### 1.1 功能需求

| # | 需求 | 说明 |
|---|------|------|
| 1 | 上传解压 | 上传 skill 压缩包 → 自动解压 → 格式验证 |
| 2 | 单 Skill 验证 | 每个 skill 一条线程，**双 Sandbox**（联网+离线）验证 |
| 3 | DeepAgents 验证 | 主 agent 制定 3 个任务 → 子代理执行 → 主 agent 评分 |
| 4 | 全量测试 | 管理员手动触发，复用之前 3 个 + 新增 2 个 = 5 个任务 |
| 5 | 多线程 | 验证和全量测试都支持并发 |
| 6 | 评分机制 | 3 维：完成度 50% + 触发 35% + 离线 15% |

### 1.2 技术栈

- **Sandbox**: Daytona（双 Sandbox：联网 + 离线）
- **Agent**: DeepAgents（主 agent + 子 agent）
- **存储**: PostgreSQL（Skill 模型）
- **并发**: asyncio + Semaphore

---

## 二、核心发现

### 2.1 Daytona 网络控制限制

| API | 网络控制 | 说明 |
|-----|---------|------|
| **Main API** (`daytona_api_client`) | ❌ 创建时设置 | `network_block_all` 只能在创建时指定 |
| **Runner API** | ✅ 运行时更新 | 但 Runner API **不直接暴露**给客户端 |

**结论**：
- ❌ **不能**在同一个 Sandbox 中动态断网/恢复
- ✅ **需要**创建两个 Sandbox：
  - Sandbox 1：联网环境（默认）
  - Sandbox 2：离线环境（`network_block_all=True`）

### 2.2 创建离线 Sandbox 的方式

```python
from daytona import Daytona, CreateSandboxFromSnapshotParams

daytona = Daytona()

# 创建联网 Sandbox
online_sandbox = daytona.create()

# 创建离线 Sandbox
offline_sandbox = daytona.create(CreateSandboxFromSnapshotParams(
    network_block_all=True  # 关键参数
))
```

---

## 三、架构设计

### 3.1 整体流程（双 Sandbox）

```
上传 zip → 解压 → 格式验证
    ↓
┌─────────────────────────────────────────────────────────────────┐
│ 串行创建两个 Sandbox:                                            │
│                                                                 │
│  ┌─────────────────────┐                                        │
│  │ Sandbox 1 (联网)     │                                        │
│  │ network_block_all=F  │                                        │
│  └──────────┬──────────┘                                        │
│             ↓                                                   │
│  ┌─────────────────────┐                                        │
│  │ 联网验证             │                                        │
│  │ - Agent 安装依赖     │                                        │
│  │ - 执行 3 个任务      │                                        │
│  │ - 保存任务到 DB     │                                        │
│  └──────────┬──────────┘                                        │
│             ↓                                                   │
│  ┌─────────────────────┐                                        │
│  │ Sandbox 2 (离线)     │                                        │
│  │ network_block_all=T  │                                        │
│  └──────────┬──────────┘                                        │
│             ↓                                                   │
│  ┌─────────────────────┐                                        │
│  │ 离线验证             │                                        │
│  │ - 复用 3 个任务      │                                        │
│  │ - 检测网络调用       │                                        │
│  └──────────┬──────────┘                                        │
│             ↓                                                   │
│  ┌─────────────────────┐                                        │
│  │ 销毁两个 Sandbox     │                                        │
│  └──────────┬──────────┘                                        │
└─────────────┼───────────────────────────────────────────────────┘
              ↓
    计算 3 维评分 → 保存结果
```

### 3.2 全量测试流程

```
管理员点击 → 获取所有已入库 Skills → 并行测试（max 5）
    ↓
每个 Skill:
  - 复用之前验证时的 3 个任务
  - 新生成 2 个额外任务
  - 共 5 个任务进行验证
  - 同样使用双 Sandbox（联网 + 离线）
```

---

## 四、文件结构

### 4.1 新文件结构

```
src/agent_skills/
├── __init__.py
├── skill_manager.py          # Skill CRUD（保留）
├── skill_validator.py        # 验证编排器（重写）
├── skill_scorer.py           # 评分计算（新增）
├── skill_format_validator.py # 格式验证（新增）
├── task_store.py             # 任务存储（新增）
└── prompts.py                # Agent 提示词（新增）
```

### 4.2 删除的文件

| 文件 | 原因 |
|------|------|
| `skill_metrics.py` | 移除资源监控，评分逻辑拆分到 skill_scorer.py |
| `skill_command_history.py` | 不再需要命令历史追踪 |
| `skill_image_manager.py` | 改用 Daytona Snapshot，暂不实现 |

---

## 五、接口变更

### 5.1 DaytonaSandboxManager 扩展

**文件**: `src/daytona_sandbox_manager.py`

| 方法 | 说明 |
|------|------|
| `get_validation_backend(skill_id)` | 获取联网验证 Sandbox |
| `get_offline_backend(skill_id)` | 获取离线验证 Sandbox（network_block_all=True） |
| `destroy_validation_backends(skill_id)` | 销毁验证相关 Sandbox |

**实现**：

```python
def get_offline_backend(self, skill_id: str) -> DaytonaSandboxBackend:
    """创建离线 Sandbox（network_block_all=True）"""
    sandbox_id = f"offline_{skill_id}"
    if sandbox_id in self._offline_sandboxes:
        return self._offline_sandboxes[sandbox_id]
    
    from daytona import CreateSandboxFromSnapshotParams
    sandbox = self._client.create(CreateSandboxFromSnapshotParams(
        network_block_all=True  # 关键：创建时断网
    ))
    backend = DaytonaSandboxBackend(sandbox_id, sandbox)
    self._offline_sandboxes[sandbox_id] = backend
    return backend
```

### 5.2 ValidationOrchestrator 重写

**文件**: `src/agent_skills/skill_validator.py`

| 方法 | 说明 |
|------|------|
| `validate_skill(skill_id)` | 验证单个 Skill |
| `run_full_test()` | 全量测试所有已入库 Skills |
| `_validate_single_skill(skill)` | 单 Skill 完整验证流程（双 Sandbox） |
| `_run_online_validation(backend, skill)` | 联网验证 |
| `_run_offline_validation(backend, skill, tasks)` | 离线验证 |

### 5.3 新增模块

| 文件 | 类/函数 | 说明 |
|------|--------|------|
| `skill_scorer.py` | `calculate_completion_score()` | 任务完成度评分 |
| | `calculate_trigger_score()` | 触发准确性评分 |
| | `calculate_offline_score()` | 离线能力评分 |
| | `calculate_overall_score()` | 计算总分（3 维） |
| `skill_format_validator.py` | `FormatValidator.validate()` | Skill 格式验证 |
| `task_store.py` | `TaskStore.save_tasks()` | 保存验证任务 |
| | `TaskStore.get_tasks()` | 获取验证任务 |
| | `TaskStore.add_extra_tasks()` | 生成额外任务 |

---

## 六、详细实现

### 6.1 验证流程（串行双 Sandbox）

```python
async def _validate_single_skill(self, skill: Skill) -> dict:
    """单个 Skill 的完整验证流程（双 Sandbox）"""
    
    manager = get_sandbox_manager()
    
    try:
        # === 阶段 1：联网验证 ===
        online_backend = manager.get_validation_backend(skill.skill_id)
        
        online_result = await self._run_online_validation(online_backend, skill)
        
        if not online_result["passed"]:
            return {"passed": False, "reason": "online_validation_failed", **online_result}
        
        # 保存任务（供离线验证和全量测试复用）
        self.task_store.save_tasks(skill.skill_id, online_result["tasks"])
        
        # === 阶段 2：离线验证 ===
        offline_backend = manager.get_offline_backend(skill.skill_id)
        
        offline_result = await self._run_offline_validation(
            offline_backend, skill, online_result["tasks"]
        )
        
        # === 阶段 3：计算评分 ===
        scores = calculate_overall_score(
            completion_score=online_result["completion_score"],
            trigger_score=online_result["trigger_score"],
            offline_score=offline_result["offline_score"]
        )
        
        passed = scores["overall"] >= 70
        
        return {
            "passed": passed,
            "online_result": online_result,
            "offline_result": offline_result,
            "scores": scores
        }
        
    finally:
        # 销毁两个 Sandbox
        manager.destroy_validation_backends(skill.skill_id)
```

### 6.2 联网验证

```python
async def _run_online_validation(
    self, 
    backend: DaytonaSandboxBackend, 
    skill: Skill
) -> dict:
    """联网验证"""
    
    # 读取 SKILL.md
    skill_md = self._read_skill_md(skill.skill_path)
    
    # 构建 prompt
    prompt = VALIDATION_PROMPT.format(
        skill_name=skill.name,
        skill_md=skill_md
    )
    
    # 创建 DeepAgent
    from deepagents import create_deep_agent
    
    agent = create_deep_agent(
        model=big_llm,
        backend=lambda _: backend,
        system_prompt=SYSTEM_PROMPT,
    )
    
    # 执行验证
    result = await agent.ainvoke({"messages": [("user", prompt)]})
    
    # 解析结果
    parsed = self._parse_validation_result(result)
    
    # 计算评分
    completion_score = calculate_completion_score(parsed["task_evaluations"])
    trigger_score = calculate_trigger_score(parsed["task_evaluations"])
    
    return {
        "passed": completion_score >= 50,
        "tasks": parsed["tasks"],
        "task_evaluations": parsed["task_evaluations"],
        "completion_score": completion_score,
        "trigger_score": trigger_score
    }
```

### 6.3 离线验证

```python
async def _run_offline_validation(
    self, 
    backend: DaytonaSandboxBackend,  # 已是 network_block_all=True
    skill: Skill,
    tasks: list[dict]
) -> dict:
    """离线验证（在离线 Sandbox 中执行）"""
    
    # Sandbox 创建时已设置 network_block_all=True
    # 验证网络已被阻断
    test_result = backend.execute("curl -s --connect-timeout 2 http://google.com 2>&1 || echo 'BLOCKED'")
    if "BLOCKED" not in test_result.output:
        logger.warning(f"[_run_offline_validation] 网络未被阻断！")
    
    # 使用同样的任务进行离线验证
    prompt = OFFLINE_VALIDATION_PROMPT.format(
        skill_name=skill.name,
        tasks=json.dumps(tasks, ensure_ascii=False, indent=2)
    )
    
    from deepagents import create_deep_agent
    
    agent = create_deep_agent(
        model=big_llm,
        backend=lambda _: backend,
        system_prompt=OFFLINE_SYSTEM_PROMPT,
    )
    
    result = await agent.ainvoke({"messages": [("user", prompt)]})
    parsed = self._parse_offline_result(result)
    
    # 计算离线评分
    offline_score = calculate_offline_score(parsed["blocked_network_calls"])
    
    return {
        "passed": offline_score >= 70,
        "blocked_network_calls": parsed["blocked_network_calls"],
        "offline_score": offline_score
    }
```

---

## 七、评分机制

### 7.1 3 维评分

| 维度 | 权重 | 计算方式 |
|------|------|---------|
| completion_score | **50%** | Agent 评估任务完成度（1-5 分转换） |
| trigger_score | **35%** | 正确触发 skill 的任务比例 |
| offline_score | **15%** | 离线环境下无网络调用 |

### 7.2 分数转换

原始分数（1-5）转换为 0-100：
- 5 分 → 100
- 4 分 → 75
- 3 分 → 50
- 2 分 → 25
- 1 分 → 0

公式：`(raw_score - 1) * 25`

### 7.3 离线评分

| 违规网络调用次数 | 分数 |
|-----------------|------|
| 0 | 100 |
| 1-2 | 70 |
| 3+ | 0 |

### 7.4 通过标准

- **overall >= 70** 通过

---

## 八、数据库变更

### 8.1 Skill 模型新增字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `validation_tasks` | JSON | 验证时的任务列表（供全量测试复用） |
| `last_full_test_at` | DateTime | 上次全量测试时间 |
| `full_test_results` | JSON | 全量测试结果 |

---

## 九、API 接口

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/admin/skills/upload` | POST | 上传 Skill 压缩包 |
| `/api/admin/skills/{id}/validate` | POST | 开始验证 |
| `/api/admin/skills/full-test` | POST | 全量测试 |
| `/api/admin/skills/{id}/validation-status` | GET | 获取验证状态 |

---

## 十、并发控制

- 验证和全量测试都使用 `asyncio.Semaphore(max_concurrent=5)`
- 每个 Skill 验证在独立的后台任务中执行
- **注意**：每个 Skill 需要创建 2 个 Sandbox，需考虑资源消耗

---

## 十一、文件变更汇总

### 11.1 新增文件

| 文件 | 说明 |
|------|------|
| `src/agent_skills/skill_scorer.py` | 评分计算 |
| `src/agent_skills/skill_format_validator.py` | 格式验证 |
| `src/agent_skills/task_store.py` | 任务存储 |
| `src/agent_skills/prompts.py` | Agent 提示词 |

### 11.2 修改文件

| 文件 | 变更 |
|------|------|
| `src/daytona_sandbox_manager.py` | 新增 get_offline_backend, destroy_validation_backends |
| `src/agent_skills/skill_validator.py` | 完全重写（双 Sandbox 方案） |
| `src/agent_skills/skill_manager.py` | 新增格式验证调用 |
| `src/database.py` | Skill 模型新增字段 |
| `api/admin.py` | 新增/修改 API 接口 |

### 11.3 删除文件

| 文件 | 原因 |
|------|------|
| `src/agent_skills/skill_metrics.py` | 移除资源监控 |
| `src/agent_skills/skill_command_history.py` | 不再需要 |
| `src/agent_skills/skill_image_manager.py` | 暂不实现 |

---

## 十二、验收标准

| # | 验收项 | 状态 |
|---|--------|------|
| 1 | 上传 zip 自动解压和格式验证 | [ ] |
| 2 | DaytonaSandboxManager 新增 get_offline_backend | [ ] |
| 3 | 双 Sandbox 验证流程（联网 + 离线） | [ ] |
| 4 | DeepAgents 主 agent + 子 agent 验证 | [ ] |
| 5 | 3 维评分（completion 50% + trigger 35% + offline 15%） | [ ] |
| 6 | 任务保存和复用 | [ ] |
| 7 | 全量测试（5 个任务：复用 3 + 新增 2） | [ ] |
| 8 | 并发控制（max 5） | [ ] |
| 9 | API 接口 | [ ] |
| 10 | 旧代码清理 | [ ] |

---

## 十三、风险与注意事项

1. **资源消耗**：每个 Skill 验证需要 2 个 Sandbox，需监控 Daytona 资源限制
2. **并发限制**：Daytona 可能有 Sandbox 创建并发限制，需要控制并发数
3. **Sandbox 泄漏**：务必在 finally 块中销毁 Sandbox，避免资源泄漏
4. **离线 Sandbox 状态**：需验证 `network_block_all=True` 是否正确生效
