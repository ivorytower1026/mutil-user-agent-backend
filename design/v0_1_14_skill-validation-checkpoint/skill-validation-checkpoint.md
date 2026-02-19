# Skill验证断点续传设计方案

## 1. 问题背景

当前 `ValidationOrchestrator` 在调用 `create_deep_agent` 时**没有传递 checkpointer**，导致：

- LangGraph 无法持久化验证会话状态
- 服务中断后无法恢复进度，需要手动重新发起验证请求
- 已完成的验证进度丢失

## 2. 架构设计

### 2.1 整体架构（方案A：复用现有Checkpointer）

```
┌─────────────────────────────────────────────────────────────┐
│                      main.py (lifespan)                      │
├─────────────────────────────────────────────────────────────┤
│  • await agent_manager.init()                               │
│    └─> 创建 AsyncPostgresSaver + 连接池                     │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                      api/server.py                           │
├─────────────────────────────────────────────────────────────┤
│  agent_manager: AgentManager (单例)                         │
│    └─> self.checkpointer: AsyncPostgresSaver (已初始化)     │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼ (导入共享)
┌─────────────────────────────────────────────────────────────┐
│                    ValidationOrchestrator                   │
├─────────────────────────────────────────────────────────────┤
│  • 复用 agent_manager.checkpointer                         │
│  • 每个验证会话使用唯一的 thread_id: "validation_{skill_id}"│
│  • 创建agent时传入checkpointer和configurable                │
│  • 服务重启时检测并恢复未完成的验证                         │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 组件关系

```
┌──────────────────┐     ┌──────────────────┐     ┌──────────────────┐
│   PostgreSQL    │────▶│ AsyncPostgres   │────▶│   AgentManager   │
│   (checkpoint)  │     │     Saver        │     │  (已初始化)       │
└──────────────────┘     └──────────────────┘     └──────────────────┘
                                                         │
                                                         │ 共享checkpointer
                                                         ▼
                                                 ┌──────────────────┐
                                                 │ ValidationOrch   │
                                                 │    (agent)       │
                                                 └──────────────────┘
                                                         │
                                                         ▼
                                                 ┌──────────────────┐
                                                 │ create_deep_agent│
                                                 │  + checkpointer  │
                                                 └──────────────────┘
```

## 3. 修改点清单

| 文件 | 修改内容 |
|------|---------|
| `api/server.py` | 导出 `agent_manager` 供其他模块使用（已存在）|
| `src/agent_skills/skill_manager.py` | 添加 `list_pending_validation()` 方法 |
| `src/agent_skills/skill_validator.py` | 1. 导入 `agent_manager`<br>2. 使用 `agent_manager.checkpointer`<br>3. `_validate_layer1` 添加 `resume` 参数支持恢复<br>4. `_run_validation_agent` 传入 `configurable={"thread_id": ...}`<br>5. 添加 `resume_all_pending` 方法（启动时主动恢复）<br>6. 添加 `_resume_validation_task` 方法 |
| `main.py` | 在 lifespan 中调用 `resume_all_pending()` |

## 4. 详细设计（方案A）

### 4.1 导出共享的 AgentManager

在 `api/server.py` 中 `agent_manager` 已经是模块级单例，其他模块可以直接导入使用：

```python
# api/server.py (已存在)
from src.agent_manager import AgentManager

router = APIRouter()
agent_manager = AgentManager()  # 模块级单例
```

### 4.2 ValidationOrchestrator 初始化

**无需额外初始化**，直接使用已初始化的 `agent_manager.checkpointer`：

```python
# src/agent_skills/skill_validator.py

from api.server import agent_manager  # 复用共享实例

class ValidationOrchestrator:
    def __init__(self):
        self.validation_lock = asyncio.Lock()
        self.skill_manager = get_skill_manager()
        self.image_backend = get_image_backend()
        # 无需创建连接池和checkpointer，复用 agent_manager
    
    @property
    def checkpointer(self):
        """复用 agent_manager 的 checkpointer"""
        return agent_manager.checkpointer
```

### 4.3 验证会话的断点续传

#### 4.3.1 使用固定thread_id

```python
# 每个验证会话使用唯一的thread_id
THREAD_ID_PREFIX = "validation_"

def _get_validation_thread_id(skill_id: str) -> str:
    return f"{THREAD_ID_PREFIX}{skill_id}"
```

#### 4.3.2 修改 `_run_validation_agent`

```python
async def _run_validation_agent(self, backend: DockerSandboxBackend, skill) -> dict:
    # ... 现有代码 ...
    
    # 复用 agent_manager 的 checkpointer
    checkpointer = self.checkpointer
    
    # 创建带checkpointer的配置
    config = RunnableConfig(
        configurable={
            "thread_id": _get_validation_thread_id(skill.skill_id)
        },
        checkpointer=checkpointer,
    )
    
    agent = create_deep_agent(
        model=big_llm,
        backend=lambda _: backend,
        system_prompt=VALIDATION_AGENT_PROMPT,
        checkpointer=checkpointer,  # 传入checkpointer
    )
    
    # 调用时传入config
    result = await agent.ainvoke(
        {"messages": [("user", prompt)]},
        config=config
    )
