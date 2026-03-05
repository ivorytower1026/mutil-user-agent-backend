# Multi-tenant AI Agent Platform 项目总结

> 文档生成时间: 2026-03-05  
> 项目版本: v0.2.0

---

## 一、项目定位

基于 **FastAPI + LangGraph 1.0 + DeepAgents** 构建的多租户 AI 编程助手平台后端服务。

---

## 二、核心架构

```
┌─────────────────────────────────────────────────────────────┐
│                      FastAPI Application                     │
├─────────────────────────────────────────────────────────────┤
│  API Layer: server.py / auth.py / webdav.py / admin.py      │
├─────────────────────────────────────────────────────────────┤
│  Agent Manager (核心编排层)                                  │
│   ├── LLM Manager (动态模型切换)                             │
│   ├── MCP Manager (外部工具协议)                             │
│   ├── Memory Manager (长期记忆)                              │
│   └── Agent Config Manager (配置热更新)                      │
├─────────────────────────────────────────────────────────────┤
│  Docker Sandbox Backend (沙箱执行层)                         │
│   ├── Thread 级容器隔离                                      │
│   ├── Redis 活动追踪 + 自动清理                              │
│   └── 资源限制 (CPU/Memory)                                  │
├─────────────────────────────────────────────────────────────┤
│  PostgreSQL (持久化层)                                        │
│   ├── LangGraph Checkpoint (会话状态)                        │
│   └── SQLAlchemy ORM (业务数据)                              │
└─────────────────────────────────────────────────────────────┘
```

---

## 三、核心功能模块

| 模块 | 文件 | 功能 |
|------|------|------|
| **AgentManager** | `src/agent_manager.py` | Agent 生命周期管理、流式对话、HITL 中断处理 |
| **DockerSandbox** | `src/docker_sandbox.py` | 容器创建/复用、Windows路径转换、资源限制 |
| **McpManager** | `src/mcp_manager.py` | MCP 服务器连接、工具加载、多传输协议支持 |
| **LLMManager** | `src/llm_manager.py` | 动态模型配置、缓存、热切换 |
| **MemoryManager** | `src/memory_manager.py` | Mem0 记忆系统、用户级记忆隔离 |
| **AgentConfigManager** | `src/agent_config_manager.py` | 主/子 Agent 配置、系统提示词管理 |
| **WebDAVHandler** | `src/webdav.py` | 文件操作协议、路径遍历防护 |
| **ChunkUpload** | `src/chunk_upload.py` | 大文件分片上传、断点续传 |

---

## 四、项目亮点分析

### 1. 多租户安全隔离

- Thread ID 格式: `{user_id}-{uuid}`，天然实现用户隔离
- Docker 容器按 Thread 创建，共享用户 workspace
- WebDAV 路径解析防止目录穿越攻击

```python
# src/auth.py
def verify_thread_permission(user_id: str, thread_id: str) -> None:
    if not thread_id.startswith(f"{user_id}-"):
        raise HTTPException(status_code=403, detail=f"Access denied to thread {thread_id}")
```

### 2. Docker 沙箱设计

**懒加载 + 容器复用**

```python
# src/docker_sandbox.py
def _ensure_container(self) -> docker.models.containers.Container:
    if self._container is None:
        self._container = self._create_container()
        self._container.start()
    else:
        try:
            self._container.reload()
            if self._container.status != "running":
                self._container.remove(force=True)
                self._container = self._create_container()
                self._container.start()
        except docker.errors.NotFound:
            self._container = self._create_container()
            self._container.start()
    return self._container
```

**Windows 路径自动转换**

```python
# D:\path -> /d/path (Docker Desktop 兼容)
def _to_docker_path(path: str) -> str:
    p = Path(path).absolute()
    path_str = str(p).replace("\\", "/")
    if len(path_str) >= 2 and path_str[1] == ":":
        path_str = "/" + path_str[0].lower() + path_str[2:]
    return path_str
```

**Redis 活动追踪 + 后台清理任务**

```python
# main.py
async def _cleanup_idle_containers_task():
    while True:
        await asyncio.sleep(60)
        cleaned = DockerSandboxBackend.cleanup_idle_containers()
        if cleaned > 0:
            print(f"[CleanupTask] Cleaned up {cleaned} idle containers")
```

### 3. 人机协作 (HITL) + 双模式

- **Plan Mode**: 只读分析，禁止写操作，自动拒绝敏感工具
- **Build Mode**: 完整执行权限
- **自动审批机制**: `execute`、`write_file`、`edit_file` 在 Build 模式自动通过

