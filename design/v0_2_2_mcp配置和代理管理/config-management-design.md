# 配置管理方案设计文档

> 版本: v1.0  
> 日期: 2026-02-28  
> 状态: 待审核

## 一、需求概述

### 1.1 背景
当前系统的配置管理存在以下问题：
1. **MCP服务无法动态配置** - 无法像 OpenCode/Claude Code 一样自由添加 MCP 服务
2. **Skill 入库流程复杂** - 需要验证才能入库，流程不稳定
3. **代理配置固化** - 主代理和子代理的 prompt、工具、skill 无法灵活配置

### 1.2 目标
1. **MCP配置管理** - Admin 可动态添加/删除 MCP 服务
2. **简化 Skill 管理** - 上传后直接保存在配置的 skills 目录，无需验证
3. **代理配置管理** - 可配置主代理和子代理的 prompt、MCP工具、skill

---

## 二、技术选型

### 2.1 MCP 集成方式
**选择：通过 LangChain MCP 适配器**

理由：
- DeepAgents 使用 LangChain 工具体系
- `langchain-mcp-adapters` 可将 MCP 工具转换为 LangChain Tool
- 无需修改 DeepAgents 源码

```python
from langchain_mcp_adapters import load_mcp_tools

tools = await load_mcp_tools("mcp-server-name")
agent = create_deep_agent(tools=tools, ...)
```

### 2.2 配置存储
**选择：PostgreSQL 数据库**

理由：
- 与现有架构一致
- 支持热重载（无需重启服务）
- 便于 Admin API 管理

### 2.3 Skills 隔离策略
**选择：共享 skills 目录**

理由：
- 简化管理
- 减少磁盘占用
- 主代理和子代理可复用相同 skill

---

## 三、数据库设计

### 3.1 新增表结构

#### 3.1.1 MCP 服务配置表 `mcp_servers`

| 字段 | 类型 | 说明 |
|------|------|------|
| id | VARCHAR(50) | 主键，UUID |
| name | VARCHAR(64) | 服务名称，唯一 |
| transport | VARCHAR(20) | 传输类型：stdio/sse/http |
| command | VARCHAR(255) | stdio 模式下的命令 |
| args | JSON | 命令参数列表 |
| url | VARCHAR(255) | sse/http 模式的 URL |
| env | JSON | 环境变量 |
| headers | JSON | HTTP 请求头 |
| enabled | BOOLEAN | 是否启用 |
| created_by | VARCHAR(50) | 创建者用户ID |
| created_at | DATETIME | 创建时间 |
| updated_at | DATETIME | 更新时间 |

#### 3.1.2 代理配置表 `agent_configs`

| 字段 | 类型 | 说明 |
|------|------|------|
| id | VARCHAR(50) | 主键，UUID |
| name | VARCHAR(64) | 代理名称，唯一（"main" 表示主代理） |
| is_main | BOOLEAN | 是否为主代理 |
| system_prompt | TEXT | 系统提示词 |
| mcp_tools | JSON | 启用的 MCP 工具列表 ["mcp_name.tool_name"] |
| skills | JSON | 启用的 skill 列表 ["skill_name"] |
| subagents | JSON | 子代理列表（仅主代理有效） |
| model | VARCHAR(64) | 专用模型（子代理可选） |
| created_at | DATETIME | 创建时间 |
| updated_at | DATETIME | 更新时间 |

### 3.2 修改现有表

#### 3.2.1 Skill 表简化

移除验证相关字段（或保留但不再使用）：
- ~~validation_stage~~
- ~~layer1_passed~~
- ~~layer2_passed~~
- ~~layer1_report~~
- ~~layer2_report~~

新增字段：
| 字段 | 类型 | 说明 |
|------|------|------|
| status | VARCHAR(20) | 简化为：active/disabled |

---

## 四、文件结构

### 4.1 新增文件

