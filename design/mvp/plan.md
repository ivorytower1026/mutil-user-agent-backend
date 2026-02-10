# MVP实现方案：单用户多线程验证

## 四件套分析

### 现象(实际)
- 项目刚初始化，只有基础的pyproject.toml配置和空的main.py
- 已安装deepagents(>=0.3.12)和docker(>=7.1.0)依赖
- 设计方案定义了多租户架构但无实现代码
- 需要从零构建可运行的多租户agent系统

### 意图(期望)
- 构建开箱即用的多租户AI Coding Agent平台
- 用户通过对话界面与agent交互，无需复杂配置
- 每个用户拥有独立的：
  - LangGraph线程隔离（thread_id）
  - Docker沙箱容器
  - 工作空间目录（挂载到容器）
- 支持人工介入（HITL）机制
- 支持内网环境运行（断网可用）

### 情境(环境约束)
- **技术栈**：Python 3.13 + uv包管理
- **核心框架**：deepagents（基于langgraph）
- **后端协议**：FastAPI + SSE通信
- **容器化**：Docker
- **文件系统**：用户工作空间挂载（rw） + 共享目录挂载（ro）
- **隔离方案**：thread_id + Docker容器双重隔离

### 边界(明确不做)
- ❌ 前端界面（Vue + Vuetify UI）
- ❌ 用户认证授权系统
- ❌ 数据库持久化（MVP使用内存存储）
- ❌ 容器资源管理和配额控制
- ❌ 容器生命周期自动管理（销毁/回收）
- ❌ 文件权限精细控制
- ❌ 监控和日志系统
- ❌ 自定义HITL策略（MVP仅支持敏感操作中断）

---

## MVP范围定义

| 范围 | 说明 |
|------|------|
| 用户模型 | 单用户多会话（thread隔离） |
| 容器管理 | 按需启停（每次创建新容器） |
| 数据持久化 | 内存存储（MemoryCheckpointer） |
| HITL支持 | 敏感操作中断（execute/write_file） |
| API协议 | FastAPI + SSE流式响应 |

---

## MVP架构设计

```
┌─────────────────────────────────────────────────────┐
│              FastAPI Server                          │
│  ┌──────────────────────────────────────────────┐  │
│  │  Agent Manager (单用户多thread管理)           │  │
│  │  - 创建/获取thread_id                         │  │
│  │  - 维护thread -> backend映射                  │  │
│  └──────────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────────┐  │
│  │  DeepAgent (deepagents.create_deep_agent)    │  │
│  │  - checkpointer: MemoryCheckpointer          │  │
│  │  - backend: DockerSandboxBackend             │  │
│  │  - middleware: HumanInTheLoopMiddleware      │  │
│  └──────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────┐
│         Docker Sandbox (按需启停)                    │
│  ┌──────────────────────────────────────────────┐  │
│  │  DockerSandboxBackend                        │  │
│  │  - execute(): 创建容器 → 执行 → 销毁        │  │
│  │  - 文件操作：容器内路径映射到宿主机         │  │
│  └──────────────────────────────────────────────┘  │
│  容器挂载:                                          │
│  - /workspace → ./workspaces/{thread_id} (rw)      │
│  - /shared → ./shared (ro)                         │
└─────────────────────────────────────────────────────┘
```

---

## 核心模块设计

### 1. `backend/docker_sandbox.py` - Docker沙箱后端

```python
class DockerSandboxBackend(BaseSandbox):
    """按需创建和销毁Docker容器"""

    def __init__(self, image: str = "python:3.13-slim"):
        self.image = image
        self.client = docker.from_env()

    async def execute(self, command: str, workdir: str = "/workspace") -> ExecuteResponse:
        """
        执行命令：
        1. 创建容器（挂载工作目录）
        2. 执行命令
        3. 返回结果
        4. 销毁容器
        """
        pass

    def _create_container(self, thread_id: str):
        """创建容器并挂载工作空间"""
        return self.client.containers.create(
            image=self.image,
            command="sleep infinity",
            volumes={
                f"./workspaces/{thread_id}": {"bind": "/workspace", "mode": "rw"},
                "./shared": {"bind": "/shared", "mode": "ro"}
            }
        )
```

### 2. `backend/config.py` - 配置文件

