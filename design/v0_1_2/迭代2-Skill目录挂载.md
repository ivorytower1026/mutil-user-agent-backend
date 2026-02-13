# 迭代2：Skill目录挂载

## 一、现象（实际）

### 当前行为

**文件**: `src/docker_sandbox.py:161-183`

```python
def _create_container(self) -> docker.models.containers.Container:
    # ...
    skills_dir = str(Path(settings.SHARED_DIR).expanduser().absolute())
    # ...
    return self.client.containers.create(
        # ...
        volumes={
            self.workspace_dir: {"bind": settings.CONTAINER_WORKSPACE_DIR, "mode": "rw"},
            user_shared_dir: {"bind": settings.USER_SHARED, "mode": "rw"},
            skills_dir: {"bind": settings.CONTAINER_SHARED_DIR, "mode": "ro"}  # 挂载到 /shared
        }
    )
```

### 问题表现

1. **概念混淆**：`SHARED_DIR` 挂载到 `/shared`，没有明确的 `/skills` 概念
2. **路径冗长**：Agent需要从 `/shared/skills/` 访问skill，路径较长
3. **无示例skill**：`shared/` 目录为空，没有可用的skill
4. **无独立挂载**：skills和shared混在一起，不利于权限管理

```
当前结构:
Host: shared/           → Container: /shared (只读)
Agent访问skill: /shared/skills/example-skill/SKILL.md (路径长)
```

---

## 二、意图（期望）

### 目标行为

1. **独立挂载**：`shared/skills/` 独立挂载到容器 `/skills`
2. **示例skill**：提供 `example-skill` 供测试和使用
3. **路径简洁**：Agent通过 `/skills/` 直接访问skill

### 期望架构

```
Host目录结构:
shared/
└── skills/                    ← 只读挂载到 /skills
    ├── example-skill/
    │   └── SKILL.md
    └── (其他skill...)

Container内挂载点:
/workspace     ← Thread工作空间 (rw)
/user_shared   ← 用户级共享 (rw)
/skills        ← 全局skills (ro) ← 新增独立挂载

Agent访问方式:
/skills/example-skill/SKILL.md  ← 路径简洁
```

### 用户体验提升

| 场景 | 当前 | 改后 |
|------|------|------|
| 访问skill | `/shared/skills/xxx` | `/skills/xxx` |
| 列出skills | `ls /shared/skills` | `ls /skills` |
| 概念清晰度 | 混淆（shared包含skills） | 清晰（独立挂载） |

---

## 三、情境（环境约束）

### 技术约束

| 约束项 | 说明 |
|--------|------|
| Python版本 | 3.13+ |
| Docker SDK | `docker` Python包 |
| 现有架构 | 基于迭代1的容器持久化方案 |
| 配置管理 | Pydantic Settings |

### 兼容性约束

1. **挂载点兼容**：保留 `/shared` 挂载（如果需要）
2. **配置扩展**：新增 `CONTAINER_SKILLS_DIR`，不影响现有配置
3. **现有测试通过**：`tests/test_v0_1_1.py` 和 `tests/test_mvp.py` 必须继续通过

### 文件系统约束

| 目录 | Host路径 | 容器路径 | 模式 |
|------|---------|---------|------|
| workspace | `{WORKSPACE_ROOT}/{user_id}/{thread_id}` | `/workspace` | rw |
| user_shared | `{WORKSPACE_ROOT}/{user_id}/shared` | `/user_shared` | rw |
| skills | `{SHARED_DIR}/skills` | `/skills` | ro |

### 运行环境

- Docker Desktop 或 Docker Engine
- Windows/Linux/macOS
- 容器镜像：`python:3.13-slim`

---

## 四、边界（明确不做）

### 本迭代不做

| 不做项 | 原因 | 计划迭代 |
|--------|------|---------|
| Skill上传API | 属于迭代3范围 | 迭代3 |
| Skill验证机制 | 属于迭代3范围 | 迭代3 |
| 多版本skill | 过度设计 | 不做 |
| Skill依赖管理 | 复杂度高 | 后续版本 |
| 动态加载/卸载 | 需要容器重建 | 不做 |
| Skill权限细粒度控制 | 非MVP需求 | 后续版本 |

### 明确排除的场景

1. **Skill热更新**：修改skill需要重建容器
2. **用户私有skill**：所有用户共享同一份skills
3. **Skill执行沙箱**：skill只是静态文件，不涉及执行

---

## 五、详细设计

### 5.1 目录结构

```
Host文件系统:
{SHARED_DIR}/
└── skills/
    └── example-skill/
        └── SKILL.md          ← 示例skill定义文件

容器内挂载:
/skills/
└── example-skill/
    └── SKILL.md              ← 只读访问
```

### 5.2 类图（无变化）

迭代2不涉及类结构变更，仅修改容器挂载配置。

### 5.3 代码改动

#### 5.3.1 新建 `shared/skills/example-skill/SKILL.md`

