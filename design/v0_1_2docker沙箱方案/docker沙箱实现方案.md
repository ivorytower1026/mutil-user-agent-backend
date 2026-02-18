# Docker沙箱实现方案（修订版）

> 基于行业最佳实践（OpenSandbox、E2B、deepagents）设计的容器生命周期管理方案

## 重要更正：Agent Skill 的正确定义

**Agent Skill 是一个文件夹**，不是Docker镜像！

### Agent Skill 结构

```
skill-name/
├── SKILL.md              # 核心文件（必须）
├── scripts/              # 脚本文件（可选）
│   ├── helper.py
│   └── process.sh
├── templates/            # 模板文件（可选）
│   └── report.html
└── references/           # 参考文档（可选）
    └── api-docs.md
```

### SKILL.md 格式

```markdown
---
name: skill-name
description: 简要描述该Skill的功能以及使用场景（最多1024字符）
---

# Skill名称

## 功能说明
为 Claude 提供清晰的分步操作指导

## 使用示例
展示该Skill的具体应用场景和使用方法

## 相关文件
- scripts/helper.py - 辅助脚本
- templates/report.html - 报告模板
```

### 与Docker的关系

```
┌─────────────────────────────────────────────────────────────┐
│                    Host Machine                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  share dir [agent skills etc.]                       │   │
│  │  ├── skill-pdf/                                      │   │
│  │  │   └── SKILL.md                                    │   │
│  │  ├── skill-excel/                                    │   │
│  │  │   └── SKILL.md                                    │   │
│  │  └── skill-webapp/                                   │   │
│  │      └── SKILL.md                                    │   │
│  └──────────────────────────────────────────────────────┘   │
│                            │                                 │
│                            │ 只读挂载 (read only)             │
│                            ▼                                 │
│  ┌──────────────────────────────────────────────────────┐   │
│  │                    Docker Container                   │   │
│  │  ┌─────────────┐  ┌─────────────┐                    │   │
│  │  │ /skills/    │  │ /workspace/ │                    │   │
│  │  │ (只读)      │  │ (读写)      │                    │   │
│  │  └─────────────┘  └─────────────┘                    │   │
│  │                                                       │   │
│  │  deepagents 读取 SKILL.md → 执行指令 → 操作 /workspace│   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

---

## 一、参考项目分析

| 项目 | 核心特点 | 适用场景 |
|------|---------|---------|
| **OpenSandbox (Alibaba)** | Pool预分配、生命周期管理、Docker+K8s双运行时 | 生产级大规模部署 |
| **E2B** | Dockerfile模板、快照机制、毫秒级冷启动 | SaaS服务、快速迭代 |
| **deepagents (LangChain)** | BaseSandbox抽象、只需实现execute() | Agent框架集成 |
| **Claude Skills** | 文件夹结构、SKILL.md核心、渐进式加载 | 知识/指令封装 |

### 关键借鉴

1. **OpenSandbox**: 
   - Pool-based容器管理
   - 容器生命周期状态机
   - 自动过期清理机制

2. **Claude Skills**:
   - Skill = 文件夹 + SKILL.md
   - 渐进式加载（先加载描述，按需加载内容）
   - 可包含脚本、模板、参考文档

3. **deepagents**:
   - BaseSandbox基类，只需实现`execute()`方法
   - 文件操作由基类通过execute实现

---

## 二、架构总览

```
┌────────────────────────────────────────────────────────────────┐
│                        API Layer                                │
│  /api/sessions  /api/chat  /api/admin/skills  /api/files       │
└────────────────────────────────────────────────────────────────┘
                               │
┌────────────────────────────────────────────────────────────────┐
│                  ContainerPoolManager                           │
│  ┌────────────────┐  ┌─────────────────┐  ┌─────────────────┐  │
│  │ IdlePool       │  │ ContainerTracker│  │ CleanupScheduler│  │
│  │ (2-3预热容器)   │  │ (状态追踪)       │  │ (30分钟超时)    │  │
│  └────────────────┘  └─────────────────┘  └─────────────────┘  │
└────────────────────────────────────────────────────────────────┘
                               │
┌────────────────────────────────────────────────────────────────┐
│                   SkillAwareSandboxBackend                      │
│  继承 deepagents.BaseSandbox                                    │
│  - 挂载共享skill目录（只读）                                     │
│  - 挂载用户工作区（读写）                                        │
│  - 持久化容器                                                    │
└────────────────────────────────────────────────────────────────┘
                               │