```python
import os
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

load_dotenv()

# LLM配置（智谱AI GLM-4.7）
llm = ChatOpenAI(
    model="glm-4.7",
    temperature=0,
    openai_api_key=os.getenv("ZHIPUAI_API_KEY", ""),
    openai_api_base=os.getenv("ZHIPUAI_API_BASE", "https://open.bigmodel.cn/api/paas/v4/"),
    extra_body={
        "response_format": {"type": "text"},
        "thinking": {"type": "enabled"}
    }
)

# Docker配置
DOCKER_IMAGE = "python:3.13-slim"
DOCKER_WORKSPACE_DIR = "/workspace"
DOCKER_SHARED_DIR = "/shared"
```

### 3. `backend/agent_manager.py` - Agent管理器

```python
class AgentManager:
    """管理单用户的多个线程"""

    def __init__(self):
        from backend.config import llm

        self.checkpointer = MemoryCheckpointer()
        self.compiled_agent = create_deep_agent(
            model=llm,
            backend=DockerSandboxBackend(),
            checkpointer=self.checkpointer,
            interrupt_on={"execute": True, "write_file": True}
        )

    async def create_session(self) -> str:
        """创建新会话，返回thread_id"""
        thread_id = f"user-{uuid4()}"
        os.makedirs(f"./workspaces/{thread_id}", exist_ok=True)
        return thread_id

    async def stream_chat(self, thread_id: str, message: str) -> AsyncIterator[str]:
        """流式对话（SSE）"""
        async for event in self.compiled_agent.astream_events(
            {"messages": [HumanMessage(content=message)]},
            config={"configurable": {"thread_id": thread_id}},
            version="v1"
        ):
            # 过滤和格式化事件
            yield format_event(event)
```

### 4. `api/server.py` - FastAPI服务

```python
app = FastAPI()
agent_manager = AgentManager()

@app.post("/sessions")
async def create_session():
    """创建新会话"""
    thread_id = await agent_manager.create_session()
    return {"thread_id": thread_id}

@app.post("/chat/{thread_id}")
async def chat(thread_id: str, request: ChatRequest):
    """发送消息并返回SSE流"""
    return StreamingResponse(
        agent_manager.stream_chat(thread_id, request.message),
        media_type="text/event-stream"
    )

@app.post("/resume/{thread_id}")
async def resume_interrupt(thread_id: str, action: str):
    """恢复HITL中断（继续/取消）"""
    return await agent_manager.resume(thread_id, action)
```

---

## 目录结构

```
backend/
├── main.py                    # 服务入口
├── pyproject.toml             # 依赖配置
├── backend/
│   ├── __init__.py
│   ├── config.py              # LLM和Docker配置
│   ├── docker_sandbox.py      # Docker沙箱后端
│   └── agent_manager.py       # Agent管理器
├── api/
│   ├── __init__.py
│   ├── server.py              # FastAPI端点
│   └── models.py              # Pydantic模型
├── workspaces/                # 按需创建的工作空间
│   └── {thread_id}/
├── shared/                    # 共享资源
└── .env.example               # 环境变量示例
```

---

## 依赖配置

### pyproject.toml 补充

```toml
[project]
name = "backend"
version = "0.1.0"
description = "Multi-tenant AI Agent Platform"
readme = "README.md"
requires-python = ">=3.13"
dependencies = [
    "deepagents>=0.3.12",
    "docker>=7.1.0",
    "fastapi>=0.115.0",
    "uvicorn>=0.32.0",
    "pydantic>=2.10.0",
    "python-dotenv>=1.0.0",
    "langchain>=1.0.0",
    "langchain-openai>=0.2.0",
    "langgraph>=1.0.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.24.0",
    "httpx>=0.28.0",
]
```

### 环境变量配置

```bash
# .env.example (复制为 .env 并填入真实值)
ZHIPUAI_API_KEY=your-zhipuai-api-key
ZHIPUAI_API_BASE=https://open.bigmodel.cn/api/paas/v4/
```

### backend/config.py 实现

```python
import os
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

load_dotenv()

# LLM配置（智谱AI GLM-4.7）
llm = ChatOpenAI(
    model="glm-4.7",
    temperature=0,
    openai_api_key=os.getenv("ZHIPUAI_API_KEY", ""),
    openai_api_base=os.getenv("ZHIPUAI_API_BASE", "https://open.bigmodel.cn/api/paas/v4/"),
    extra_body={
        "response_format": {"type": "text"},
        "thinking": {"type": "enabled"}
    }
)

# Docker配置
DOCKER_IMAGE = "python:3.13-slim"
DOCKER_WORKSPACE_DIR = "/workspace"
DOCKER_SHARED_DIR = "/shared"
```

---

## 测试验证方案

### 测试脚本 `test_mvp.py`

