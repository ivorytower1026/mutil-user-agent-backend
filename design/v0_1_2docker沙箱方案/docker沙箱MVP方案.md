# Docker沙箱MVP实现方案

> 最小可行性实现，分3个迭代完成

---

## 迭代概览

| 迭代 | 目标 | 核心改动 | 预计时间 |
|------|------|---------|---------|
| **迭代1** | 容器持久化 | 改造docker_sandbox.py，容器不立即销毁 | 0.5天 |
| **迭代2** | Skill目录挂载 | 添加shared/skills目录，只读挂载到容器 | 0.5天 |
| **迭代3** | Skill管理API | 上传/验证/删除skill的管理接口 | 1天 |

---

## 迭代1：容器持久化

### 目标
- 容器在会话期间保持运行，不再每次执行后销毁
- 支持显式销毁容器

### 改动文件

#### 1.1 改造 `src/docker_sandbox.py`

**当前问题**：
```python
# 当前代码：每次execute后都销毁容器
def execute(self, command: str) -> ExecuteResponse:
    container = None
    try:
        container = self._create_container()  # 每次创建
        container.start()
        # ... 执行命令
    finally:
        if container:
            container.remove(force=True)  # 每次销毁
```

**改为**：
```python
class DockerSandboxBackend(BaseSandbox):
    def __init__(self, thread_id: str, workspace_dir: str):
        self.thread_id = thread_id
        self.workspace_dir = workspace_dir
        self.image = settings.DOCKER_IMAGE
        self.client = docker.from_env()
        self._container: Container | None = None  # 持久化容器

    @property
    def id(self) -> str:
        return self.thread_id

    def _ensure_container(self) -> Container:
        """确保容器存在（懒加载）"""
        if self._container is None:
            self._container = self._create_container()
            self._container.start()
        return self._container

    def execute(self, command: str) -> ExecuteResponse:
        container = self._ensure_container()  # 复用容器
        
        exit_code, output = container.exec_run(
            cmd=["/bin/bash", "-lc", command],
            workdir=settings.CONTAINER_WORKSPACE_DIR,
        )

        return ExecuteResponse(
            output=output.decode('utf-8'),
            exit_code=exit_code,
            truncated=False
        )

    def destroy(self) -> None:
        """显式销毁容器"""
        if self._container:
            self._container.remove(force=True)
            self._container = None
```

#### 1.2 修改 `get_thread_backend` 工厂函数

```python
def get_thread_backend(thread_id: str) -> 'DockerSandboxBackend':
    if thread_id not in _thread_backends:
        user_id = thread_id.split('-')[0]
        workspace_dir = os.path.join(
            Path(settings.WORKSPACE_ROOT).expanduser().absolute(),
            user_id,
            thread_id
        )
        os.makedirs(workspace_dir, exist_ok=True)
        _thread_backends[thread_id] = DockerSandboxBackend(thread_id, workspace_dir)
    return _thread_backends[thread_id]

def destroy_thread_backend(thread_id: str) -> None:
    """销毁thread的backend和容器"""
    if thread_id in _thread_backends:
        _thread_backends[thread_id].destroy()
        del _thread_backends[thread_id]
```

#### 1.3 添加销毁会话API

**文件**: `api/server.py`

```python
@router.delete("/sessions/{thread_id}")
async def destroy_session(
    thread_id: str,
    user: str = Depends(get_current_user)
):
    """销毁会话和容器"""
    from src.docker_sandbox import destroy_thread_backend
    destroy_thread_backend(thread_id)
    return {"status": "destroyed", "thread_id": thread_id}
```

### 验证
```bash
# 创建会话
curl -X POST http://localhost:8002/api/sessions -H "Authorization: Bearer $TOKEN"

# 多次执行命令（应该复用同一容器）
curl -X POST http://localhost:8002/api/chat/$THREAD_ID -d '{"message":"echo hello1"}'
curl -X POST http://localhost:8002/api/chat/$THREAD_ID -d '{"message":"echo hello2"}'

# 销毁会话
curl -X DELETE http://localhost:8002/api/sessions/$THREAD_ID
```

---

## 迭代2：Skill目录挂载

### 目标
- 创建 `shared/skills/` 目录存放skill文件夹
- 容器启动时只读挂载skills目录到 `/skills`

### 改动文件

#### 2.1 创建目录结构

```bash
mkdir -p shared/skills
```

#### 2.2 添加示例Skill