```
backend/
├── api/
│   ├── mcp.py                    # MCP 服务管理 API
│   └── agent_config.py           # 代理配置管理 API
├── src/
│   ├── mcp_manager.py            # MCP 连接与工具管理
│   ├── agent_config_manager.py   # 代理配置加载与热重载
│   └── simple_skill_manager.py   # 简化版 skill 管理
└── design/
    └── config-management-design.md
```

### 4.2 修改文件

| 文件 | 改动说明 |
|------|----------|
| `src/database.py` | 新增 McpServer、AgentConfig 模型 |
| `src/config.py` | 新增 MCP 相关配置项 |
| `src/agent_manager.py` | 动态加载配置、集成 MCP 工具 |
| `api/admin.py` | 新增简化 skill 上传端点 |
| `main.py` | 注册新路由 |
| `pyproject.toml` | 添加依赖 |

---

## 五、核心模块设计

### 5.1 MCP 管理器 (`src/mcp_manager.py`)

```python
class McpManager:
    """MCP 服务连接与工具管理"""
    
    _instances: dict[str, MCPToolAdapter] = {}
    
    async def add_server(self, config: McpServerConfig) -> bool:
        """添加并连接 MCP 服务"""
        
    async def remove_server(self, name: str) -> bool:
        """移除 MCP 服务"""
        
    async def get_tools(self, mcp_names: list[str]) -> list[BaseTool]:
        """获取指定 MCP 服务的工具列表"""
        
    async def list_tools(self, name: str) -> list[dict]:
        """列出 MCP 服务提供的所有工具"""
        
    async def test_connection(self, name: str) -> dict:
        """测试 MCP 服务连接"""
```

### 5.2 代理配置管理器 (`src/agent_config_manager.py`)

```python
class AgentConfigManager:
    """代理配置加载与缓存"""
    
    _cache: dict[str, AgentConfig] = {}
    _last_reload: datetime = None
    
    def load_configs(self, db: Session) -> dict:
        """从数据库加载所有代理配置"""
        
    def get_main_config(self) -> AgentConfig:
        """获取主代理配置"""
        
    def get_subagent_configs(self) -> list[AgentConfig]:
        """获取子代理配置列表"""
        
    def reload_if_needed(self, db: Session) -> bool:
        """检查并热重载配置"""
```

### 5.3 简化 Skill 管理器 (`src/simple_skill_manager.py`)

```python
class SimpleSkillManager:
    """简化版 Skill 管理（无验证）"""
    
    def __init__(self):
        self.skills_dir = Path(settings.SKILL_DIR or f"{settings.SHARED_DIR}/skills")
    
    def upload(self, db: Session, file: BinaryIO, filename: str) -> Skill:
        """上传 skill，直接解压到 skills 目录"""
        # 1. 解压 ZIP
        # 2. 解析 SKILL.md 元数据
        # 3. 保存数据库记录 (status="active")
        # 4. 无需验证
        
    def delete(self, db: Session, name: str) -> bool:
        """删除 skill"""
        
    def list_all(self, db: Session) -> list[Skill]:
        """列出所有 skill"""
        
    def sync_to_db(self, db: Session) -> int:
        """将 skills 目录同步到数据库"""
```

---

## 六、API 设计

### 6.1 MCP 服务管理

```
POST   /api/admin/mcp                 # 添加 MCP 服务
GET    /api/admin/mcp                 # 列出所有 MCP 服务
GET    /api/admin/mcp/{name}          # 获取 MCP 服务详情
PUT    /api/admin/mcp/{name}          # 更新 MCP 服务
DELETE /api/admin/mcp/{name}          # 删除 MCP 服务
POST   /api/admin/mcp/{name}/test     # 测试 MCP 连接
GET    /api/admin/mcp/{name}/tools    # 列出 MCP 提供的工具
```

#### 请求/响应示例

**添加 MCP 服务 (stdio 模式)**
```json
// POST /api/admin/mcp
{
  "name": "playwright",
  "transport": "stdio",
  "command": "npx",
  "args": ["-y", "@anthropic/mcp-server-playwright"],
  "env": {"BROWSER": "chrome"},
  "enabled": true
}
```