┌────────────────────────────────────────────────────────────────┐
│                     Docker Runtime                              │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐ │
│  │ sandbox1    │  │ sandbox2    │  │ share dir (skills)      │ │
│  │ userA       │  │ userB       │  │ 只读挂载到所有容器        │ │
│  └─────────────┘  └─────────────┘  └─────────────────────────┘ │
└────────────────────────────────────────────────────────────────┘
```

---

## 三、核心模块设计

### 3.1 Skill管理模块（新增）

**文件**: `src/skill_manager.py`

**功能**:
- 管理skill文件夹的上传、验证、存储
- 解析SKILL.md元数据
- 提供skill列表查询

**目录结构**:

```
shared/
└── skills/
    ├── skill-pdf/
    │   ├── SKILL.md
    │   └── scripts/
    ├── skill-excel/
    │   ├── SKILL.md
    │   └── templates/
    └── skill-webapp/
        └── SKILL.md
```

**核心实现**:

```python
# src/skill_manager.py
import os
import yaml
from pathlib import Path
from dataclasses import dataclass
from typing import Optional

@dataclass
class SkillMeta:
    """Skill元数据"""
    name: str
    description: str
    path: str
    has_scripts: bool = False
    has_templates: bool = False

class SkillManager:
    """Skill管理器"""
    
    SKILLS_DIR = Path(settings.SHARED_DIR) / "skills"
    
    def __init__(self):
        self.SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    
    def list_skills(self) -> list[SkillMeta]:
        """列出所有可用Skills"""
        skills = []
        for skill_dir in self.SKILLS_DIR.iterdir():
            if skill_dir.is_dir():
                skill_file = skill_dir / "SKILL.md"
                if skill_file.exists():
                    meta = self._parse_skill_meta(skill_file)
                    if meta:
                        meta.path = str(skill_dir)
                        meta.has_scripts = (skill_dir / "scripts").exists()
                        meta.has_templates = (skill_dir / "templates").exists()
                        skills.append(meta)
        return skills
    
    def get_skill(self, skill_name: str) -> Optional[SkillMeta]:
        """获取指定Skill"""
        skill_dir = self.SKILLS_DIR / skill_name
        skill_file = skill_dir / "SKILL.md"
        if skill_file.exists():
            return self._parse_skill_meta(skill_file)
        return None
    
    def _parse_skill_meta(self, skill_file: Path) -> Optional[SkillMeta]:
        """解析SKILL.md的frontmatter"""
        content = skill_file.read_text(encoding="utf-8")
        
        # 提取frontmatter
        if not content.startswith("---"):
            return None
        
        parts = content.split("---", 2)
        if len(parts) < 3:
            return None
        
        try:
            frontmatter = yaml.safe_load(parts[1])
            return SkillMeta(
                name=frontmatter.get("name", ""),
                description=frontmatter.get("description", ""),
                path=str(skill_file.parent)
            )
        except:
            return None
    
    def upload_skill(self, skill_name: str, files: dict[str, bytes]) -> SkillMeta:
        """上传Skill（管理员操作）"""
        skill_dir = self.SKILLS_DIR / skill_name
        skill_dir.mkdir(parents=True, exist_ok=True)
        
        for file_path, content in files.items():
            file_path = file_path.lstrip("/")
            full_path = skill_dir / file_path
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_bytes(content)
        
        # 验证必须有SKILL.md
        if not (skill_dir / "SKILL.md").exists():
            raise ValueError("SKILL.md is required")
        
        return self.get_skill(skill_name)
    
    def validate_skill(self, skill_name: str) -> dict:
        """验证Skill格式"""
        skill_dir = self.SKILLS_DIR / skill_name
        errors = []
        warnings = []
        
        # 检查SKILL.md是否存在
        skill_file = skill_dir / "SKILL.md"
        if not skill_file.exists():
            errors.append("SKILL.md not found")
            return {"valid": False, "errors": errors, "warnings": warnings}
        
        # 解析frontmatter
        meta = self._parse_skill_meta(skill_file)
        if not meta:
            errors.append("Invalid SKILL.md format: missing frontmatter")
        else:
            if not meta.name:
                errors.append("Skill name is required in frontmatter")
            elif not meta.name.replace("-", "").replace("_", "").isalnum():
                errors.append("Skill name should only contain letters, numbers, - and _")
            
            if not meta.description:
                warnings.append("Skill description is recommended")
            elif len(meta.description) > 1024:
                errors.append("Description exceeds 1024 characters")
        
        # 检查脚本安全性
        scripts_dir = skill_dir / "scripts"
        if scripts_dir.exists():
            for script in scripts_dir.rglob("*"):
                if script.is_file():
                    content = script.read_text(encoding="utf-8", errors="ignore")
                    # 简单的安全检查
                    dangerous_patterns = ["rm -rf", "sudo", "eval(", "exec("]
                    for pattern in dangerous_patterns:
                        if pattern in content:
                            warnings.append(f"Potentially dangerous pattern '{pattern}' in {script.name}")
        
        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings
        }
    
    def delete_skill(self, skill_name: str) -> bool:
        """删除Skill"""
        import shutil
        skill_dir = self.SKILLS_DIR / skill_name
        if skill_dir.exists():
            shutil.rmtree(skill_dir)
            return True
        return False
