# 迭代3：Skill 管理 API

> 版本：v0.1.3
> 日期：2026-02-13
> 作者：AI Agent
> 更新：2026-02-13 新增依赖环境管理方案

---

## 一、四件套分析

### 1.1 现象（实际）

**业界现状**：


| 来源                | 验证方式                     | 上传方式        | 持久化   | Agent验证 | 审批流程 |
| :------------------ | :--------------------------- | :-------------- | :------- | :-------- | :------- |
| Anthropic API       | 格式验证（frontmatter 检查） | zip / multipart | 云端存储 | ❌ 无     | ❌ 无    |
| OpenAI Skills API   | 格式验证                     | zip / multipart | 云端存储 | ❌ 无     | ❌ 无    |
| agentskills.io 规范 | 结构规范定义                 | -               | -        | ❌ 无     | ❌ 无    |
| 本项目（迭代2）     | 格式验证 + 脚本安全检查      | 文件列表        | 文件系统 | ❌ 无     | ❌ 无    |

**业界限制**：

- `name`: max 64 字符，小写字母/数字/连字符
- `description`: max 1024 字符
- zip: max 50MB，最多 500 文件，单文件 max 25MB
- 必须包含 `SKILL.md`（大小写不敏感）

**本项目现状（迭代2后）**：

- ✅ Skill 目录挂载已实现（`/skills/` 只读）
- ✅ 简单 SkillManager 设计已有
- ❌ 无 zip 上传
- ❌ 无数据库持久化
- ❌ 无 Agent 能力验证
- ❌ 无验证报告
- ❌ 无审批流程

---

### 1.2 意图（期望）

**核心目标**：

1. 管理员上传 **zip 压缩包**（符合业界规范）
2. 后台 **自动格式验证** + **Agent 能力评估**（可选）
3. 生成 **结构化验证报告**
4. 管理员查看报告后 **手动批准入库**
5. 完整 **CRUD** + **状态流转**

**验收标准**：

- [ ]  上传 zip 包，自动解压到临时目录，状态为 `pending`
- [ ]  格式验证：SKILL.md 存在 + frontmatter 合法 + name/description 格式
- [ ]  Agent 验证：异步执行，评估清晰度/完整性/可操作性/触发准确性
- [ ]  验证报告：JSON 格式，含评分、优点、不足、建议
- [ ]  同时只能验证一个 Skill（全局锁）
- [ ]  评分阈值可配置（env）
- [ ]  管理员可批准/拒绝/再次验证/删除
- [ ]  只有 `approved` 的 Skill 对 Agent 可用

---

### 1.3 情境（环境约束）

**技术栈约束**：

- Python 3.13
- FastAPI + SQLAlchemy
- PostgreSQL
- Docker 沙箱
- 智谱 AI LLM

**文件系统约束**：

```
{SHARED_DIR}/
├── skills/                      # 正式目录（仅 approved）
│   └── approved-skill/
│       └── SKILL.md
└── skills_pending/              # 临时目录（pending/rejected）
    ├── pending-skill-1/
    │   └── SKILL.md
    └── rejected-skill-2/
        └── SKILL.md
```

**并发约束**：

- Agent 验证同时只能 1 个（全局锁）
- 上传/查询/删除无并发限制

**安全约束**：

- 仅管理员可操作（`is_admin=True`）
- 脚本安全检查（危险模式警告）
- 拒绝同名 Skill 上传（pending 状态下）

---

### 1.4 边界（明确不做）

**本迭代不做**：

- ❌ Skill 版本管理（v1, v2, default_version）
- ❌ Skill 分享/权限（用户组可见）
- ❌ Skill 在线编辑
- ❌ 前端管理界面
- ❌ Skill 使用统计
- ❌ 自动触发 Agent 验证（需手动触发）
- ❌ Skill marketplace / 商店
- ❌ 多级审批（只需管理员一人批准）
- ❌ 批量审批
- ❌ 自动审批（即使评分 100 分也需人工确认）
- ❌ 自动镜像构建（需手动触发导出）

---

## 二、状态流转

### 2.1 状态定义