```python
# src/agent_utils/stream/runner.py
def _handle_interrupt(self, subgraph_path: tuple, data: dict, mode: str) -> StreamChunk:
    ...
    if tool_name in AUTO_APPROVE_TOOLS:
        if mode == "build":
            return StreamChunk(auto_resume=True)
        else:
            # plan 模式下自动拒绝
            return StreamChunk(auto_reject=True)
```

### 4. 流式输出架构 (AgentStreamRunner)

```python
# LangGraph 原生流模式
stream_mode=["messages", "updates"]  # messages: token流, updates: 工具事件

# 自动恢复循环
while True:
    async for chunk in self._stream_one_cycle(...):
        if chunk.auto_resume:
            current_input = Command(resume={"decisions": [{"type": "approve"}]})
        elif chunk.auto_reject:  # Plan 模式自动拒绝
            current_input = Command(
                resume={
                    "decisions": [{
                        "type": "reject",
                        "message": "当前为思考模式，此操作需要写入权限..."
                    }]
                }
            )
```

### 5. Subagent 嵌套支持

- 支持 Agent 调用子 Agent 完成专门任务
- 栈式管理支持嵌套调用
- SSE 事件携带 `subagent_id`、`subagent_name` 用于前端展示

```python
# src/agent_utils/stream/runner.py
@dataclass
class RunnerState:
    in_subagent: bool = False
    current_subagent_id: str | None = None
    current_subagent_name: str | None = None
    subagent_stack: list = field(default_factory=list)
```

### 6. MCP 协议集成

- 支持 stdio、http、sse 三种传输方式
- 工具命名空间: `{server_name}.{tool_name}` 避免冲突
- 动态加载/卸载 MCP 服务器

```python
# src/mcp_manager.py
async def _fetch_tools(self) -> list[BaseTool]:
    tools = await load_mcp_tools(None, connection=self._connection, server_name=self.config.name)
    renamed_tools = []
    for tool in tools:
        tool.name = f"{self.config.name}.{tool.name}"  # 命名空间前缀
        renamed_tools.append(tool)
    return renamed_tools
```

### 7. 动态 LLM 配置

- 数据库存储多模型配置
- 按角色 (`big`/`flash`/`embedding`) 激活
- 配置更新自动失效缓存

```python
# src/llm_manager.py
def activate_config(self, config_id: str, db: Session) -> Optional[LlmConfig]:
    config = db.query(LlmConfig).filter(LlmConfig.id == config_id).first()
    
    # 同角色其他配置 deactivate
    db.query(LlmConfig).filter(
        LlmConfig.role == config.role, LlmConfig.is_active == True
    ).update({"is_active": False})
    
    config.is_active = True
    db.commit()
    
    self.invalidate_cache(config.role)  # 自动失效缓存
```

### 8. 长期记忆系统 (Mem0)

- Qdrant 向量存储 + 用户级隔离
- 提供 6 个记忆工具: `add_memory`、`search_memories`、`get_memories` 等
- 从 ToolRuntime 提取 thread_id 关联用户

```python
# src/memory_manager.py
def _extract_user_id(self, tool_runtime: ToolRuntime) -> str:
    config = tool_runtime.config
    thread_id = config.get("configurable", {}).get("thread_id")
    
    with SessionLocal() as db:
        thread = db.query(Thread).filter(Thread.thread_id == thread_id).first()
        if thread:
            return thread.user_id
    
    return "default"
```

---

## 五、API 端点一览

| 端点 | 方法 | 功能 |
|------|------|------|
| `/api/auth/register` | POST | 用户注册 |
| `/api/auth/login` | POST | JWT 登录 |
| `/api/sessions` | POST/GET | 创建/列出会话 |
| `/api/chat/{thread_id}` | POST | 流式对话 |
| `/api/resume/{thread_id}` | POST | 恢复中断会话 |
| `/api/status/{thread_id}` | GET | 获取会话状态 |
| `/api/history/{thread_id}` | GET | 获取对话历史 |
| `/api/sessions/{thread_id}` | DELETE | 销毁会话 |
| `/dav/{path}` | PROPFIND/GET/PUT/MKCOL/DELETE/MOVE | WebDAV 文件操作 |
| `/api/files/init-upload` | POST | 初始化分片上传 |
| `/api/files/upload-chunk` | POST | 上传分片 |
| `/api/files/complete-upload` | POST | 完成上传 |
| `/api/admin/skills` | GET/POST | 技能管理 |
| `/api/admin/skills/simple` | GET/POST/DELETE | 简单技能管理 |
| `/api/admin/mcp` | GET/POST | MCP 服务器管理 |
| `/api/admin/agents` | GET/PUT | Agent 配置管理 |
| `/api/admin/agents/subagents/{name}` | POST/GET/PUT/DELETE | 子 Agent 管理 |