```

### 3.2 ContainerPoolManager

**文件**: `src/container_pool.py`

**与之前方案一致**，但挂载配置需要包含skill目录：

```python
async def _create_container(self, workspace_dir: str) -> Container:
    """创建容器"""
    skills_dir = Path(settings.SHARED_DIR) / "skills"
    
    return self._client.containers.create(
        image=settings.DOCKER_IMAGE,
        command="sleep infinity",
        working_dir="/workspace",
        volumes={
            workspace_dir: {"bind": "/workspace", "mode": "rw"},
            str(skills_dir): {"bind": "/skills", "mode": "ro"},  # 只读挂载skills
        }
    )
```

### 3.3 DockerSandboxBackend（改造）

**文件**: `src/docker_sandbox.py`

```python
class DockerSandboxBackend(BaseSandbox):
    def __init__(
        self,
        thread_id: str,
        workspace_dir: str,
        pool_manager: ContainerPoolManager
    ):
        self.thread_id = thread_id
        self.workspace_dir = workspace_dir
        self._pool_manager = pool_manager
        self._container: Container | None = None
    
    @property
    def id(self) -> str:
        return self.thread_id
    
    async def _ensure_container(self) -> Container:
        """确保容器存在（懒加载）"""
        if self._container is None:
            self._container = await self._pool_manager.get_or_create(
                self.thread_id,
                self.workspace_dir
            )
        return self._container
    
    def execute(self, command: str) -> ExecuteResponse:
        """执行命令 - Agent在此环境中读取/skills/执行任务"""
        container = asyncio.run(self._ensure_container())
        
        exit_code, output = container.exec_run(
            cmd=["/bin/bash", "-lc", command],
            workdir="/workspace"
        )
        
        return ExecuteResponse(
            output=output.decode('utf-8'),
            exit_code=exit_code,
            truncated=False
        )
    
    async def destroy(self):
        """销毁容器"""
        if self._container:
            await self._pool_manager.release(self.thread_id)
            self._container = None
```

---

## 四、文件目录结构

```
backend/
├── workspaces/                    # 用户工作区
│   └── {user_id}/
│       ├── {thread_id}/           # 会话工作区 → /workspace (rw)
│       │   ├── src/
│       │   ├── data/
│       │   └── output/
│       └── shared/                # 用户共享文件
│
├── shared/                        # 共享目录
│   └── skills/                    # Agent Skills → /skills (ro)
│       ├── skill-pdf/
│       │   ├── SKILL.md
│       │   └── scripts/
│       ├── skill-excel/
│       │   └── SKILL.md
│       └── skill-webapp/
│           └── SKILL.md
```

### 容器挂载配置

| 主机路径 | 容器路径 | 模式 | 说明 |
|---------|---------|------|------|
| `workspaces/{user_id}/{thread_id}` | `/workspace` | rw | 用户工作区 |
| `shared/skills` | `/skills` | ro | 只读的Skill库 |

---

## 五、API接口设计

### 5.1 用户端API（不变）

```python
# 创建会话
POST /api/sessions
Response: { thread_id: "..." }

# 对话
POST /api/chat/{thread_id}
Request: { message: "..." }
Response: SSE stream

# 上传文件到工作区
POST /api/files/{thread_id}/upload

# 下载文件
GET /api/files/{thread_id}/download?path=...

# 销毁会话
DELETE /api/sessions/{thread_id}
```

### 5.2 管理员API（Skill管理）

**文件**: `api/admin.py`

```python
from fastapi import APIRouter, UploadFile, Depends
from src.agent_skills.skill_manager import SkillManager

router = APIRouter()


@router.post("/skills")
async def upload_skill(
        skill_name: str,
        files: list[UploadFile],
        admin: str = Depends(get_admin_user)
):
    """上传Skill"""
    file_dict = {}
    for file in files:
        file_dict[file.filename] = await file.read()

    skill = SkillManager().upload_skill(skill_name, file_dict)
    return {"skill": skill.name, "status": "created"}