| 状态         | 说明               | Agent 可用 | 可执行操作                 |
| :----------- | :----------------- | :--------- | :------------------------- |
| `pending`    | 待审批（初始状态） | ❌         | 验证、再次验证、批准、拒绝 |
| `validating` | Agent 验证中       | ❌         | 等待（不可操作）           |
| `approved`   | 已批准入库         | ✅         | 删除                       |
| `rejected`   | 已拒绝             | ❌         | 再次验证、删除             |

### 2.2 状态流转图

```
  上传 zip
      │
      ▼
┌───────────┐     触发验证      ┌─────────────┐     验证完成     ┌───────────┐
│  pending  │ ───────────────▶ │ validating  │ ───────────────▶ │  pending  │
│ (待审批)   │                   │  (验证中)    │                   │ (有报告)   │
└───────────┘                   └─────────────┘                   └───────────┘
      ▲                                 │                              │
      │                                 │ 失败                         │
      │                                 ▼                              │
      │                          ┌───────────┐                         │
      └──────────────────────────│  pending  │◀────────────────────────┘
           再次验证               │ (有报告)   │
                                 └───────────┘
                                       │
                     ┌─────────────────┼─────────────────┐
                     │                 │                 │
                     ▼                 ▼                 ▼
              ┌───────────┐     ┌───────────┐     ┌───────────┐
              │ approved  │     │ rejected  │     │ 再次验证   │
              │  (已批准)  │     │  (已拒绝)  │     │ (回到上面) │
              └───────────┘     └───────────┘     └───────────┘
                     │                 │
                     ▼                 ▼
               Agent 可用          可删除
```

### 2.3 典型使用场景

**场景 1：一次性通过**

```
上传 → pending → 验证 → pending(有报告) → 批准 → approved
```

**场景 2：多次验证后通过**

```
上传 → pending → 验证 → pending(报告不理想) → 再次验证 → pending(报告改善) → 批准 → approved
```

**场景 3：验证后拒绝**

```
上传 → pending → 验证 → pending(报告差) → 拒绝 → rejected → 删除
```

**场景 4：拒绝后修复重验**

```
上传 → pending → 验证 → pending → 拒绝 → rejected 
    → 上传新版本(覆盖) → pending → 验证 → 批准 → approved
```

---

## 三、API 设计

### 3.1 端点列表


| 方法     | 端点                                    | 说明               | 可执行状态         |
| :------- | :-------------------------------------- | :----------------- | :----------------- |
| `POST`   | `/api/admin/skills/upload`              | 上传 Skill zip     | -                  |
| `POST`   | `/api/admin/skills/{skill_id}/validate` | 触发/再次验证      | pending, rejected  |
| `POST`   | `/api/admin/skills/{skill_id}/approve`  | 批准入库           | pending            |
| `POST`   | `/api/admin/skills/{skill_id}/reject`   | 拒绝               | pending            |
| `DELETE` | `/api/admin/skills/{skill_id}`          | 删除               | rejected, approved |
| `GET`    | `/api/admin/skills`                     | 列表（可过滤状态） | -                  |
| `GET`    | `/api/admin/skills/{skill_id}`          | 详情               | -                  |
| `GET`    | `/api/admin/skills/{skill_id}/report`   | 验证报告           | -                  |
| `PUT`    | `/api/admin/skills/{skill_id}`          | 更新元信息         | pending            |

### 3.2 请求/响应模型

#### 上传 Skill

```http
POST /api/admin/skills/upload
Content-Type: multipart/form-data
Authorization: Bearer {token}

file: skill.zip
```

```json
// Response
{
  "skill_id": "uuid-xxx",
  "name": "csv-insights",
  "status": "pending",
  "format_valid": true,
  "format_errors": [],
  "message": "Skill uploaded, waiting for approval"
}
```

#### 触发验证

```http
POST /api/admin/skills/{skill_id}/validate
Authorization: Bearer {token}
```

```json
// Response
{
  "skill_id": "uuid-xxx",
  "message": "Validation started",
  "status": "validating"
}
```

#### 批准入库