**添加 MCP 服务 (HTTP 模式)**
```json
// POST /api/admin/mcp
{
  "name": "weather-api",
  "transport": "http",
  "url": "https://api.example.com/mcp",
  "headers": {
    "Authorization": "Bearer your-token"
  },
  "enabled": true
}
```

**测试连接响应**
```json
// POST /api/admin/mcp/playwright/test
{
  "success": true,
  "tools_count": 12,
  "tools": [
    {"name": "browser_navigate", "description": "Navigate to URL"},
    {"name": "browser_click", "description": "Click element"}
  ]
}
```

### 6.2 代理配置管理

```
GET    /api/admin/agents                    # 获取所有代理配置
PUT    /api/admin/agents/main               # 更新主代理配置
POST   /api/admin/agents/subagents          # 创建子代理
GET    /api/admin/agents/subagents/{name}   # 获取子代理配置
PUT    /api/admin/agents/subagents/{name}   # 更新子代理
DELETE /api/admin/agents/subagents/{name}   # 删除子代理
POST   /api/admin/agents/reload             # 热重载代理配置
```

#### 请求/响应示例

**更新主代理配置**
```json
// PUT /api/admin/agents/main
{
  "system_prompt": "你是一个专业的编程助手...",
  "mcp_tools": ["playwright.browser_navigate", "playwright.browser_click"],
  "skills": ["code-review", "test-generator"],
  "subagents": ["researcher", "code-writer"]
}
```

**创建子代理**
```json
// POST /api/admin/agents/subagents
{
  "name": "researcher",
  "description": "专门负责信息检索和研究的子代理",
  "system_prompt": "你是一个研究助手，专注于...",
  "mcp_tools": ["web-search.search"],
  "skills": ["web-scraper"],
  "model": "openai:gpt-4o"
}
```

**获取所有代理配置响应**
```json
// GET /api/admin/agents
{
  "main": {
    "name": "main",
    "system_prompt": "...",
    "mcp_tools": [...],
    "skills": [...],
    "subagents": ["researcher", "code-writer"]
  },
  "subagents": [
    {
      "name": "researcher",
      "description": "...",
      "system_prompt": "...",
      "mcp_tools": [...],
      "skills": [...],
      "model": "openai:gpt-4o"
    }
  ]
}
```

### 6.3 简化 Skill 上传

```
POST   /api/admin/skills/upload            # 上传 skill（直接入库）
GET    /api/admin/skills                   # 列出所有 skill
DELETE /api/admin/skills/{name}            # 删除 skill
POST   /api/admin/skills/sync              # 同步 skills 目录到数据库
```

---

## 七、AgentManager 改造

### 7.1 初始化流程改造

```python
class AgentManager:
    async def init(self):
        await self.pool.open()
        self.checkpointer = AsyncPostgresSaver(self.pool)
        await self.checkpointer.setup()
        
        # 加载配置
        with SessionLocal() as db:
            configs = self.config_manager.load_configs(db)
            main_config = configs["main"]
        
        # 加载 MCP 工具
        mcp_tools = await self.mcp_manager.get_tools(main_config.mcp_tools)
        
        # 构建 skills 路径
        skills_paths = [f"{settings.SKILL_DIR}/{name}" for name in main_config.skills]
        
        # 构建子代理
        subagents = self._build_subagents(configs["subagents"])
        
        # 创建代理
        self.compiled_agent = create_deep_agent(
            model=big_llm,
            backend=lambda runtime: get_thread_backend(...),
            checkpointer=self.checkpointer,
            tools=mcp_tools,
            skills=skills_paths,
            system_prompt=main_config.system_prompt,
            subagents=subagents,
            interrupt_on={...},
        )
    
    def _build_subagents(self, configs: list[AgentConfig]) -> list[SubAgent]:
        """根据配置构建子代理"""
        subagents = []
        for cfg in configs:
            tools = await self.mcp_manager.get_tools(cfg.mcp_tools)
            skills_paths = [f"{settings.SKILL_DIR}/{name}" for name in cfg.skills]
            
            subagent: SubAgent = {
                "name": cfg.name,
                "description": cfg.description,
                "system_prompt": cfg.system_prompt,
                "model": cfg.model or big_llm,
                "tools": tools,
                "skills": skills_paths,
            }
            subagents.append(subagent)
        return subagents
```