```python
import requests
import time

# 1. 创建会话
print("1. 创建会话...")
session = requests.post("http://localhost:8000/sessions").json()
thread_id = session["thread_id"]
print(f"   Thread ID: {thread_id}")

# 2. 发送消息（SSE流）
print("2. 发送消息：创建hello.py文件...")
response = requests.post(
    f"http://localhost:8000/chat/{thread_id}",
    json={"message": "创建一个hello.py文件，输出'Hello World'"},
    stream=True
)

print("   响应流：")
for line in response.iter_lines():
    if line:
        print(f"   {line.decode()}")

# 3. 处理HITL中断
print("3. 检测到HITL中断，批准继续...")
time.sleep(1)
resume = requests.post(
    f"http://localhost:8000/resume/{thread_id}",
    json={"action": "continue"}
)
print(f"   恢复结果: {resume.json()}")

# 4. 验证文件创建
print("4. 验证文件创建...")
import os
file_path = f"./workspaces/{thread_id}/hello.py"
if os.path.exists(file_path):
    print(f"   文件已创建: {file_path}")
    with open(file_path) as f:
        print(f"   内容:\n{f.read()}")
else:
    print(f"   文件未找到: {file_path}")
```

---

## MVP里程碑

### 阶段1️⃣：DockerSandboxBackend基础实现

**任务**：
- [ ] 实现DockerSandboxBackend类
- [ ] 实现execute()方法（创建→执行→销毁）
- [ ] 实现容器挂载逻辑

**验收标准**：
```bash
# 测试命令执行
docker run --rm -v $(pwd)/workspaces/test:/workspace python:3.13-slim sh -c "cd /workspace && echo 'test' > test.txt && ls -la"
```

### 阶段2️⃣：AgentManager + MemoryCheckpointer

**任务**：
- [ ] 实现AgentManager类
- [ ] 配置MemoryCheckpointer
- [ ] 实现thread_id生成逻辑

**验收标准**：
```python
# 测试上下文恢复
thread_id = manager.create_session()
manager.stream_chat(thread_id, "记住：我的名字是Alice")
manager.stream_chat(thread_id, "我叫什么名字？")
# 应该输出 "Alice"
```

### 阶段3️⃣：FastAPI SSE端点

**任务**：
- [ ] 实现FastAPI应用
- [ ] 实现SSE流式响应
- [ ] 定义Pydantic模型

**验收标准**：
```bash
# 测试SSE流
curl -N -X POST http://localhost:8000/chat/test-thread \
  -H "Content-Type: application/json" \
  -d '{"message": "你好"}'
```

### 阶段4️⃣：HITL中断机制

**任务**：
- [ ] 配置interrupt_on参数
- [ ] 实现resume端点
- [ ] 处理中断信号

**验收标准**：
```python
# 测试中断恢复
manager.stream_chat(thread_id, "删除所有文件")
# 应该中断并等待批准
manager.resume(thread_id, "continue")
# 应该继续执行
```

### 阶段5️⃣：端到端测试

**任务**：
- [ ] 运行完整测试脚本
- [ ] 验证文件系统隔离
- [ ] 验证线程上下文隔离

**验收标准**：
```
✓ 会话创建成功
✓ 响应流正常
✓ HITL中断生效
✓ 文件创建成功
✓ 线程隔离有效
```

---

## 后续迭代方向

### 短期（1-2周）
- [ ] PostgreSQL持久化
- [ ] 多用户认证
- [ ] 容器池管理
- [ ] 自定义skills支持

### 中期（1个月）
- [ ] 前端界面（Vue + Vuetify）
- [ ] 监控和日志
- [ ] 资源配额控制
- [ ] 文件权限管理

### 长期（2-3个月）
- [ ] 分布式部署
- [ ] 高可用架构
- [ ] 插件系统
- [ ] 性能优化

---

## 风险和挑战

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| Docker API稳定性 | 高 | 先在本地测试，确认容器启停逻辑 |
| LangGraph API变更 | 中 | 查阅最新文档，使用稳定版本 |
| SSE流中断 | 中 | 实现重连机制 |
| 内存泄漏 | 低 | 限制线程数量，实现清理机制 |
| 容器资源占用 | 低 | 设置资源限制，定时清理 |

---

## 参考资料

- [deepagents文档](https://github.com/langchain-ai/deepagents)
- [LangGraph文档](https://langchain-ai.github.io/langgraph/)
- [Docker Python SDK](https://docker-py.readthedocs.io/)
- [FastAPI SSE](https://fastapi.tiangolo.com/advanced/custom-response/#streamingresponse)