```http
POST /api/admin/skills/{skill_id}/approve
Authorization: Bearer {token}
```

```json
// Response
{
  "skill_id": "uuid-xxx",
  "name": "csv-insights",
  "status": "approved",
  "approved_at": "2026-02-13T10:30:00Z",
  "message": "Skill approved and available to agents"
}
```

#### 拒绝

```http
POST /api/admin/skills/{skill_id}/reject
Authorization: Bearer {token}
Content-Type: application/json

{
  "reason": "Validation score too low"
}
```

```json
// Response
{
  "skill_id": "uuid-xxx",
  "status": "rejected",
  "rejected_at": "2026-02-13T10:30:00Z"
}
```

#### 列表查询

```http
GET /api/admin/skills?status=pending&page=1&size=20
Authorization: Bearer {token}
```

```json
// Response
{
  "skills": [
    {
      "skill_id": "uuid-xxx",
      "name": "csv-insights",
      "display_name": "CSV Insights",
      "description": "...",
      "status": "pending",
      "format_valid": true,
      "agent_validation_status": "success",
      "validation_score": 85,
      "created_at": "2026-02-13T10:00:00Z",
      "validated_at": "2026-02-13T10:05:00Z"
    }
  ],
  "total": 10,
  "page": 1,
  "size": 20
}
```

#### 验证报告

```http
GET /api/admin/skills/{skill_id}/report
Authorization: Bearer {token}
```

```json
// Response
{
  "skill_id": "uuid-xxx",
  "skill_name": "csv-insights",
  "validation_status": "valid",
  "format_check": {
    "passed": true,
    "errors": [],
    "warnings": ["Unusual file type: template.pptx"]
  },
  "agent_check": {
    "clarity_score": 85,
    "completeness_score": 75,
    "actionability_score": 90,
    "trigger_accuracy_score": 80,
    "overall_score": 82.5,
    "summary": "一个结构清晰的 CSV 分析 Skill",
    "strengths": [
      "工作流程分步骤清晰",
      "包含具体示例"
    ],
    "weaknesses": [
      "缺少错误处理指导"
    ]
  },
  "overall_score": 82.5,
  "recommendations": [
    "增加错误场景处理说明",
    "添加更多边界情况示例"
  ],
  "validated_at": "2026-02-13T10:05:00Z"
}
```

---

## 四、数据库设计

### 4.1 修改 User 表

```python
# src/database.py

class User(Base):
    __tablename__ = "users"

    user_id = Column(String(50), primary_key=True)
    username = Column(String(50), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    is_admin = Column(Boolean, default=False)  # 新增
    created_at = Column(DateTime, server_default=func.now())
```

### 4.2 新增 Skill 表

```python
class Skill(Base):
    __tablename__ = "skills"

    skill_id = Column(String(50), primary_key=True)
    name = Column(String(64), unique=True, nullable=False)
    display_name = Column(String(100))
    description = Column(String(1024))
  
    # 状态管理
    status = Column(String(20), default="pending", nullable=False)
    # pending / validating / approved / rejected
  
    # 文件信息
    skill_path = Column(String(255), nullable=False)
    extra_files = Column(JSON, default=list)
  
    # 格式验证
    format_valid = Column(Boolean, default=False)
    format_errors = Column(JSON, default=list)
    format_warnings = Column(JSON, default=list)
  
    # Agent 验证
    agent_validation_status = Column(String(20))  # pending / success / failed
    validation_report = Column(Text)
    validation_score = Column(Float)
    validation_count = Column(Integer, default=0)
    validated_at = Column(DateTime)
  
    # 审批信息
    approved_by = Column(String(50), ForeignKey("users.user_id"))
    approved_at = Column(DateTime)
    rejected_by = Column(String(50), ForeignKey("users.user_id"))
    rejected_at = Column(DateTime)
    reject_reason = Column(String(500))
  
    # 依赖环境（新增）
    docker_image = Column(String(255))  # 依赖的 Docker 镜像，如 "python:3.13-slim"
    requirements = Column(Text)  # pip 依赖列表
    system_packages = Column(String(500))  # 系统包依赖，如 "ffmpeg,poppler-utils"
    
    # 元信息
    allowed_tools = Column(String(255))
    tags = Column(String(255))
    created_by = Column(String(50), ForeignKey("users.user_id"))
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
```

