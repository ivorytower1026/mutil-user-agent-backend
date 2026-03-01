# v0.2.3 LLM动态配置

## 背景

当前项目的LLM配置硬编码在 `src/config.py` 中，通过 `LLM_MODE` 环境变量切换，存在以下问题：

- 无法通过API动态修改
- 不支持运行时热更新
- 无法同时支持多种LLM提供商（Ollama、VLLM等）

## 目标

1. 支持通过Admin API动态配置LLM
2. 支持Ollama和VLLM部署的接口
3. 全局统一配置（所有用户使用相同的big_llm和flash_llm）
4. 配置变更仅对新会话生效
5. 保留环境变量作为默认/fallback配置

## 架构设计

```
┌─────────────────────────────────────────────────────────────┐
│                     Admin API Layer                          │
│  POST/GET/PUT/DELETE /api/admin/llm/*                       │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    LLM Manager                               │
│  - 管理LLM实例缓存                                           │
│  - 从数据库读取配置                                          │
│  - Fallback到环境变量                                        │
└─────────────────────────────────────────────────────────────┘
                              │
          ┌───────────────────┼───────────────────┐
          ▼                   ▼                   ▼
┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐
│   PostgreSQL    │ │  环境变量/.env  │ │  LLM Provider   │
│  (LlmConfig表)  │ │   (Fallback)    │ │  (Ollama/VLLM)  │
└─────────────────┘ └─────────────────┘ └─────────────────┘
```

## 数据库模型

### LlmConfig 表

```python
class LlmConfig(Base):
    """LLM配置模型"""
    __tablename__ = "llm_configs"
    
    id = Column(String(50), primary_key=True)
    name = Column(String(64), unique=True, nullable=False)  # 配置名称
    display_name = Column(String(100))  # 显示名称
    description = Column(String(512))  # 描述
    
    # Provider配置
    provider = Column(String(20), nullable=False)  # ollama/vllm/openai/zhipuai
    base_url = Column(String(255), nullable=False)  # API地址
    api_key = Column(String(255), nullable=False)  # API密钥
    model_name = Column(String(100), nullable=False)  # 模型名称
    
    # 模型参数
    temperature = Column(Float, default=0.7)
    max_tokens = Column(Integer, default=4096)
    extra_params = Column(JSON, default=dict)  # 额外参数，如 extra_body
    
    # 角色和状态
    role = Column(String(20), nullable=False, index=True)  # "big" / "flash"
    is_active = Column(Boolean, default=True, index=True)
    
    # 审计字段
    created_by = Column(String(50), ForeignKey("users.user_id"))
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
```

### 字段说明

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| id | String(50) | 是 | 主键，UUID |
| name | String(64) | 是 | 配置名称，唯一 |
| display_name | String(100) | 否 | 显示名称 |
| description | String(512) | 否 | 描述 |
| provider | String(20) | 是 | 提供商：ollama/vllm/openai/zhipuai |
| base_url | String(255) | 是 | API地址 |
| api_key | String(255) | 是 | API密钥（Ollama可填"EMPTY"） |
| model_name | String(100) | 是 | 模型名称 |
| temperature | Float | 否 | 温度参数，默认0.7 |
| max_tokens | Integer | 否 | 最大token数，默认4096 |
| extra_params | JSON | 否 | 额外参数 |
| role | String(20) | 是 | 角色：big（主模型）/flash（快速模型） |
| is_active | Boolean | 否 | 是否激活，默认True |

## API设计

### 端点列表

| 端点 | 方法 | 描述 |
|------|------|------|
| `/api/admin/llm/configs` | GET | 列出所有LLM配置 |
| `/api/admin/llm/configs` | POST | 创建新LLM配置 |
| `/api/admin/llm/configs/{id}` | GET | 获取配置详情 |
| `/api/admin/llm/configs/{id}` | PUT | 更新LLM配置 |
| `/api/admin/llm/configs/{id}` | DELETE | 删除LLM配置 |
| `/api/admin/llm/configs/{id}/activate` | POST | 激活配置（同role其他自动停用） |
| `/api/admin/llm/test` | POST | 测试LLM连接 |

