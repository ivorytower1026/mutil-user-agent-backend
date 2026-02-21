# Skill 简化上传方案 v0.2.2

## 目标

跳过复杂验证流程，上传后直接入库并同步到沙箱。

## 流程

```
ZIP上传 -> 解压 -> 基本格式检查 -> 存入approved目录 -> 数据库status=approved -> 重建Snapshot
```

## 基本格式检查

只检查：
1. ZIP中存在 `SKILL.md` 文件
2. `SKILL.md` 有有效的 YAML frontmatter（包含 `name` 和 `description`）

## 修改文件

### 1. `src/agent_skills/skill_manager.py`

新增方法 `create_simplified()`:

```python
def create_simplified(self, db: Session, file: BinaryIO, admin_id: str, filename: str) -> Skill:
    """简化上传：只验证基本格式，直接入库"""
    skill_id = str(uuid.uuid4())
    temp_dir = self.approved_dir / f"temp_{skill_id}"
    
    try:
        # 1. 解压ZIP
        temp_dir.mkdir(parents=True, exist_ok=True)
        zip_path = temp_dir / filename
        with open(zip_path, 'wb') as f:
            f.write(file.read())
        
        extract_dir = temp_dir / "extracted"
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(extract_dir)
        
        # 处理嵌套目录
        extracted_items = list(extract_dir.iterdir())
        if len(extracted_items) == 1 and extracted_items[0].is_dir():
            skill_dir = extracted_items[0]
        else:
            skill_dir = extract_dir
        
        # 2. 基本格式检查
        skill_md_path = skill_dir / "SKILL.md"
        if not skill_md_path.exists():
            raise ValueError("Missing SKILL.md")
        
        with open(skill_md_path, encoding='utf-8') as f:
            content = f.read()
        
        from deepagents.middleware.skills import _parse_skill_metadata
        metadata = _parse_skill_metadata(content, str(skill_md_path), skill_dir.name)
        
        if not metadata:
            raise ValueError("Invalid SKILL.md frontmatter (need name and description)")
        
        name = metadata.get('name', Path(filename).stem)
        
        # 3. 移动到approved目录
        final_dir = self.approved_dir / name
        if final_dir.exists():
            shutil.rmtree(final_dir)
        shutil.move(str(skill_dir), str(final_dir))
        shutil.rmtree(temp_dir)
        
        # 4. 创建数据库记录（直接approved）
        skill = Skill(
            skill_id=skill_id,
            name=name,
            display_name=metadata.get('display_name', name),
            description=metadata.get('description', ''),
            status=STATUS_APPROVED,  # 直接approved
            skill_path=str(final_dir),
            format_valid=True,
            format_errors=[],
            format_warnings=[],
            created_by=admin_id,
            approved_by=admin_id,
            approved_at=datetime.utcnow(),
        )
        
        db.add(skill)
        db.commit()
        db.refresh(skill)
        
        return skill
        
    except Exception as e:
        if temp_dir.exists():
            shutil.rmtree(temp_dir)
        raise e
```

### 2. `api/admin.py`

修改 `upload_skill()`:

```python
@router.post("/skills/upload", response_model=SkillResponse)
async def upload_skill(
    file: UploadFile = File(...),
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db)
):
    if not file.filename or not file.filename.endswith('.zip'):
        raise HTTPException(status_code=400, detail="File must be a ZIP file")
    
    manager = get_skill_manager()
    
    try:
        # 使用简化上传
        skill = manager.create_simplified(db, file.file, admin.user_id, file.filename)
        
        # 自动重建Snapshot
        from src.snapshot_manager import get_snapshot_manager
        snapshot_id = get_snapshot_manager().rebuild_skills_snapshot()
        
        return SkillResponse(
            skill_id=skill.skill_id,
            name=skill.name,
            display_name=skill.display_name,
            description=skill.description,
            status=skill.status,
            format_valid=skill.format_valid,
            format_errors=skill.format_errors or [],
            format_warnings=skill.format_warnings or [],
            created_at=str(skill.created_at) if skill.created_at else None,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```

## 不涉及的文件

- `skill_validator.py` - 不再调用
- `approve()` 方法 - 不再需要手动approve
- `/skills/{id}/validate` 接口 - 保留但不再自动触发

## 回滚方案

如需恢复完整验证，将 `upload_skill()` 改回调用 `manager.create()` 即可。
