"""Admin API endpoints for skill management."""
import asyncio
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends, UploadFile, File
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.database import get_db, User, Skill
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
    rejected_by: Optional[str] = None
    rejected_at: Optional[str] = None
    reject_reason: Optional[str] = None
    runtime_image_version: Optional[str] = None
    installed_dependencies: Optional[dict] = None
    blind_test_passed: Optional[bool] = None
    skill_triggered: Optional[bool] = None
    trigger_accuracy: Optional[float] = None
    network_test_passed: Optional[bool] = None
    offline_capable: Optional[bool] = None
    blocked_network_calls: Optional[int] = None
    execution_metrics: Optional[dict] = None
    task_results: Optional[list] = None
    regression_results: Optional[dict] = None
    
    class Config:
        from_attributes = True


class SkillListResponse(BaseModel):
    """Skill list response."""
    skills: list[SkillResponse]
    total: int
    page: int = 1
    size: int = 20


def _extract_skill_response(skill: Skill) -> SkillResponse:
    """从 Skill 模型提取响应数据，包括从 layer1_report/layer2_report 提取字段"""
    
    layer1_report = skill.layer1_report or {}
    layer2_report = skill.layer2_report or {}
    
    online_test = layer1_report.get("online_blind_test", {})
    offline_test = layer1_report.get("offline_blind_test", {})
    metrics = layer1_report.get("metrics", {})
    
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
        rejected_by=skill.rejected_by,
        rejected_at=str(skill.rejected_at) if skill.rejected_at else None,
        reject_reason=skill.reject_reason,
        runtime_image_version=skill.runtime_image_version,
        installed_dependencies=skill.installed_dependencies,
        blind_test_passed=online_test.get("passed"),
        skill_triggered=online_test.get("skill_triggered"),
        trigger_accuracy=online_test.get("trigger_accuracy"),
        network_test_passed=offline_test.get("passed"),
        offline_capable=offline_test.get("offline_capable"),
        blocked_network_calls=offline_test.get("blocked_network_calls"),
        execution_metrics=metrics,
        task_results=online_test.get("task_results"),
        regression_results=layer2_report.get("regression_results"),
    )


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
    validation_stage: Optional[str] = None,
    page: int = 1,
    size: int = 20,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db)
):
    """List all skills with pagination.
    
    Args:
        status: Filter by status (optional)
        validation_stage: Filter by validation stage (optional)
        page: Page number (default 1)
        size: Page size (default 20)
        admin: Current admin user
        db: Database session
        
    Returns:
        List of skills with pagination
    """
    manager = get_skill_manager()
    
    offset = (page - 1) * size
    
    total_query = db.query(Skill)
    if status:
        total_query = total_query.filter(Skill.status == status)
    if validation_stage:
        total_query = total_query.filter(Skill.validation_stage == validation_stage)
    total = total_query.count()
    
    skills = manager.list_all(db, status=status, offset=offset, limit=size)
    
    return SkillListResponse(
        skills=[_extract_skill_response(s) for s in skills],
        total=total,
        page=page,
        size=size
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
    
    return _extract_skill_response(skill)


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


@router.post("/skills/{skill_id}/revalidate")
async def revalidate_skill(
    skill_id: str,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db)
):
    """重新验证 Skill
    
    Args:
        skill_id: Skill ID
        admin: Current admin user
        db: Database session
        
    Returns:
        验证启动确认
    """
    logger.info(f"[API revalidate_skill] 收到重新验证请求 skill_id={skill_id}")
    
    manager = get_skill_manager()
    skill = manager.get(db, skill_id)
    
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    
    if skill.status not in [STATUS_PENDING, "rejected"]:
        raise HTTPException(
            status_code=400, 
            detail=f"Cannot revalidate skill with status: {skill.status}"
        )
    
    skill.status = STATUS_PENDING
    skill.validation_stage = None
    skill.layer1_passed = None
    skill.layer2_passed = None
    db.commit()
    
    orchestrator = get_validation_orchestrator()
    
    try:
        asyncio.create_task(orchestrator.validate_skill(skill_id))
        return {
            "skill_id": skill_id,
            "status": "validating",
            "validation_stage": "layer1",
            "message": "Validation started"
        }
    except Exception as e:
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
        return {
            "skill_id": skill.skill_id,
            "name": skill.name,
            "status": skill.status,
            "runtime_image_version": skill.runtime_image_version,
            "approved_at": str(skill.approved_at) if skill.approved_at else None,
            "message": "Skill approved and available to agents"
        }
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
        return {
            "skill_id": skill.skill_id,
            "status": skill.status,
            "rejected_at": str(skill.rejected_at) if skill.rejected_at else None,
            "reject_reason": skill.reject_reason
        }
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


@router.post("/skills/full-test")
async def run_full_test(
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db)
):
    """全量测试所有已入库 Skills
    
    对每个已批准的 Skill 执行验证测试：
    - 复用之前验证时的 3 个任务
    - 新生成 2 个额外任务
    - 共 5 个任务进行验证
    
    Args:
        admin: Current admin user
        db: Database session
        
    Returns:
        全量测试启动确认
    """
    logger.info(f"[API run_full_test] 收到全量测试请求 admin={admin.user_id}")
    
    orchestrator = get_validation_orchestrator()
    
    try:
        asyncio.create_task(orchestrator.run_full_test())
        return {
            "status": "started",
            "message": "Full test started. Check skill statuses for progress."
        }
    except Exception as e:
        logger.error(f"[API run_full_test] 启动失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


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


class RollbackRequest(BaseModel):
    """Rollback request."""
    target_version: str


@router.get("/images")
async def list_image_versions(
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db)
):
    """获取镜像版本列表
    
    Args:
        admin: Current admin user
        db: Database session
        
    Returns:
        List of image versions
    """
    from src.database import ImageVersion
    
    versions = db.query(ImageVersion).order_by(ImageVersion.created_at.desc()).all()
    
    return {
        "versions": [
            {
                "version": v.version,
                "skill_id": v.skill_id,
                "skill_name": None,
                "created_at": str(v.created_at),
                "is_current": v.is_current
            }
            for v in versions
        ],
        "current_version": next((v.version for v in versions if v.is_current), None),
        "total": len(versions)
    }


@router.post("/images/rollback")
async def rollback_image(
    request: RollbackRequest,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db)
):
    """回滚镜像版本
    
    Note: 镜像管理功能已迁移到 Daytona Snapshot，此接口暂时禁用。
    
    Args:
        request: Rollback request with target version
        admin: Current admin user
        db: Database session
        
    Returns:
        Rollback result
    """
    raise HTTPException(
        status_code=501, 
        detail="Image rollback is deprecated. Use Daytona Snapshots instead."
    )