### 请求/响应模型

#### 创建配置请求

```json
{
  "name": "ollama-llama3",
  "display_name": "Ollama Llama3",
  "description": "本地Ollama部署的Llama3模型",
  "provider": "ollama",
  "base_url": "http://localhost:11434/v1",
  "api_key": "EMPTY",
  "model_name": "llama3",
  "temperature": 0.7,
  "max_tokens": 4096,
  "extra_params": {},
  "role": "big"
}
```

#### 配置响应

```json
{
  "id": "uuid-xxx",
  "name": "ollama-llama3",
  "display_name": "Ollama Llama3",
  "description": "本地Ollama部署的Llama3模型",
  "provider": "ollama",
  "base_url": "http://localhost:11434/v1",
  "model_name": "llama3",
  "temperature": 0.7,
  "max_tokens": 4096,
  "role": "big",
  "is_active": true,
  "created_at": "2024-01-01T00:00:00",
  "updated_at": "2024-01-01T00:00:00"
}
```

#### 测试连接请求

```json
{
  "base_url": "http://localhost:11434/v1",
  "api_key": "EMPTY",
  "model_name": "llama3"
}
```

#### 测试连接响应

```json
{
  "success": true,
  "message": "Connection successful",
  "response_time_ms": 150
}
```

## 支持的Provider类型

| Provider | base_url示例 | api_key | 说明 |
|----------|-------------|---------|------|
| `ollama` | `http://localhost:11434/v1` | `EMPTY` | Ollama本地部署 |
| `vllm` | `http://localhost:8000/v1` | `EMPTY` | VLLM部署 |
| `openai` | `https://api.openai.com/v1` | `sk-xxx` | OpenAI官方 |
| `zhipuai` | `https://open.bigmodel.cn/api/paas/v4` | `xxx.xxx` | 智谱AI |

## 文件改动清单

| 文件 | 改动类型 | 主要内容 |
|------|----------|----------|
| `src/database.py` | 修改 | 新增 `LlmConfig` 模型 |
| `src/llm_manager.py` | **新建** | LLM管理器，缓存+fallback逻辑 |
| `src/config.py` | 修改 | 移除硬编码LLM实例，保留env配置作为fallback |
| `src/agent_manager.py` | 修改 | 从 `LLMManager` 获取LLM |
| `src/agent_skills/skill_validator.py` | 修改 | 从 `LLMManager` 获取LLM |
| `api/admin.py` | 修改 | 新增LLM配置管理API |
| `api/models.py` | 修改 | 新增LLM相关Pydantic模型 |

## LLM Manager 核心逻辑

```python
class LLMManager:
    """动态LLM配置管理器"""
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._cache = {}
            cls._instance._config_version = {}
        return cls._instance
    
    def get_big_llm(self, db: Session) -> ChatOpenAI:
        """获取主模型"""
        return self._get_llm_by_role("big", db)
    
    def get_flash_llm(self, db: Session) -> ChatOpenAI:
        """获取快速模型"""
        return self._get_llm_by_role("flash", db)
    
    def _get_llm_by_role(self, role: str, db: Session) -> ChatOpenAI:
        # 1. 检查缓存
        if role in self._cache:
            return self._cache[role]
        
        # 2. 从数据库获取active配置
        config = db.query(LlmConfig).filter(
            LlmConfig.role == role,
            LlmConfig.is_active == True
        ).first()
        
        if config:
            llm = self._create_llm(config)
            self._cache[role] = llm
            return llm
        
        # 3. Fallback到环境变量配置
        return self._get_fallback_llm(role)
    
    def _create_llm(self, config: LlmConfig) -> ChatOpenAI:
        """根据配置创建LLM实例"""
        return ChatOpenAI(
            model=config.model_name,
            base_url=config.base_url,
            api_key=config.api_key,
            temperature=config.temperature,
            max_tokens=config.max_tokens,
            **config.extra_params
        )
    
    def _get_fallback_llm(self, role: str) -> ChatOpenAI:
        """从环境变量获取fallback LLM"""
        from src.config import get_fallback_big_llm, get_fallback_flash_llm
        
        if role == "big":
            return get_fallback_big_llm()
        return get_fallback_flash_llm()
    
    def invalidate_cache(self, role: str = None):
        """清除缓存，配置变更时调用"""
        if role:
            self._cache.pop(role, None)
        else:
            self._cache.clear()


def get_llm_manager() -> LLMManager:
    """获取LLM管理器单例"""
    return LLMManager()
```