### 4.3 新增 SkillValidationLog 表

```python
class SkillValidationLog(Base):
    __tablename__ = "skill_validation_logs"

    log_id = Column(String(50), primary_key=True)
    skill_id = Column(String(50), ForeignKey("skills.skill_id"), nullable=False)
    validation_type = Column(String(20))  # format / agent
    status = Column(String(20))  # success / failed
    details = Column(Text)  # JSON
    created_at = Column(DateTime, server_default=func.now())
```

---

## 五、验证机制

### 5.1 格式验证（同步）

```python
# src/skill_validator.py

class SkillValidator:
    NAME_PATTERN = r'^[a-z0-9-]{1,64}$'
    DESCRIPTION_MAX_LEN = 1024
  
    def validate_structure(self, skill_dir: Path) -> dict:
        """验证目录结构"""
        errors = []
        warnings = []
      
        # 检查 SKILL.md
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.exists():
            errors.append("Missing required file: SKILL.md")
            return {"passed": False, "errors": errors, "warnings": warnings}
      
        # 检查目录名格式
        if not re.match(self.NAME_PATTERN, skill_dir.name):
            errors.append(f"Directory name must be lowercase, hyphens, max 64 chars")
      
        return {"passed": len(errors) == 0, "errors": errors, "warnings": warnings}
  
    def validate_frontmatter(self, skill_md: Path) -> dict:
        """验证 YAML frontmatter"""
        errors = []
        warnings = []
      
        content = skill_md.read_text(encoding='utf-8')
      
        if not content.startswith('---'):
            errors.append("SKILL.md must start with YAML frontmatter")
            return {"passed": False, "errors": errors, "warnings": warnings}
      
        parts = content.split('---', 2)
        if len(parts) < 3:
            errors.append("Invalid frontmatter format")
            return {"passed": False, "errors": errors, "warnings": warnings}
      
        try:
            frontmatter = yaml.safe_load(parts[1])
        except yaml.YAMLError as e:
            errors.append(f"Invalid YAML: {e}")
            return {"passed": False, "errors": errors, "warnings": warnings}
      
        # 检查 name
        if 'name' not in frontmatter:
            errors.append("Missing required field: name")
        elif not re.match(self.NAME_PATTERN, str(frontmatter['name'])):
            errors.append(f"Invalid name format: {frontmatter['name']}")
      
        # 检查 description
        if 'description' not in frontmatter:
            warnings.append("Missing recommended field: description")
        elif len(str(frontmatter['description'])) > self.DESCRIPTION_MAX_LEN:
            errors.append(f"Description exceeds {self.DESCRIPTION_MAX_LEN} chars")
      
        return {
            "passed": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
            "frontmatter": frontmatter
        }
```

### 5.2 Agent 能力验证（异步）

```python
# src/skill_agent_validator.py

VALIDATION_PROMPT = """
你是一个 Skill 验证助手。请分析以下 Skill 的能力：

Skill 名称：{skill_name}
Skill 描述：{skill_description}

Skill 内容：
---
{skill_content}
---

请从以下维度评估这个 Skill（0-100分）：

1. **清晰度**：指令是否清晰明确？
2. **完整性**：是否包含足够的上下文和示例？
3. **可操作性**：指令是否可被 AI Agent 执行？
4. **触发准确性**：描述是否能准确匹配使用场景？

返回 JSON：
{{
    "clarity_score": <0-100>,
    "completeness_score": <0-100>,
    "actionability_score": <0-100>,
    "trigger_accuracy_score": <0-100>,
    "overall_score": <0-100>,
    "summary": "<一句话总结>",
    "strengths": ["<优点1>", "<优点2>"],
    "weaknesses": ["<不足1>"],
    "recommendations": ["<建议1>"]
}}
"""

class SkillAgentValidator:
    _validating_skill_id: str | None = None  # 全局锁
  
    @classmethod
    def is_validating(cls) -> bool:
        return cls._validating_skill_id is not None
  
    @classmethod
    def get_validating_skill(cls) -> str | None:
        return cls._validating_skill_id
  
    async def validate(self, skill_id: str, skill_name: str, 
                       skill_description: str, skill_content: str) -> dict:
        """执行 Agent 验证"""
        if self.is_validating():
            return {"error": "Another skill is being validated"}
      
        self._validating_skill_id = skill_id
        try:
            # 调用 LLM 验证
            prompt = VALIDATION_PROMPT.format(
                skill_name=skill_name,
                skill_description=skill_description,
                skill_content=skill_content[:8000]
            )
          
            response = await llm.ainvoke(prompt)
            return self._parse_result(response.content)
        finally:
            self._validating_skill_id = None
```