```markdown
---
name: example-skill
description: 示例技能，演示skill的基本结构
version: 1.0.0
author: system
---

# 示例技能

## 功能说明
这是一个示例skill，用于测试skill挂载是否正常工作。

## 使用方法
Agent可以在 `/skills/example-skill/` 目录下找到本文件。

## 示例命令
```bash
# 查看skill内容
cat /skills/example-skill/SKILL.md

# 列出所有skills
ls /skills/
```

## 注意事项
- Skills目录是只读的，不能修改
- 如需创建新skill，请联系管理员通过API上传
```

#### 5.3.2 修改 `src/config.py`

```python
class Settings(BaseSettings):
    # ... 现有配置 ...
    
    # 容器内路径
    CONTAINER_WORKSPACE_DIR: str
    USER_SHARED: str
    CONTAINER_SHARED_DIR: str
    CONTAINER_SKILLS_DIR: str = "/skills"  # 新增
```

#### 5.3.3 修改 `src/docker_sandbox.py`

**修改前**:
```python
def _create_container(self) -> docker.models.containers.Container:
    # ...
    skills_dir = str(Path(settings.SHARED_DIR).expanduser().absolute())
    # ...
    volumes={
        # ...
        skills_dir: {"bind": settings.CONTAINER_SHARED_DIR, "mode": "ro"}
    }
```

**修改后**:
```python
def _create_container(self) -> docker.models.containers.Container:
    """Create a new container (does not start it).
    
    Mounts:
    - /workspace: Thread-private workspace (rw)
    - /user_shared: User-level shared directory (rw)
    - /skills: Global shared skills directory (ro)
    """
    user_id = self.thread_id.split('-')[0]
    
    # User-level shared directory
    user_shared_dir = os.path.join(
        Path(settings.WORKSPACE_ROOT).expanduser().absolute(),
        user_id,
        "shared"
    )
    os.makedirs(user_shared_dir, exist_ok=True)
    
    # Skills directory (shared/skills)
    skills_dir = os.path.join(
        Path(settings.SHARED_DIR).expanduser().absolute(),
        "skills"
    )
    os.makedirs(skills_dir, exist_ok=True)
    
    return self.client.containers.create(
        image=self.image,
        command="sleep infinity",
        working_dir=settings.CONTAINER_WORKSPACE_DIR,
        volumes={
            self.workspace_dir: {"bind": settings.CONTAINER_WORKSPACE_DIR, "mode": "rw"},
            user_shared_dir: {"bind": settings.USER_SHARED, "mode": "rw"},
            skills_dir: {"bind": settings.CONTAINER_SKILLS_DIR, "mode": "ro"}
        }
    )
```

#### 5.3.4 修改 `.env`

```env
# 添加配置项
CONTAINER_SKILLS_DIR=/skills
```

### 5.4 配置变更汇总

| 配置项 | 位置 | 默认值 | 说明 |
|--------|------|--------|------|
| `CONTAINER_SKILLS_DIR` | `.env` | `/skills` | 容器内skills挂载路径 |

---

## 六、测试用例

### 6.1 单元测试

**文件**: `tests/test_skills_mount.py`

```python
# -*- coding: utf-8 -*-
"""Test skills directory mounting."""
import pytest
from src.docker_sandbox import get_thread_backend, destroy_thread_backend


def test_skills_directory_exists():
    """测试容器内/skills目录存在"""
    thread_id = "test-user-skills-exist"
    
    try:
        backend = get_thread_backend(thread_id)
        result = backend.execute("test -d /skills && echo OK")
        assert result.exit_code == 0, f"Skills directory should exist: {result.output}"
        assert "OK" in result.output
        print("[PASS] test_skills_directory_exists")
    finally:
        destroy_thread_backend(thread_id)


def test_example_skill_accessible():
    """测试示例skill可访问"""
    thread_id = "test-user-skill-access"
    
    try:
        backend = get_thread_backend(thread_id)
        result = backend.execute("cat /skills/example-skill/SKILL.md")
        assert result.exit_code == 0, f"Example skill should be accessible: {result.output}"
        assert "example-skill" in result.output, "Skill content should contain name"
        print("[PASS] test_example_skill_accessible")
    finally:
        destroy_thread_backend(thread_id)


def test_skills_readonly():
    """测试skills目录只读"""
    thread_id = "test-user-skills-readonly"
    
    try:
        backend = get_thread_backend(thread_id)
        result = backend.execute("touch /skills/test_write.txt 2>&1")
        assert result.exit_code != 0, "Should not be able to write to skills dir"
        print("[PASS] test_skills_readonly")
    finally:
        destroy_thread_backend(thread_id)


def test_list_skills():
    """测试列出skills"""
    thread_id = "test-user-list-skills"
    
    try:
        backend = get_thread_backend(thread_id)
        result = backend.execute("ls /skills/")
        assert result.exit_code == 0, f"Should be able to list skills: {result.output}"
        assert "example-skill" in result.output, "Should see example-skill"
        print("[PASS] test_list_skills")
    finally:
        destroy_thread_backend(thread_id)


def run_all_tests():
    """运行所有测试"""
    print("=" * 60)
    print("Running skills mount tests...")
    print("=" * 60)
    
    try:
        test_skills_directory_exists()
        test_example_skill_accessible()
        test_skills_readonly()
        test_list_skills()
        
        print("=" * 60)
        print("[OK] All tests passed!")
        print("=" * 60)
        return True
    except AssertionError as e:
        print(f"\n[FAIL] {e}")
        return False


if __name__ == "__main__":
    import sys
    success = run_all_tests()
    sys.exit(0 if success else 1)
```