---

## 六、技术栈总结

| 领域 | 技术 |
|------|------|
| Web框架 | FastAPI + Uvicorn |
| Agent编排 | LangGraph 1.0 + DeepAgents 0.4.4 |
| 持久化 | PostgreSQL + SQLAlchemy |
| 检查点 | AsyncPostgresSaver (langgraph-checkpoint-postgres) |
| 容器 | Docker SDK |
| 缓存 | Redis |
| 记忆 | Mem0 + Qdrant |
| 协议 | MCP (langchain-mcp-adapters) |
| 认证 | JWT + Argon2 |
| 监控 | Langfuse |

---

## 七、数据库模型

### User (用户)
```python
user_id: str          # 主键
username: str         # 唯一
password_hash: str    # Argon2
is_admin: bool
created_at: DateTime
```

### Thread (会话)
```python
thread_id: str        # 主键, 格式: {user_id}-{uuid}
user_id: str          # 外键
title: str            # 自动生成或手动设置
created_at: DateTime
```

### Skill (技能)
```python
skill_id: str
name: str             # 唯一
status: str           # pending/validating/approved/rejected/active/disabled
validation_stage: str # layer1/layer2/completed/failed
skill_path: str
# 验证结果字段...
```

### McpServer (MCP服务器)
```python
id: str
name: str             # 唯一
transport: str        # stdio/http/sse
command: str          # stdio 传输时使用
url: str              # http/sse 传输时使用
enabled: bool
```

### AgentConfigModel (Agent配置)
```python
id: str
name: str             # 唯一
is_main: bool         # 是否为主配置
system_prompt: str
mcp_servers: list     # 启用的 MCP 服务器
skills: list          # 启用的技能
subagents: list       # 启用的子 Agent
model: str            # 指定模型 (可选)
```

### LlmConfig (LLM配置)
```python
id: str
name: str             # 唯一
provider: str         # openai/zhipuai/vllm
base_url: str
api_key: str
model_name: str
role: str             # big/flash/embedding
is_active: bool
```

---

## 八、项目结构

```
backend/
├── main.py                 # FastAPI 入口, lifespan 管理
├── pyproject.toml          # uv 包管理
├── src/                    # 核心业务逻辑
│   ├── config.py           # 配置管理, LLM 实例
│   ├── agent_manager.py    # Agent 生命周期
│   ├── docker_sandbox.py   # Docker 沙箱
│   ├── mcp_manager.py      # MCP 协议
│   ├── llm_manager.py      # 动态 LLM
│   ├── memory_manager.py   # 记忆系统
│   ├── agent_config_manager.py
│   ├── auth.py             # JWT 认证
│   ├── database.py         # ORM 模型
│   ├── webdav.py           # WebDAV 协议
│   ├── chunk_upload.py     # 分片上传
│   ├── simple_skill_manager.py
│   ├── agent_skills/       # 技能管理
│   ├── agent_utils/        # Agent 工具
│   │   ├── stream/         # 流式处理
│   │   ├── formatter.py    # SSE 格式化
│   │   ├── session.py      # 会话管理
│   │   ├── interrupt.py    # 中断处理
│   │   └── types.py        # 类型定义
│   └── utils/              # 工具函数
├── api/                    # API 路由
│   ├── server.py           # Agent API
│   ├── auth.py             # 认证 API
│   ├── admin.py            # 管理 API
│   ├── webdav.py           # WebDAV 路由
│   ├── files.py            # 文件上传
│   ├── mcp.py              # MCP 管理
│   ├── agent_config.py     # Agent 配置
│   └── models.py           # Pydantic 模型
└── tests/                  # 测试
```

---

## 九、总体评价

这是一个架构清晰、模块化程度高的企业级 AI Agent 平台，主要优势：

1. **安全性**: 多租户隔离、沙箱执行、路径防护
2. **可扩展性**: 动态 LLM、MCP 协议、Subagent 架构
3. **用户体验**: 流式输出、双模式切换、长期记忆
4. **运维友好**: 容器自动清理、配置热更新、监控集成

---

*文档由代码分析自动生成*