### 5.3 验证报告结构

```json
{
  "format_check": {
    "passed": true,
    "errors": [],
    "warnings": ["Unusual file type: template.pptx"]
  },
  "agent_check": {
    "clarity_score": 85,
    "completeness_score": 75,
    "actionability_score": 90,
    "trigger_accuracy_score": 80,
    "overall_score": 82.5,
    "summary": "一个结构清晰的 Skill",
    "strengths": ["工作流程分步骤清晰"],
    "weaknesses": ["缺少错误处理指导"],
    "recommendations": ["增加错误场景处理说明"]
  },
  "overall_score": 82.5
}
```

---

## 六、配置更新

### 6.1 环境变量

```env
# .env 新增

# Skill 验证配置
SKILL_VALIDATION_THRESHOLD=60  # Agent 验证通过阈值（0-100）
```

### 6.2 Settings 更新

```python
# src/config.py

class Settings(BaseSettings):
    # ... 现有配置 ...
  
    # Skill 验证
    SKILL_VALIDATION_THRESHOLD: int = 60
  
    @field_validator("SKILL_VALIDATION_THRESHOLD", mode="before")
    def parse_validation_threshold(cls, v):
        return int(v)
```

---

## 七、文件变更清单

| 文件                           | 操作     | 核心改动                                          |
| :----------------------------- | :------- | :------------------------------------------------ |
| `.env`                         | 修改     | +4 行 阈值配置 + 镜像管理配置                     |
| `src/config.py`                | 修改     | +10 行 阈值配置 + 镜像配置                        |
| `src/database.py`              | 修改     | +55 行 User.is_admin + Skill（含依赖字段）+ Log   |
| `src/skill_validator.py`       | **新建** | ~150 行 格式验证器 + 依赖验证                     |
| `src/skill_agent_validator.py` | **新建** | ~80 行 Agent 验证器 + 并发锁                      |
| `src/skill_image_builder.py`   | **新建** | ~150 行 镜像构建/导出/导入                        |
| `api/admin.py`                 | **新建** | ~380 行 管理员 API + 镜像管理 API                 |
| `api/models.py`                | 修改     | +100 行 Skill 相关 Pydantic 模型                  |
| `main.py`                      | 修改     | +2 行 注册 admin 路由                             |
| `tests/test_skills_api.py`     | **新建** | ~250 行 API 测试                                  |

**总计**：新建约 1110 行，修改约 170 行

---

## 八、实现步骤

### Phase 1：数据库模型（0.5天）

1. 修改 `src/database.py`
   - User 添加 `is_admin` 字段
   - 新增 `Skill` 表（含依赖字段）
   - 新增 `SkillValidationLog` 表
2. 创建迁移脚本（或自动建表）

### Phase 2：验证器（0.5天）

1. 新建 `src/skill_validator.py`
   - 目录结构验证
   - Frontmatter 验证
   - **依赖声明验证**（docker_image / requirements.txt）
   - 脚本安全检查
2. 新建 `src/skill_agent_validator.py`
   - Agent 验证逻辑
   - 全局锁实现
   - 结果解析

### Phase 3：镜像管理（0.5天）

1. 新建 `src/skill_image_builder.py`
   - Dockerfile 生成
   - 镜像构建
   - 镜像导出（docker save）
   - 镜像导入（docker load）
   - manifest.json 生成