@router.get("/skills")
async def list_skills():
    """列出所有Skills"""
    skills = SkillManager().list_skills()
    return {
        "skills": [
            {
                "name": s.name,
                "description": s.description,
                "has_scripts": s.has_scripts,
                "has_templates": s.has_templates
            }
            for s in skills
        ]
    }


@router.post("/skills/{skill_name}/validate")
async def validate_skill(skill_name: str):
    """验证Skill"""
    result = SkillManager().validate_skill(skill_name)
    return result


@router.delete("/skills/{skill_name}")
async def delete_skill(
        skill_name: str,
        admin: str = Depends(get_admin_user)
):
    """删除Skill"""
    SkillManager().delete_skill(skill_name)
    return {"status": "deleted"}
```

---

## 六、Agent执行流程

```
1. 用户发送消息: "帮我生成一份PDF报告"

2. deepagents 接收请求:
   - 检查 /skills/ 目录下是否有匹配的skill
   - 读取 skill-pdf/SKILL.md 的 description
   - 匹配成功，加载完整SKILL.md内容

3. Agent执行:
   - 按照 SKILL.md 中的指令操作
   - 可能调用 scripts/helper.py
   - 使用 templates/report.html
   - 输出文件到 /workspace/output/

4. 用户获取结果:
   - 通过 /api/files/{thread_id}/download 下载
```

---

## 七、配置项

**文件**: `.env`

```env
# 容器池配置
CONTAINER_POOL_MAX=50
CONTAINER_POOL_IDLE_SIZE=3
CONTAINER_IDLE_TIMEOUT_MINUTES=30

# 目录配置
WORKSPACE_ROOT=./workspaces
SHARED_DIR=./shared

# Docker配置
DOCKER_IMAGE=python:3.13-slim
CONTAINER_WORKSPACE_DIR=/workspace
CONTAINER_SKILLS_DIR=/skills
```

---

## 八、实现步骤

### Phase 1: 容器持久化 + 池管理（P0）

**目标**: 将容器从"临时执行"改为"持久运行"

**任务**:
1. 新建 `src/container_pool.py`
2. 改造 `src/docker_sandbox.py`
3. 在 `main.py` 中初始化池
4. 添加 `DELETE /api/sessions/{thread_id}` 端点

**预计工时**: 2-3天

### Phase 2: Skill管理模块（P1）

**目标**: 支持Skill的上传、验证、查询

**任务**:
1. 新建 `src/skill_manager.py`
2. 创建 `shared/skills/` 目录结构
3. 新建 `api/admin.py` 管理员API
4. 实现Skill验证逻辑

**预计工时**: 2天

### Phase 3: 容器挂载优化（P1）

**目标**: 正确挂载skill目录到容器

**任务**:
1. 修改容器创建逻辑，添加skills只读挂载
2. 测试Agent读取skill功能
3. 添加skill加载日志

**预计工时**: 1天

### Phase 4: 前端集成（P2）

**目标**: 管理员界面上传skill

**任务**:
1. Skill上传界面
2. Skill列表展示
3. 验证结果反馈

**预计工时**: 2天

---

## 九、Skill示例

### 示例1: PDF生成Skill

```
skill-pdf/
├── SKILL.md
├── scripts/
│   └── generate.py
└── templates/
    └── base.html
```

**SKILL.md**:
```markdown
---
name: pdf-generator
description: 生成PDF文档，支持多种模板格式。当用户需要生成报告、文档、发票等PDF文件时使用。
---

# PDF生成器

## 功能说明
将内容转换为PDF格式，支持：
- Markdown转PDF
- HTML模板渲染
- 表格和图表

## 使用方法
1. 准备内容文件
2. 运行 `python /skills/skill-pdf/scripts/generate.py`
3. 输出文件在 /workspace/output/

## 相关文件
- scripts/generate.py - 主生成脚本
- templates/base.html - 基础HTML模板
```

### 示例2: 数据分析Skill

```
skill-data-analysis/
├── SKILL.md
└── scripts/
    ├── analyze.py
    └── visualize.py
```

---

## 十、注意事项

### 10.1 安全考虑

1. **Skill脚本安全**: 只读挂载防止skill被篡改
2. **脚本审查**: 上传时检查危险命令
3. **容器隔离**: 用户工作区互不干扰
4. **权限控制**: 只有管理员可以上传skill

### 10.2 性能优化

1. **预热池**: 减少容器启动延迟
2. **渐进式加载**: Agent按需读取skill内容
3. **只读挂载**: skills目录可被多个容器共享

### 10.3 兼容性

1. 保持与deepagents BaseSandbox接口兼容
2. Skill格式与Claude Skills兼容
3. 支持增量更新skill
