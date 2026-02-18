"""Admin API endpoints for skill management."""
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends, UploadFile, File
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.database import get_db, User
from src.auth import get_current_user
from src.agent_skills.skill_manager import (
    get_skill_manager,
    STATUS_PENDING
)
from src.agent_skills.skill_validator import get_validation_orchestrator
from src.utils.get_logger import get_logger

router = APIRouter()
logger = get_logger("valid-agent-skill")


async def get_admin_user(
    token: str = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> User:
    """Get current user and verify admin status."""
    user = db.query(User).filter(User.user_id == token).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


class SkillResponse(BaseModel):
    """Skill response model."""
    skill_id: str
    name: str
    display_name: Optional[str] = None
    description: Optional[str] = None
    status: str
    validation_stage: Optional[str] = None
    format_valid: bool = False
    format_errors: list = []
    format_warnings: list = []
    completion_score: Optional[int] = None
    trigger_accuracy_score: Optional[int] = None
    offline_capability_score: Optional[int] = None
    resource_efficiency_score: Optional[int] = None
    validation_score: Optional[float] = None
    layer1_passed: bool = False
    layer2_passed: bool = False
    created_at: Optional[str] = None
    validated_at: Optional[str] = None
    approved_by: Optional[str] = None
    approved_at: Optional[str] = None
    
    class Config:
        from_attributes = True


class SkillListResponse(BaseModel):
    """Skill list response."""
    skills: list[SkillResponse]
    total: int


class ApproveRequest(BaseModel):
    """Approve request."""
    pass


class RejectRequest(BaseModel):
    """Reject request."""
    reason: str


class ValidateRequest(BaseModel):
    """Validate request."""
    pass


@router.post("/skills/upload", response_model=SkillResponse)
async def upload_skill(
    file: UploadFile = File(...),
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db)
):
    """Upload a new skill for validation.
    
    Args:
        file: ZIP file containing skill
        admin: Current admin user
        db: Database session
        
    Returns:
        Created skill
    """
    if not file.filename or not file.filename.endswith('.zip'):
        raise HTTPException(status_code=400, detail="File must be a ZIP file")
    
    manager = get_skill_manager()
    
    try:
        skill = manager.create(db, file.file, admin.user_id, file.filename)
        return SkillResponse(
            skill_id=skill.skill_id,
            name=skill.name,
            display_name=skill.display_name,
            description=skill.description,
            status=skill.status,
            validation_stage=skill.validation_stage,
            format_valid=skill.format_valid,
            format_errors=skill.format_errors or [],
            format_warnings=skill.format_warnings or [],
            created_at=str(skill.created_at) if skill.created_at else None,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/skills", response_model=SkillListResponse)
async def list_skills(
    status: Optional[str] = None,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db)
):
    """List all skills.
    
    Args:
        status: Filter by status (optional)
        admin: Current admin user
        db: Database session
        
    Returns:
        List of skills
    """
    manager = get_skill_manager()
    skills = manager.list_all(db, status=status)
    
    return SkillListResponse(
        skills=[
            SkillResponse(
                skill_id=s.skill_id,
                name=s.name,
                display_name=s.display_name,
                description=s.description,
                status=s.status,
                validation_stage=s.validation_stage,
                format_valid=s.format_valid,
                format_errors=s.format_errors or [],
                format_warnings=s.format_warnings or [],
                completion_score=s.completion_score,
                trigger_accuracy_score=s.trigger_accuracy_score,
                offline_capability_score=s.offline_capability_score,
                resource_efficiency_score=s.resource_efficiency_score,
                validation_score=s.validation_score,
                layer1_passed=s.layer1_passed,
                layer2_passed=s.layer2_passed,
                created_at=str(s.created_at) if s.created_at else None,
                validated_at=str(s.validated_at) if s.validated_at else None,
            )
            for s in skills
        ],
        total=len(skills)
    )


@router.get("/skills/{skill_id}", response_model=SkillResponse)
async def get_skill(
    skill_id: str,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db)
):
    """Get skill by ID.
    
    Args:
        skill_id: Skill ID
        admin: Current admin user
        db: Database session
        
    Returns:
        Skill details
    """
    manager = get_skill_manager()
    skill = manager.get(db, skill_id)
    
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    
    return SkillResponse(
        skill_id=skill.skill_id,
        name=skill.name,
        display_name=skill.display_name,
        description=skill.description,
        status=skill.status,
        validation_stage=skill.validation_stage,
        format_valid=skill.format_valid,
        format_errors=skill.format_errors or [],
        format_warnings=skill.format_warnings or [],
        completion_score=skill.completion_score,
        trigger_accuracy_score=skill.trigger_accuracy_score,
        offline_capability_score=skill.offline_capability_score,
        resource_efficiency_score=skill.resource_efficiency_score,
        validation_score=skill.validation_score,
        layer1_passed=skill.layer1_passed,
        layer2_passed=skill.layer2_passed,
        created_at=str(skill.created_at) if skill.created_at else None,
        validated_at=str(skill.validated_at) if skill.validated_at else None,
        approved_by=skill.approved_by,
        approved_at=str(skill.approved_at) if skill.approved_at else None,
    )