### Phase 4：API 实现（1天）

1. 新建 `api/admin.py`
   - 上传接口
   - 验证接口
   - 审批接口（批准/拒绝）
   - CRUD 接口
   - **镜像管理接口**（导出/导入）
2. 修改 `api/models.py`
   - Skill 相关请求/响应模型
   - **依赖信息模型**

### Phase 5：集成测试（0.5天）

1. 新建 `tests/test_skills_api.py`
2. 测试完整流程：
   - 上传 → 验证 → 批准
   - 上传 → 验证 → 拒绝 → 删除
   - 并发验证限制
   - **依赖验证**
   - **镜像导出/导入**

### Phase 6：文档更新（0.5天）

1. 更新 AGENTS.md
2. 更新 main.py 根路由端点列表

---

## 九、测试用例

### 9.1 上传测试

```python
def test_upload_skill_success():
    """测试成功上传 Skill"""
    # 准备 zip 文件
    # 调用上传接口
    # 验证返回 pending 状态
    # 验证数据库记录
    pass

def test_upload_skill_invalid_format():
    """测试上传格式错误的 Skill"""
    # 准备无效 zip
    # 验证返回格式错误
    pass

def test_upload_duplicate_skill():
    """测试上传重复 Skill"""
    pass
```

### 9.2 验证测试

```python
def test_validate_skill():
    """测试 Skill 验证"""
    pass

def test_concurrent_validation_blocked():
    """测试并发验证被阻止"""
    pass
```

### 9.3 审批测试

```python
def test_approve_skill():
    """测试批准 Skill"""
    pass

def test_reject_skill():
    """测试拒绝 Skill"""
    pass

def test_delete_skill():
    """测试删除 Skill"""
    pass
```

### 9.4 依赖环境测试

```python
def test_validate_dependencies():
    """测试依赖验证"""
    pass

def test_build_skill_image():
    """测试构建 Skill 专用镜像"""
    pass

def test_export_import_image():
    """测试镜像导出和导入"""
    pass

def test_intranet_deployment():
    """测试内网部署流程"""
    pass
```

---

## 十、风险与缓解

> 详见 **十三、风险与缓解（更新）**

---

## 十一、后续迭代预览

### 迭代4：Skill 版本管理

- 版本号支持（v1, v2）
- default_version / latest_version
- 版本回滚

### 迭代5：Skill 权限管理

- 用户组可见性
- 组织级别共享

### 迭代6：Skill 使用分析

- 使用次数统计
- 效果评分
- 热门 Skill 排行

---

## 十二、依赖环境管理方案

### 12.1 问题背景

不同 Skill 可能需要不同的运行环境：
- Python 版本不同（3.10 / 3.11 / 3.13）
- pip 依赖不同（pandas, numpy, pdfplumber 等）
- 系统依赖不同（ffmpeg, poppler-utils 等）

**核心挑战**：
1. 如何让 Skill 声明自己的依赖？
2. 如何在验证时确保依赖可用？
3. 如何在内网环境复现验证时的环境？

### 12.2 依赖声明方式

**方案：Skill 根目录包含 `requirements.txt` + frontmatter 声明**

```
skill-name/
├── SKILL.md              # 必需
├── requirements.txt      # pip 依赖（可选）
└── scripts/
    └── helper.py
```

**SKILL.md frontmatter 扩展**：

```yaml
---
name: pdf-analyzer
description: PDF 文档分析和提取工具
docker_image: python:3.13-slim      # 可选：指定 Docker 镜像
system_packages: poppler-utils       # 可选：系统包依赖（逗号分隔）
python_version: "3.13"              # 可选：Python 版本要求
---

# PDF Analyzer Skill

...
```

### 12.3 验证时的依赖检查

**格式验证阶段**（同步）：