```bash
mkdir -p shared/skills/example-skill
```

**文件**: `shared/skills/example-skill/SKILL.md`
```markdown
---
name: example-skill
description: 示例技能，演示skill的基本结构
---

# 示例技能

## 功能
这是一个示例skill，用于测试skill挂载是否正常工作。

## 使用方法
在 /skills/example-skill/ 目录下可以找到本文件。
```

#### 2.3 修改 `src/docker_sandbox.py`

```python
def _create_container(self) -> Container:
    """创建容器"""
    skills_dir = str(Path(settings.SHARED_DIR).expanduser().absolute() / "skills")
    
    # 确保skills目录存在
    os.makedirs(skills_dir, exist_ok=True)
    
    return self.client.containers.create(
        image=self.image,
        command="sleep infinity",
        working_dir=settings.CONTAINER_WORKSPACE_DIR,
        volumes={
            self.workspace_dir: {
                "bind": settings.CONTAINER_WORKSPACE_DIR, 
                "mode": "rw"
            },
            skills_dir: {
                "bind": settings.CONTAINER_SKILLS_DIR,  # 新增
                "mode": "ro"  # 只读
            }
        }
    )
```

#### 2.4 添加配置项

**文件**: `src/config.py`

```python
class Settings(BaseSettings):
    # ... 现有配置 ...
    
    # 新增
    CONTAINER_SKILLS_DIR: str = "/skills"
```

**文件**: `.env`
```env
SHARED_DIR=./shared
CONTAINER_SKILLS_DIR=/skills
```

### 验证
```bash
# 创建会话后，让agent查看skills目录
curl -X POST http://localhost:8002/api/chat/$THREAD_ID \
  -d '{"message":"列出 /skills 目录的内容"}'

# 预期输出：应该看到 example-sskill/SKILL.md
```

---

## 迭代3：Skill管理API

### 目标
- 管理员可以上传skill（文件夹）
- 验证skill格式
- 列出/删除skill

### 新建文件

#### 3.1 新建 `src/skill_manager.py`

```python
import os
import yaml
from pathlib import Path
from dataclasses import dataclass
from typing import Optional

from src.config import settings


@dataclass
class SkillMeta:
    name: str
    description: str
    path: str


class SkillManager:
    SKILLS_DIR = Path(settings.SHARED_DIR) / "skills"
    
    def __init__(self):
        self.SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    
    def list_skills(self) -> list[SkillMeta]:
        skills = []
        for skill_dir in self.SKILLS_DIR.iterdir():
            if skill_dir.is_dir():
                meta = self._parse_skill_meta(skill_dir)
                if meta:
                    skills.append(meta)
        return skills
    
    def get_skill(self, skill_name: str) -> Optional[SkillMeta]:
        skill_dir = self.SKILLS_DIR / skill_name
        if skill_dir.exists():
            return self._parse_skill_meta(skill_dir)
        return None
    
    def _parse_skill_meta(self, skill_dir: Path) -> Optional[SkillMeta]:
        skill_file = skill_dir / "SKILL.md"
        if not skill_file.exists():
            return None
        
        content = skill_file.read_text(encoding="utf-8")
        if not content.startswith("---"):
            return None
        
        parts = content.split("---", 2)
        if len(parts) < 3:
            return None
        
        try:
            frontmatter = yaml.safe_load(parts[1])
            return SkillMeta(
                name=frontmatter.get("name", skill_dir.name),
                description=frontmatter.get("description", ""),
                path=str(skill_dir)
            )
        except:
            return None
    
    def upload_skill(self, skill_name: str, files: dict[str, bytes]) -> SkillMeta:
        import shutil
        
        # 清理旧目录
        skill_dir = self.SKILLS_DIR / skill_name
        if skill_dir.exists():
            shutil.rmtree(skill_dir)
        skill_dir.mkdir(parents=True)
        
        # 写入文件
        for file_path, content in files.items():
            file_path = file_path.lstrip("/")
            full_path = skill_dir / file_path
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_bytes(content)
        
        meta = self._parse_skill_meta(skill_dir)
        if not meta:
            shutil.rmtree(skill_dir)
            raise ValueError("Invalid SKILL.md format")
        
        return meta
    
    def validate_skill(self, skill_name: str) -> dict:
        skill_dir = self.SKILLS_DIR / skill_name
        errors = []
        warnings = []
        
        skill_file = skill_dir / "SKILL.md"
        if not skill_file.exists():
            return {"valid": False, "errors": ["SKILL.md not found"], "warnings": []}
        
        meta = self._parse_skill_meta(skill_dir)
        if not meta:
            errors.append("Invalid SKILL.md: missing frontmatter")
        elif not meta.name:
            errors.append("Skill name is required")
        
        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings
        }
    
    def delete_skill(self, skill_name: str) -> bool:
        import shutil
        skill_dir = self.SKILLS_DIR / skill_name
        if skill_dir.exists():
            shutil.rmtree(skill_dir)
            return True
        return False
```