### 7.2 热重载支持

```python
class AgentManager:
    async def reload_configs(self):
        """热重载代理配置（无需重启服务）"""
        with SessionLocal() as db:
            if self.config_manager.reload_if_needed(db):
                await self.init()  # 重新初始化代理
                logger.info("[AgentManager] Configs reloaded")
                return True
        return False
```

---

## 八、依赖更新

### 8.1 pyproject.toml

```toml
dependencies = [
    # ... 现有依赖 ...
    "langchain-mcp-adapters>=0.1.0",  # MCP 工具适配器
]
```

---

## 九、配置文件更新

### 9.1 环境变量 (.env)

```bash
# 新增 MCP 相关配置
MCP_CACHE_TTL=300          # MCP 工具缓存时间（秒）
MCP_CONNECTION_TIMEOUT=30  # MCP 连接超时（秒）
```

---

## 十、兼容性说明

### 10.1 向后兼容

1. **现有 API 保持不变** - `/api/chat`, `/api/sessions` 等接口无需修改
2. **现有 Skill 验证流程保留** - 旧 API `/api/admin/skills/validate` 仍可用
3. **默认配置** - 若数据库无配置，使用硬编码默认值

### 10.2 迁移路径

1. 数据库迁移脚本自动创建新表
2. 首次启动时自动创建默认主代理配置
3. 现有 skills 自动同步到数据库

---

## 十一、实施计划

### Phase 1: 基础设施 (1-2天)
- [ ] 数据库模型定义
- [ ] 配置项添加
- [ ] 依赖安装

### Phase 2: MCP 管理 (2-3天)
- [ ] McpManager 实现
- [ ] MCP API 实现
- [ ] 连接测试

### Phase 3: 代理配置 (2-3天)
- [ ] AgentConfigManager 实现
- [ ] 代理配置 API 实现
- [ ] AgentManager 改造

### Phase 4: Skill 简化 (1天)
- [ ] SimpleSkillManager 实现
- [ ] 简化上传 API

### Phase 5: 测试与文档 (1-2天)
- [ ] 单元测试
- [ ] 集成测试
- [ ] API 文档更新

---

## 十二、风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| MCP 连接不稳定 | 工具调用失败 | 实现重试机制、降级处理 |
| 配置热重载失败 | 需要重启服务 | 提供手动重载接口、回滚机制 |
| Skills 目录权限问题 | 无法写入 | 启动时检查权限、明确错误提示 |

---

## 十三、附录

### A. MCP 配置格式参考

兼容 OpenCode/Claude Code 格式：

```json
// stdio 模式
{
  "name": "filesystem",
  "transport": "stdio",
  "command": "npx",
  "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path/to/dir"],
  "env": {}
}

// HTTP 模式
{
  "name": "api-server",
  "transport": "http",
  "url": "https://api.example.com/mcp",
  "headers": {
    "Authorization": "Bearer token"
  }
}

// SSE 模式
{
  "name": "streaming-server",
  "transport": "sse",
  "url": "https://api.example.com/mcp/stream"
}
```

### B. 默认主代理配置

```python
DEFAULT_MAIN_CONFIG = {
    "name": "main",
    "is_main": True,
    "system_prompt": """
    用户的工作目录在/workspace中，若无明确要求，请在/workspace目录【及子目录】下执行操作,
    当你不明确用户需求时，可以调用提问工具向用户提问(可以同时提多个问题)，这个提问工具最多调用两次
    优先尝试使用已有的skill完成任务
    """,
    "mcp_tools": [],
    "skills": [],
    "subagents": [],
}
```