```python
def validate_dependencies(self, skill_dir: Path, frontmatter: dict) -> dict:
    """验证依赖声明"""
    errors = []
    warnings = []
    
    # 检查 requirements.txt
    req_file = skill_dir / "requirements.txt"
    if req_file.exists():
        try:
            # 解析 requirements.txt
            requirements = parse_requirements(req_file)
        except Exception as e:
            errors.append(f"Invalid requirements.txt: {e}")
    
    # 检查 docker_image 格式
    docker_image = frontmatter.get("docker_image")
    if docker_image:
        if not re.match(r'^[\w./-]+:[\w.-]+$', docker_image):
            errors.append(f"Invalid docker_image format: {docker_image}")
    
    # 检查 system_packages
    system_packages = frontmatter.get("system_packages")
    if system_packages:
        # 验证是逗号分隔的包名
        pass
    
    return {"passed": len(errors) == 0, "errors": errors, "warnings": warnings}
```

**Agent 验证阶段**（在验证容器中）：

```python
async def validate_with_dependencies(self, skill: Skill) -> dict:
    """在隔离环境中验证 Skill"""
    
    # 1. 创建临时容器（使用指定的 docker_image）
    container = create_validation_container(
        image=skill.docker_image or settings.DOCKER_IMAGE
    )
    
    # 2. 安装系统依赖
    if skill.system_packages:
        container.exec(f"apt-get update && apt-get install -y {skill.system_packages}")
    
    # 3. 安装 pip 依赖
    if has_requirements(skill):
        container.exec("pip install -r requirements.txt")
    
    # 4. 执行 Agent 验证
    result = await self._run_agent_validation(skill)
    
    # 5. 清理容器
    container.remove()
    
    return result
```

### 12.4 外网验证 → 内网部署流程

```
┌─────────────────────────────────────────────────────────────────────┐
│                         外网环境（验证）                             │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  1. 上传 Skill zip                                                  │
│           │                                                         │
│           ▼                                                         │
│  2. 格式验证（解析依赖声明）                                         │
│           │                                                         │
│           ▼                                                         │
│  3. 创建验证容器（docker_image 或默认）                              │
│           │                                                         │
│           ▼                                                         │
│  4. 安装依赖（requirements.txt + system_packages）                   │
│           │                                                         │
│           ▼                                                         │
│  5. Agent 能力验证                                                  │
│           │                                                         │
│           ▼                                                         │
│  6. 记录验证结果 + 实际使用的镜像                                    │
│           │                                                         │
│           ▼                                                         │
│  7. 批准入库                                                        │
│           │                                                         │
│           ▼                                                         │
│  8. 导出 Docker 镜像                                                │
│      docker save -o skill-name.tar <image>:<tag>                    │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              │ 物理传输（U盘/内网拷贝）
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         内网环境（生产）                             │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  1. 导入 Docker 镜像                                                │
│     docker load -i skill-name.tar                                   │
│           │                                                         │
│           ▼                                                         │
│  2. 上传 Skill zip（或直接拷贝到 skills 目录）                       │
│           │                                                         │
│           ▼                                                         │
│  3. 批准入库（无需再次验证）                                         │
│           │                                                         │
│           ▼                                                         │
│  4. Agent 可用                                                      │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### 12.5 Docker 镜像管理 API

新增 API 端点用于镜像管理：

| 方法 | 端点 | 说明 |
|:---|:---|:---|
| `GET` | `/api/admin/images` | 列出所有可用镜像 |
| `POST` | `/api/admin/images/export/{skill_id}` | 导出 Skill 依赖镜像 |
| `POST` | `/api/admin/images/import` | 导入镜像 tar 包 |
| `GET` | `/api/admin/skills/{skill_id}/dependencies` | 获取 Skill 依赖信息 |

**导出镜像**：

```http
POST /api/admin/images/export/{skill_id}
Authorization: Bearer {token}
```

```json
// Response
{
  "skill_id": "uuid-xxx",
  "skill_name": "pdf-analyzer",
  "docker_image": "skill-pdf-analyzer:validated-20260213",
  "export_path": "/exports/pdf-analyzer-20260213.tar",
  "size_mb": 450,
  "message": "Image exported successfully"
}
```

**导入镜像**：

```http
POST /api/admin/images/import
Content-Type: multipart/form-data
Authorization: Bearer {token}