#### 3.2 新建 `api/admin.py`

```python
from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Depends

from src.skill_manager import SkillManager, SkillMeta
from src.auth import get_current_user

router = APIRouter(prefix="/admin", tags=["admin"])


def get_admin_user(user: str = Depends(get_current_user)) -> str:
    """验证管理员权限（简化版：所有用户都是管理员）"""
    return user


@router.get("/skills")
async def list_skills() -> list[dict]:
    """列出所有Skills"""
    manager = SkillManager()
    skills = manager.list_skills()
    return [
        {"name": s.name, "description": s.description}
        for s in skills
    ]


@router.post("/skills/{skill_name}")
async def upload_skill(
    skill_name: str,
    files: list[UploadFile] = File(...),
    admin: str = Depends(get_admin_user)
) -> dict:
    """上传Skill"""
    manager = SkillManager()
    
    file_dict = {}
    for file in files:
        file_dict[file.filename] = await file.read()
    
    try:
        meta = manager.upload_skill(skill_name, file_dict)
        return {"status": "created", "name": meta.name}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/skills/{skill_name}/validate")
async def validate_skill(skill_name: str) -> dict:
    """验证Skill"""
    manager = SkillManager()
    result = manager.validate_skill(skill_name)
    return result


@router.delete("/skills/{skill_name}")
async def delete_skill(
    skill_name: str,
    admin: str = Depends(get_admin_user)
) -> dict:
    """删除Skill"""
    manager = SkillManager()
    if manager.delete_skill(skill_name):
        return {"status": "deleted"}
    raise HTTPException(status_code=404, detail="Skill not found")
```

#### 3.3 注册路由

**文件**: `main.py`

```python
from api.admin import router as admin_router

# 添加管理员路由
app.include_router(admin_router, prefix="/api")
```

#### 3.4 添加依赖

**文件**: `pyproject.toml`

```toml
dependencies = [
    # ... 现有依赖 ...
    "pyyaml>=6.0",
]
```

### 验证

```bash
# 列出skills
curl http://localhost:8002/api/admin/skills

# 上传skill
curl -X POST http://localhost:8002/api/admin/skills/my-skill \
  -F "files=SKILL.md;type=text/plain" \
  -H "Authorization: Bearer $TOKEN" \
  --data-binary @- << 'EOF'
---name: my-skill
description: 测试skill
---

# My Skill
测试内容
EOF

# 验证skill
curl -X POST http://localhost:8002/api/admin/skills/my-skill/validate

# 删除skill
curl -X DELETE http://localhost:8002/api/admin/skills/my-skill \
  -H "Authorization: Bearer $TOKEN"
```

---

## 文件变更汇总

| 迭代 | 文件 | 操作 |
|------|------|------|
| 1 | `src/docker_sandbox.py` | 改造：容器持久化 |
| 1 | `api/server.py` | 添加：DELETE /sessions/{thread_id} |
| 2 | `src/config.py` | 添加：CONTAINER_SKILLS_DIR |
| 2 | `src/docker_sandbox.py` | 添加：skills目录挂载 |
| 2 | `shared/skills/example-skill/SKILL.md` | 新建：示例skill |
| 3 | `src/skill_manager.py` | 新建：Skill管理逻辑 |
| 3 | `api/admin.py` | 新建：管理API |
| 3 | `main.py` | 添加：注册admin路由 |
| 3 | `pyproject.toml` | 添加：pyyaml依赖 |

---

## 测试计划

### 迭代1测试
1. 创建会话，执行多次命令，确认容器ID不变
2. 销毁会话，确认容器被删除

### 迭代2测试
1. 检查容器内 `/skills` 目录存在
2. Agent能读取skill内容

### 迭代3测试
1. 上传skill成功
2. 列出skill包含新上传的
3. 删除skill成功