```

#### 4.3.3 恢复检测逻辑

```python
async def validate_skill(self, skill_id: str) -> dict:
    """运行验证，支持中断恢复"""
    
    thread_id = _get_validation_thread_id(skill_id)
    config = RunnableConfig(configurable={"thread_id": thread_id})
    checkpointer = self.checkpointer
    
    async with self.validation_lock:
        with SessionLocal() as db:
            skill = self.skill_manager.get(db, skill_id)
            if not skill:
                raise ValueError(f"Skill not found: {skill_id}")
            
            # 检测是否有未完成的验证
            existing_state = None
            if skill.status == STATUS_VALIDATING and checkpointer:
                existing_state = await checkpointer.aget(config)
            
            if existing_state is not None:
                logger.info(f"[validate_skill] 检测到未完成的验证会话，尝试恢复 thread_id={thread_id}")
                # 使用 resume=True 恢复验证
                result = await self._validate_layer1(skill, config, resume=True)
                # ... 保存结果 ...
            else:
                if skill.status == STATUS_VALIDATING:
                    # 无checkpoint，标记失败
                    self.skill_manager.set_validation_failed(db, skill_id)
                    raise ValueError(f"Validation checkpoint lost for skill {skill_id}")
                
                logger.info(f"[validate_skill] 开始新验证会话 thread_id={thread_id}")
                skill = self.skill_manager.set_validating(db, skill_id)
                
                try:
                    result = await self._validate_layer1(skill, config)
                    # ... 保存结果 ...
                except Exception as e:
                    self.skill_manager.set_validation_failed(db, skill_id)
                    raise
    
    # 验证完成后清理checkpoint
    if checkpointer:
        await checkpointer.adelete(config)
    
    return result
```

#### 4.3.4 `_validate_layer1` 统一新验证和恢复

```python
async def _validate_layer1(self, skill, config: RunnableConfig | None = None, resume: bool = False) -> dict:
    """Run layer 1 validation (online + offline blind tests).
    
    Args:
        skill: Skill 对象
        config: RunnableConfig，包含 thread_id
        resume: 是否为恢复模式，True 时使用 ainvoke(None) 恢复
    """
    
    # ... 创建 workspace、backend、metrics_collector ...
    
    if resume:
        # 恢复模式：通过 ainvoke(None) 恢复
        agent = create_deep_agent(
            model=big_llm,
            backend=lambda _: backend,
            system_prompt=VALIDATION_AGENT_PROMPT,
            checkpointer=checkpointer,
        )
        result = await agent.ainvoke(None, config=invoke_config)
        validation_result = self._parse_validation_result(result)
    else:
        # 新验证模式：调用 _run_validation_agent
        validation_result = await self._run_validation_agent(backend, skill, config)
    
    # ... 后续处理：离线测试、评分、生成报告 ...
```

### 4.4 服务启动时主动恢复

在 `main.py` 的 lifespan 中添加主动恢复逻辑，服务启动时自动恢复所有未完成的验证：

```python
# main.py (修改)
from src.agent_skills.skill_validator import get_validation_orchestrator

@asynccontextmanager
async def lifespan(app: FastAPI):
    create_tables()
    await agent_manager.init()
    
    # 主动恢复所有未完成的验证
    orchestrator = get_validation_orchestrator()
    resumed_count = await orchestrator.resume_all_pending()
    if resumed_count > 0:
        print(f"[Startup] Resumed {resumed_count} pending validations")
    
    cleaned = upload_manager.cleanup_stale()
    if cleaned > 0:
        print(f"[Startup] Cleaned up {cleaned} stale upload sessions")
    yield
```

### 4.5 ValidationOrchestrator.resume_all_pending 方法

```python
async def resume_all_pending(self) -> int:
    """启动时恢复所有未完成的验证，返回恢复的任务数量"""
    
    checkpointer = self.checkpointer
    if not checkpointer:
        logger.warning("[resume_all_pending] checkpointer未初始化，跳过恢复")
        return 0
    
    with SessionLocal() as db:
        # 查找所有 validation_stage 是 layer1 或 layer2 的 skill（未完成验证）
        pending_skills = self.skill_manager.list_pending_validation(db)
        
        resumed_count = 0
        for skill in pending_skills:
            thread_id = _get_validation_thread_id(skill.skill_id)
            config = RunnableConfig(configurable={"thread_id": thread_id})
            
            try:
                existing_state = await checkpointer.aget(config)
                if existing_state is not None:
                    logger.info(f"[resume_all_pending] 恢复验证 skill_id={skill.skill_id}")
                    # 异步启动恢复任务，不阻塞其他任务
                    asyncio.create_task(self._resume_validation_task(skill.skill_id, config))
                    resumed_count += 1
                else:
                    logger.warning(f"[resume_all_pending] skill_id={skill.skill_id} 无checkpoint，标记失败")
                    self.skill_manager.set_validation_failed(db, skill.skill_id)
                    db.commit()
            except Exception as e:
                logger.error(f"[resume_all_pending] 检查失败 skill_id={skill.skill_id}: {e}")
        
        logger.info(f"[resume_all_pending] 已启动 {resumed_count} 个恢复任务")
        return resumed_count