### 6.2 集成测试（通过Agent）

```bash
# 1. 创建会话
curl -X POST http://localhost:8004/api/sessions \
  -H "Authorization: Bearer $TOKEN"

# 2. 让Agent列出skills
curl -X POST http://localhost:8004/api/chat/$THREAD_ID \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"message":"列出 /skills 目录的内容"}'

# 预期输出：Agent能看到 example-skill
```

---

## 七、验收标准

### 功能验收

| 场景 | 预期结果 | 验证方法 |
|------|---------|---------|
| 目录存在 | `/skills` 目录存在 | `ls /skills` |
| 示例skill可读 | 能读取SKILL.md内容 | `cat /skills/example-skill/SKILL.md` |
| 只读限制 | 无法写入 | `touch /skills/test` 失败 |
| 路径简洁 | Agent通过 `/skills/` 访问 | Agent对话测试 |

### 回归验收

- [ ] `tests/test_v0_1_1.py` 全部通过
- [ ] `tests/test_mvp.py` 全部通过
- [ ] 迭代1的容器持久化功能正常

### 文件验收

| 文件 | 状态 |
|------|------|
| `shared/skills/example-skill/SKILL.md` | 存在且内容正确 |
| `src/config.py` | 包含 `CONTAINER_SKILLS_DIR` |
| `src/docker_sandbox.py` | 挂载 `/skills` |
| `.env` | 包含 `CONTAINER_SKILLS_DIR=/skills` |

---

## 八、风险评估

| 风险 | 可能性 | 影响 | 缓解措施 |
|------|--------|------|---------|
| skills目录不存在 | 低 | 容器创建失败 | 代码中 `os.makedirs(skills_dir, exist_ok=True)` |
| 示例skill格式错误 | 低 | Agent无法理解 | 使用标准frontmatter格式 |
| Windows路径问题 | 中 | 挂载失败 | 使用 `os.path.join` 处理路径 |

---

## 九、实施步骤

### 步骤1：创建目录和示例skill

```bash
mkdir -p shared/skills/example-skill
```

创建 `shared/skills/example-skill/SKILL.md`

### 步骤2：修改配置

1. 编辑 `src/config.py`，添加 `CONTAINER_SKILLS_DIR`
2. 编辑 `.env`，添加 `CONTAINER_SKILLS_DIR=/skills`

### 步骤3：修改docker_sandbox.py

修改 `_create_container()` 方法中的skills挂载逻辑

### 步骤4：测试验证

```bash
# 运行测试
uv run python tests/test_skills_mount.py

# 运行回归测试
uv run python tests/test_v0_1_1.py
```

### 步骤5：重启服务验证

```bash
# 重启服务
uv run python main.py

# 手动测试
curl -X POST http://localhost:8004/api/chat/$THREAD_ID \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"message":"列出 /skills 目录"}'
```

---

## 十、文件变更汇总

| 文件 | 操作 | 改动量 |
|------|------|--------|
| `shared/skills/example-skill/SKILL.md` | 新建 | ~30行 |
| `src/config.py` | 修改 | +1行 |
| `src/docker_sandbox.py` | 修改 | ~10行 |
| `.env` | 修改 | +1行 |
| `tests/test_skills_mount.py` | 新建 | ~80行 |

**总计**: 新建约110行，修改约12行

---

## 十一、后续迭代预览

### 迭代3：Skill管理API

| 功能 | 说明 |
|------|------|
| `GET /api/admin/skills` | 列出所有skills |
| `POST /api/admin/skills/{name}` | 上传skill |
| `POST /api/admin/skills/{name}/validate` | 验证skill格式 |
| `DELETE /api/admin/skills/{name}` | 删除skill |

### 迭代4（可选）：容器生命周期优化

| 功能 | 说明 |
|------|------|
| 自动超时清理 | 空闲N分钟的容器自动销毁 |
| 容器池预热 | 预创建容器提升首次响应速度 |
| 资源限制 | CPU/内存配额控制 |

---

## 十二、总结

### 改动范围

- **文件数**: 5个（2个新建，3个修改）
- **代码量**: 约120行
- **风险等级**: 低

### 关键收益

1. ✅ 独立的 `/skills` 挂载点，路径简洁
2. ✅ 示例skill可供测试和使用
3. ✅ 为迭代3（Skill管理API）奠定基础
4. ✅ 向后兼容，不影响现有功能