@router.post("/skills/{skill_id}/validate")
async def validate_skill(
    skill_id: str,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db)
):
    """Start skill validation.
    
    Args:
        skill_id: Skill ID
        admin: Current admin user
        db: Database session
        
    Returns:
        Validation result
    """
    logger.info(f"[API validate_skill] 收到验证请求 skill_id={skill_id} admin={admin.user_id}")
    
    manager = get_skill_manager()
    skill = manager.get(db, skill_id)
    
    if not skill:
        logger.error(f"[API validate_skill] Skill不存在: {skill_id}")
        raise HTTPException(status_code=404, detail="Skill not found")
    
    if skill.status not in [STATUS_PENDING]:
        logger.warning(f"[API validate_skill] 状态不允许验证: {skill.status}")
        raise HTTPException(status_code=400, detail=f"Cannot validate skill with status: {skill.status}")
    
    orchestrator = get_validation_orchestrator()
    
    try:
        logger.info(f"[API validate_skill] 开始执行验证流程 skill_id={skill_id}")
        result = await orchestrator.validate_skill(skill_id)
        logger.info(f"[API validate_skill] 验证完成 skill_id={skill_id} passed={result.get('passed')}")
        return {"message": "Validation completed", "result": result}
    except Exception as e:
        logger.error(f"[API validate_skill] 验证异常 skill_id={skill_id} error={e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/skills/{skill_id}/approve")
async def approve_skill(
    skill_id: str,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db)
):
    """Approve a skill.
    
    Args:
        skill_id: Skill ID
        admin: Current admin user
        db: Database session
        
    Returns:
        Approved skill
    """
    manager = get_skill_manager()
    
    try:
        skill = manager.approve(db, skill_id, admin.user_id)
        return {"message": "Skill approved", "skill_id": skill.skill_id}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/skills/{skill_id}/reject")
async def reject_skill(
    skill_id: str,
    request: RejectRequest,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db)
):
    """Reject a skill.
    
    Args:
        skill_id: Skill ID
        request: Reject request with reason
        admin: Current admin user
        db: Database session
        
    Returns:
        Rejected skill
    """
    manager = get_skill_manager()
    
    try:
        skill = manager.reject(db, skill_id, admin.user_id, request.reason)
        return {"message": "Skill rejected", "skill_id": skill.skill_id}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/skills/{skill_id}")
async def delete_skill(
    skill_id: str,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db)
):
    """Delete a skill.
    
    Args:
        skill_id: Skill ID
        admin: Current admin user
        db: Database session
        
    Returns:
        Success message
    """
    manager = get_skill_manager()
    
    if not manager.delete(db, skill_id):
        raise HTTPException(status_code=404, detail="Skill not found")
    
    return {"message": "Skill deleted"}


@router.get("/skills/{skill_id}/report")
async def get_skill_report(
    skill_id: str,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db)
):
    """Get skill validation report.
    
    Args:
        skill_id: Skill ID
        admin: Current admin user
        db: Database session
        
    Returns:
        Markdown validation report
    """
    from src.config import flash_llm
    
    manager = get_skill_manager()
    skill = manager.get(db, skill_id)
    
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    
    if not skill.layer1_report:
        return {
            "content": f"""# Skill 验证报告

## 基本信息

| 字段 | 值 |
|------|-----|
| **Skill ID** | {skill.skill_id} |
| **名称** | {skill.name} |
| **验证阶段** | {skill.validation_stage or 'pending'} |

## 说明

验证尚未完成，请稍后刷新查看完整报告。
""",
            "content_type": "markdown"
        }
    
    prompt = f"""
请根据以下验证结果生成 Markdown 格式的验证报告。

## 基本信息
- Skill ID: {skill.skill_id}
- 名称: {skill.name}
- 验证阶段: {skill.validation_stage}

## 评分
- 任务完成度: {skill.completion_score}/100
- 触发准确性: {skill.trigger_accuracy_score}/100
- 离线能力: {skill.offline_capability_score}/100
- 资源效率: {skill.resource_efficiency_score}/100
- 总分: {skill.validation_score}

## 验证报告 JSON
{skill.layer1_report}

请按照以下格式生成报告：
1. 基本信息（表格）
2. 第一层验证（联网盲测、离线盲测）
3. 评分表格
4. 评估（优点、缺点、建议、总结）
5. 依赖信息
6. 结论

输出纯 Markdown，不要用代码块包裹。
"""
    
    response = await flash_llm.ainvoke(prompt)
    content = response.content if hasattr(response, 'content') else str(response)
    
    return {
        "content": content,
        "content_type": "markdown"
    }