async def _resume_validation_task(self, skill_id: str, config: RunnableConfig):
    """独立的恢复任务，在后台执行"""
    with SessionLocal() as db:
        skill = self.skill_manager.get(db, skill_id)
        if not skill:
            logger.error(f"[_resume_validation_task] skill不存在: {skill_id}")
            return
        
        try:
            # 复用 _validate_layer1(resume=True)
            result = await self._validate_layer1(skill, config, resume=True)
            
            if result.get("passed"):
                self.skill_manager.update_validation_result(
                    db, skill_id,
                    validation_stage=VALIDATION_STAGE_COMPLETED,
                    layer1_report=result.get("layer1_report"),
                    scores=result.get("scores"),
                    installed_dependencies=result.get("installed_dependencies"),
                )
            else:
                self.skill_manager.set_validation_failed(db, skill_id)
            
            db.commit()
            
            # 清理 checkpoint
            if self.checkpointer:
                await self.checkpointer.adelete(config)
                
        except Exception as e:
            logger.error(f"[_resume_validation_task] 恢复失败: {e}")
            self.skill_manager.set_validation_failed(db, skill_id)
            db.commit()
```

## 5. 流程图

### 5.1 新验证流程

```
开始
  │
  ▼
检查数据库状态
  │
  ├──▶ 状态 = pending ──▶ 开始新验证
  │                      │
  │                      ▼
  │                 创建 thread_id
  │                      │
  │                      ▼
  │                 agent.ainvoke() + checkpointer (复用)
  │                      │
  │                      ▼
  │                 保存结果到数据库
  │                      │
  │                      ▼
  │                 删除 checkpoint
  │
  └──▶ 状态 = validating ──▶ 检查checkpoint
                                 │
                                 ├──▶ 有checkpoint ──▶ 恢复验证
                                 │                       │
                                 └──▶ 无checkpoint ──▶ 标记失败
```

### 5.2 服务启动主动恢复流程

```
服务启动 (main.py lifespan)
  │
  ▼
agent_manager.init() ──> checkpointer 初始化
  │
  ▼
get_validation_orchestrator().resume_all_pending()
  │
  ▼
查询数据库: status = validating 的所有 skill
  │
  ▼
遍历每个 skill
  │
  ├──▶ 有checkpoint ──▶ asyncio.create_task(_resume_validation_task)
  │                       (后台异步执行，不阻塞启动)
  │
  └──▶ 无checkpoint ──▶ 标记为失败
  │
  ▼
服务就绪，继续启动流程
```

### 5.3 请求时懒恢复流程（兜底）

```
用户请求验证 skill
  │
  ▼
检查数据库: status = validating
  │
  ▼
检查checkpoint是否存在
  │
  ├──▶ 存在 ──▶ _resume_validation() 恢复执行
  │
  └──▶ 不存在 ──▶ 标记为失败，返回错误

## 6. 注意事项

### 6.1 依赖顺序

- `agent_manager.init()` 必须在 `ValidationOrchestrator` 之前初始化
- 由于 `main.py` 中按顺序调用，这已自动满足

### 6.2 并发控制

- 使用 `validation_lock` 确保同一时间只有一个验证任务
- 防止多个请求同时操作同一个 skill 的验证

### 6.3 Checkpoint 清理

- 验证完成后及时删除 checkpoint，避免占用存储
- 可以设置过期时间，自动清理过期 checkpoint

### 6.4 超时处理

- 设置合理的超时机制
- 防止 checkpoint 无限积累

### 6.5 错误处理

- 网络中断：checkpoint 已保存，重启后可恢复
- 数据库错误：记录日志，返回友好错误信息
- Agent 内部错误：正常捕获并标记验证失败

## 7. 方案对比

| 对比项 | 方案A（复用） | 原方案（独立） |
|--------|--------------|----------------|
| 连接池 | 复用已有 (20) | 新建 (5) |
| 代码改动 | 导入+属性访问 | 完整初始化逻辑 |
| 维护成本 | 低 | 高 |
| 资源占用 | 低 | 高 (额外5连接) |

## 8. 预期效果

- **服务中断前**: 验证进度自动保存到 PostgreSQL
- **服务重启后**: 检测到 `validating` 状态，自动恢复验证
- **用户体验**: 无感知断点续传
- **数据完整性**: 验证结果不会因服务中断丢失
- **资源优化**: 复用现有连接池，减少资源消耗