## 实施步骤

### Step 1: 新建 `src/llm_manager.py`

创建LLM管理器，实现：
- 单例模式
- LLM实例缓存
- 数据库配置读取
- 环境变量fallback

### Step 2: 修改 `src/database.py`

新增 `LlmConfig` 模型。

### Step 3: 修改 `src/config.py`

- 移除硬编码的 `big_llm` 和 `flash_llm` 实例
- 新增 `get_fallback_big_llm()` 和 `get_fallback_flash_llm()` 函数
- 保留环境变量配置作为fallback

### Step 4: 新增 `api/models.py` LLM相关Schema

```python
class LlmConfigCreate(BaseModel):
    name: str
    display_name: str | None = None
    description: str | None = None
    provider: str
    base_url: str
    api_key: str
    model_name: str
    temperature: float = 0.7
    max_tokens: int = 4096
    extra_params: dict = {}
    role: str

class LlmConfigUpdate(BaseModel):
    display_name: str | None = None
    description: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    model_name: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    extra_params: dict | None = None

class LlmTestRequest(BaseModel):
    base_url: str
    api_key: str
    model_name: str

class LlmConfigResponse(BaseModel):
    id: str
    name: str
    display_name: str | None
    description: str | None
    provider: str
    base_url: str
    model_name: str
    temperature: float
    max_tokens: int
    role: str
    is_active: bool
    created_at: str | None
    updated_at: str | None
```

### Step 5: 修改 `api/admin.py`

新增LLM配置管理API端点。

### Step 6: 修改 `src/agent_manager.py`

- 导入 `get_llm_manager`
- 使用 `LLMManager` 获取LLM实例

### Step 7: 修改 `src/agent_skills/skill_validator.py`

使用 `LLMManager` 获取LLM实例。

### Step 8: 添加测试

新增 `tests/test_llm_config.py` 测试API。

## 配置变更流程

```
1. Admin调用 POST /api/admin/llm/configs 创建新配置
2. Admin调用 POST /api/admin/llm/configs/{id}/activate 激活配置
3. API自动将同role的其他配置is_active设为False
4. 调用 llm_manager.invalidate_cache(role) 清除缓存
5. 新会话自动使用新配置
```

## 向后兼容

- 保留环境变量配置作为fallback
- 首次启动时，如果没有数据库配置，自动使用环境变量
- 迁移脚本可选择性将环境变量配置导入数据库

## 风险与缓解

| 风险 | 缓解措施 |
|------|----------|
| 配置错误导致服务不可用 | Fallback到环境变量配置 |
| API密钥泄露 | 数据库字段加密存储（可选） |
| 缓存不一致 | 配置变更时立即清除缓存 |

## 测试计划

1. **单元测试**
   - LLMManager缓存逻辑
   - Fallback机制

2. **集成测试**
   - API CRUD操作
   - 激活/停用逻辑
   - 连接测试

3. **端到端测试**
   - 创建配置 -> 激活 -> 新会话使用新配置
   - 删除配置 -> Fallback到环境变量