file: pdf-analyzer-20260213.tar
```

```json
// Response
{
  "image_name": "skill-pdf-analyzer:validated-20260213",
  "size_mb": 450,
  "message": "Image imported successfully"
}
```

### 12.6 验证时的镜像固化策略

**方案：为每个 Skill 创建带依赖的专用镜像**

```python
# src/skill_image_builder.py

class SkillImageBuilder:
    BASE_IMAGE = "python:3.13-slim"
    
    async def build_skill_image(self, skill: Skill) -> str:
        """为 Skill 构建专用镜像"""
        
        # 镜像标签格式：skill-{name}:validated-{date}
        tag = f"skill-{skill.name}:validated-{datetime.now().strftime('%Y%m%d')}"
        
        # 构建 Dockerfile
        dockerfile = self._generate_dockerfile(skill)
        
        # 构建镜像
        # docker build -t {tag} -f Dockerfile.skill {skill_path}
        
        return tag
    
    def _generate_dockerfile(self, skill: Skill) -> str:
        """生成 Dockerfile"""
        lines = [
            f"FROM {skill.docker_image or self.BASE_IMAGE}",
            "",
            "# Install system packages",
        ]
        
        if skill.system_packages:
            lines.append(f"RUN apt-get update && apt-get install -y {skill.system_packages} && rm -rf /var/lib/apt/lists/*")
        
        lines.extend([
            "",
            "# Copy skill files",
            "COPY . /skill/",
            "",
            "# Install Python dependencies",
        ])
        
        if skill.requirements:
            lines.append("RUN pip install --no-cache-dir -r /skill/requirements.txt")
        
        return "\n".join(lines)
```

### 12.7 内网部署清单

**外网导出时生成的文件**：

```
export/
├── pdf-analyzer/                    # Skill 目录
│   ├── SKILL.md
│   ├── requirements.txt
│   └── scripts/
├── pdf-analyzer-20260213.tar        # Docker 镜像
└── manifest.json                    # 部署清单
```

**manifest.json**：

```json
{
  "export_time": "2026-02-13T10:30:00Z",
  "skills": [
    {
      "name": "pdf-analyzer",
      "skill_id": "uuid-xxx",
      "docker_image": "skill-pdf-analyzer:validated-20260213",
      "image_file": "pdf-analyzer-20260213.tar",
      "validation_score": 85,
      "dependencies": {
        "python_version": "3.13",
        "pip_packages": ["pdfplumber>=0.10.0", "pandas>=2.0.0"],
        "system_packages": ["poppler-utils"]
      }
    }
  ]
}
```

### 12.8 配置更新

```env
# .env 新增

# Skill 镜像管理
SKILL_IMAGE_EXPORT_DIR=./exports        # 镜像导出目录
SKILL_BASE_IMAGE=python:3.13-slim       # 默认基础镜像
SKILL_BUILD_IMAGES=true                 # 是否为 Skill 构建专用镜像
```

### 12.9 文件变更清单（新增）

| 文件 | 操作 | 核心改动 |
|:---|:---|:---|
| `src/skill_image_builder.py` | **新建** | ~150 行 镜像构建/导出/导入 |
| `src/skill_validator.py` | 修改 | +50 行 依赖验证逻辑 |
| `api/admin.py` | 修改 | +80 行 镜像管理 API |

---

## 十三、风险与缓解（更新）

| 风险 | 影响 | 缓解措施 |
|:---|:---|:---|
| 大文件上传超时 | 中 | 限制 zip 大小 50MB |
| Agent 验证耗时长 | 低 | 后台异步执行 + 全局锁 |
| 并发上传冲突 | 低 | 数据库唯一约束 |
| 磁盘空间不足 | 中 | 定期清理 rejected 文件 |
| Docker 镜像过大 | 高 | 使用 slim 镜像 + 多阶段构建 |
| 内网镜像传输慢 | 中 | 压缩传输 + 增量更新 |
| 依赖版本冲突 | 中 | 每个 Skill 使用独立镜像 |

### agent skill 与历史skill的依赖环境是否兼容

不同的skill需要的依赖环境不一样，如何管理依赖/docker 镜像 且能在内网访问
