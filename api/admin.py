"""Admin API endpoints for skill management."""

import asyncio
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends, UploadFile, File
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from src.database import get_db, User, Skill
from src.auth import get_current_user
from api.models import LlmConfigResponse
from src.agent_skills.skill_manager import get_skill_manager, STATUS_PENDING
from src.agent_skills.skill_validator import get_validation_orchestrator
from src.utils.get_logger import get_logger

router = APIRouter()
logger = get_logger("valid-agent-skill")


async def get_admin_user(
    token: str = Depends(get_current_user), db: Session = Depends(get_db)
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

    model_config = ConfigDict(from_attributes=True)


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
    db: Session = Depends(get_db),
):
    """Upload a new skill for validation.

    Args:
        file: ZIP file containing skill
        admin: Current admin user
        db: Database session

    Returns:
        Created skill
    """
    if not file.filename or not file.filename.endswith(".zip"):
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
    db: Session = Depends(get_db),
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
        size=size,
    )


class SimpleSkillResponse(BaseModel):
    """Simple skill response model."""

    skill_id: str
    name: str
    display_name: Optional[str] = None
    description: Optional[str] = None
    status: str
    format_valid: bool = False
    format_errors: list = []
    format_warnings: list = []
    created_at: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class SimpleSkillListResponse(BaseModel):
    """Simple skill list response."""

    skills: list[SimpleSkillResponse]
    total: int


@router.post("/skills/simple/upload", response_model=SimpleSkillResponse)
async def upload_skill_simple(
    file: UploadFile = File(...),
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    """Upload a skill directly without validation.

    Args:
        file: ZIP file containing skill
        admin: Current admin user
        db: Database session

    Returns:
        Created skill
    """
    if not file.filename or not file.filename.endswith(".zip"):
        raise HTTPException(status_code=400, detail="File must be a ZIP file")

    from src.simple_skill_manager import get_simple_skill_manager

    manager = get_simple_skill_manager()

    try:
        skill = manager.upload(db, file.file, file.filename, admin.user_id)
        return SimpleSkillResponse(
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
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/skills/simple", response_model=SimpleSkillListResponse)
async def list_skills_simple(
    status: Optional[str] = None,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    """List all skills (simple mode).

    Args:
        status: Filter by status (optional)
        admin: Current admin user
        db: Database session

    Returns:
        List of skills
    """
    from src.simple_skill_manager import get_simple_skill_manager

    manager = get_simple_skill_manager()
    skills = manager.list_all(db, status=status)

    return SimpleSkillListResponse(
        skills=[
            SimpleSkillResponse(
                skill_id=s.skill_id,
                name=s.name,
                display_name=s.display_name,
                description=s.description,
                status=s.status,
                format_valid=s.format_valid,
                format_errors=s.format_errors or [],
                format_warnings=s.format_warnings or [],
                created_at=str(s.created_at) if s.created_at else None,
            )
            for s in skills
        ],
        total=len(skills),
    )


@router.delete("/skills/simple/{name}")
async def delete_skill_simple(
    name: str, admin: User = Depends(get_admin_user), db: Session = Depends(get_db)
):
    """Delete a skill by name (simple mode).

    Args:
        name: Skill name
        admin: Current admin user
        db: Database session

    Returns:
        Success message
    """
    from src.simple_skill_manager import get_simple_skill_manager

    manager = get_simple_skill_manager()

    if not manager.delete_by_name(db, name):
        raise HTTPException(status_code=404, detail=f"Skill '{name}' not found")

    return {"message": f"Skill '{name}' deleted"}


@router.post("/skills/simple/{skill_id}/disable")
async def disable_skill_simple(
    skill_id: str, admin: User = Depends(get_admin_user), db: Session = Depends(get_db)
):
    """Disable a skill (simple mode).

    Args:
        skill_id: Skill ID
        admin: Current admin user
        db: Database session

    Returns:
        Updated skill
    """
    from src.simple_skill_manager import get_simple_skill_manager

    manager = get_simple_skill_manager()
    skill = manager.disable(db, skill_id)

    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")

    return {"skill_id": skill.skill_id, "status": skill.status}


@router.post("/skills/simple/{skill_id}/enable")
async def enable_skill_simple(
    skill_id: str, admin: User = Depends(get_admin_user), db: Session = Depends(get_db)
):
    """Enable a skill (simple mode).

    Args:
        skill_id: Skill ID
        admin: Current admin user
        db: Database session

    Returns:
        Updated skill
    """
    from src.simple_skill_manager import get_simple_skill_manager

    manager = get_simple_skill_manager()
    skill = manager.enable(db, skill_id)

    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")

    return {"skill_id": skill.skill_id, "status": skill.status}


@router.post("/skills/simple/sync")
async def sync_skills_simple(
    admin: User = Depends(get_admin_user), db: Session = Depends(get_db)
):
    """Sync skills directory to database.

    Args:
        admin: Current admin user
        db: Database session

    Returns:
        Sync result
    """
    from src.simple_skill_manager import get_simple_skill_manager

    manager = get_simple_skill_manager()
    synced = manager.sync_to_db(db)

    return {"synced": synced, "message": f"Synced {synced} skills to database"}


@router.get("/skills/{skill_id}", response_model=SkillResponse)
async def get_skill(
    skill_id: str, admin: User = Depends(get_admin_user), db: Session = Depends(get_db)
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
    skill_id: str, admin: User = Depends(get_admin_user), db: Session = Depends(get_db)
):
    """Start skill validation.

    Args:
        skill_id: Skill ID
        admin: Current admin user
        db: Database session

    Returns:
        Validation result
    """
    logger.info(
        f"[API validate_skill] 收到验证请求 skill_id={skill_id} admin={admin.user_id}"
    )

    manager = get_skill_manager()
    skill = manager.get(db, skill_id)

    if not skill:
        logger.error(f"[API validate_skill] Skill不存在: {skill_id}")
        raise HTTPException(status_code=404, detail="Skill not found")

    if skill.status not in [STATUS_PENDING]:
        logger.warning(f"[API validate_skill] 状态不允许验证: {skill.status}")
        raise HTTPException(
            status_code=400, detail=f"Cannot validate skill with status: {skill.status}"
        )

    orchestrator = get_validation_orchestrator()

    try:
        logger.info(f"[API validate_skill] 开始执行验证流程 skill_id={skill_id}")
        result = await orchestrator.validate_skill(skill_id)
        logger.info(
            f"[API validate_skill] 验证完成 skill_id={skill_id} passed={result.get('passed')}"
        )
        return {"message": "Validation completed", "result": result}
    except Exception as e:
        logger.error(f"[API validate_skill] 验证异常 skill_id={skill_id} error={e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/skills/{skill_id}/revalidate")
async def revalidate_skill(
    skill_id: str, admin: User = Depends(get_admin_user), db: Session = Depends(get_db)
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
            detail=f"Cannot revalidate skill with status: {skill.status}",
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
            "message": "Validation started",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/skills/{skill_id}/approve")
async def approve_skill(
    skill_id: str, admin: User = Depends(get_admin_user), db: Session = Depends(get_db)
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
            "message": "Skill approved and available to agents",
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/skills/{skill_id}/reject")
async def reject_skill(
    skill_id: str,
    request: RejectRequest,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
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
            "reject_reason": skill.reject_reason,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/skills/{skill_id}")
async def delete_skill(
    skill_id: str, admin: User = Depends(get_admin_user), db: Session = Depends(get_db)
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
    skill_id: str, admin: User = Depends(get_admin_user), db: Session = Depends(get_db)
):
    """Get skill validation report.

    Args:
        skill_id: Skill ID
        admin: Current admin user
        db: Database session

    Returns:
        Markdown validation report
    """
    from src.llm_manager import get_llm_manager

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
| **验证阶段** | {skill.validation_stage or "pending"} |

## 说明

验证尚未完成，请稍后刷新查看完整报告。
""",
            "content_type": "markdown",
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

    flash_llm = get_llm_manager().get_flash_llm(db)
    response = await flash_llm.ainvoke(prompt)
    content = response.content if hasattr(response, "content") else str(response)

    return {"content": content, "content_type": "markdown"}


class RollbackRequest(BaseModel):
    """Rollback request."""

    target_version: str


@router.get("/images")
async def list_image_versions(
    admin: User = Depends(get_admin_user), db: Session = Depends(get_db)
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
                "is_current": v.is_current,
            }
            for v in versions
        ],
        "current_version": next((v.version for v in versions if v.is_current), None),
        "total": len(versions),
    }


@router.post("/images/rollback")
async def rollback_image(
    request: RollbackRequest,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    """回滚镜像版本

    Args:
        request: Rollback request with target version
        admin: Current admin user
        db: Database session

    Returns:
        Rollback result
    """
    from src.database import ImageVersion
    from src.agent_skills.skill_image_manager import get_image_backend

    image_backend = get_image_backend()

    target = (
        db.query(ImageVersion)
        .filter(ImageVersion.version == request.target_version)
        .first()
    )
    if not target:
        raise HTTPException(
            status_code=404, detail=f"Version {request.target_version} not found"
        )

    current = db.query(ImageVersion).filter(ImageVersion.is_current == True).first()
    affected_skills = []

    if current:
        skills = db.query(Skill).filter(Skill.approved_at >= target.created_at).all()
        affected_skills = [s.name for s in skills]

        for skill in skills:
            skill.status = "rollback_pending"
        db.commit()

    try:
        image_backend.load(request.target_version)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load image: {e}")

    db.query(ImageVersion).update({"is_current": False})
    target.is_current = True
    db.commit()

    return {
        "current_version": current.version if current else None,
        "target_version": request.target_version,
        "affected_skills": affected_skills,
        "message": f"Rollback to {request.target_version} completed",
    }


@router.get("/llm/configs", response_model=dict)
async def list_llm_configs(
    role: Optional[str] = None,
    provider: Optional[str] = None,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    """List all LLM configurations.

    Args:
        role: Filter by role (big/flash)
        provider: Filter by provider (ollama/vllm/openai/zhipuai)
        admin: Current admin user
        db: Database session

    Returns:
        List of LLM configurations
    """
    from src.llm_manager import get_llm_manager
    from api.models import LlmConfigResponse

    manager = get_llm_manager()
    configs = manager.list_configs(db, role=role, provider=provider)

    return {
        "configs": [
            LlmConfigResponse(
                id=c.id,
                name=c.name,
                display_name=c.display_name,
                description=c.description,
                provider=c.provider,
                base_url=c.base_url,
                model_name=c.model_name,
                temperature=c.temperature,
                max_tokens=c.max_tokens,
                extra_params=c.extra_params or {},
                role=c.role,
                is_active=c.is_active,
                created_at=str(c.created_at) if c.created_at else None,
                updated_at=str(c.updated_at) if c.updated_at else None,
            )
            for c in configs
        ],
        "total": len(configs),
    }


@router.post("/llm/configs", response_model=LlmConfigResponse)
async def create_llm_config(
    request: dict,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    """Create a new LLM configuration.

    Args:
        request: LLM config creation request
        admin: Current admin user
        db: Database session

    Returns:
        Created LLM configuration
    """
    from src.llm_manager import get_llm_manager
    from api.models import LlmConfigResponse

    manager = get_llm_manager()

    try:
        config = manager.create_config(
            db=db,
            name=request["name"],
            provider=request["provider"],
            base_url=request["base_url"],
            api_key=request["api_key"],
            model_name=request["model_name"],
            role=request["role"],
            display_name=request.get("display_name"),
            description=request.get("description"),
            temperature=request.get("temperature", 0.7),
            max_tokens=request.get("max_tokens", 4096),
            extra_params=request.get("extra_params"),
            created_by=admin.user_id,
            activate=request.get("activate", False),
        )

        return LlmConfigResponse(
            id=config.id,
            name=config.name,
            display_name=config.display_name,
            description=config.description,
            provider=config.provider,
            base_url=config.base_url,
            model_name=config.model_name,
            temperature=config.temperature,
            max_tokens=config.max_tokens,
            extra_params=config.extra_params or {},
            role=config.role,
            is_active=config.is_active,
            created_at=str(config.created_at) if config.created_at else None,
            updated_at=str(config.updated_at) if config.updated_at else None,
        )
    except Exception as e:
        if "unique constraint" in str(e).lower() or "duplicate" in str(e).lower():
            raise HTTPException(
                status_code=400,
                detail=f"Config name '{request['name']}' already exists",
            )
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/llm/configs/{config_id}", response_model=LlmConfigResponse)
async def get_llm_config(
    config_id: str,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    """Get LLM configuration by ID.

    Args:
        config_id: LLM config ID
        admin: Current admin user
        db: Database session

    Returns:
        LLM configuration details
    """
    from src.database import LlmConfig
    from api.models import LlmConfigResponse

    config = db.query(LlmConfig).filter(LlmConfig.id == config_id).first()

    if not config:
        raise HTTPException(status_code=404, detail="LLM config not found")

    return LlmConfigResponse(
        id=config.id,
        name=config.name,
        display_name=config.display_name,
        description=config.description,
        provider=config.provider,
        base_url=config.base_url,
        model_name=config.model_name,
        temperature=config.temperature,
        max_tokens=config.max_tokens,
        extra_params=config.extra_params or {},
        role=config.role,
        is_active=config.is_active,
        created_at=str(config.created_at) if config.created_at else None,
        updated_at=str(config.updated_at) if config.updated_at else None,
    )


@router.put("/llm/configs/{config_id}", response_model=LlmConfigResponse)
async def update_llm_config(
    config_id: str,
    request: dict,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    """Update LLM configuration.

    Args:
        config_id: LLM config ID
        request: Update request
        admin: Current admin user
        db: Database session

    Returns:
        Updated LLM configuration
    """
    from src.llm_manager import get_llm_manager
    from api.models import LlmConfigResponse

    manager = get_llm_manager()

    config = manager.update_config(
        db=db,
        config_id=config_id,
        display_name=request.get("display_name"),
        description=request.get("description"),
        base_url=request.get("base_url"),
        api_key=request.get("api_key"),
        model_name=request.get("model_name"),
        temperature=request.get("temperature"),
        max_tokens=request.get("max_tokens"),
        extra_params=request.get("extra_params"),
    )

    if not config:
        raise HTTPException(status_code=404, detail="LLM config not found")

    return LlmConfigResponse(
        id=config.id,
        name=config.name,
        display_name=config.display_name,
        description=config.description,
        provider=config.provider,
        base_url=config.base_url,
        model_name=config.model_name,
        temperature=config.temperature,
        max_tokens=config.max_tokens,
        extra_params=config.extra_params or {},
        role=config.role,
        is_active=config.is_active,
        created_at=str(config.created_at) if config.created_at else None,
        updated_at=str(config.updated_at) if config.updated_at else None,
    )


@router.delete("/llm/configs/{config_id}")
async def delete_llm_config(
    config_id: str,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    """Delete LLM configuration.

    Args:
        config_id: LLM config ID
        admin: Current admin user
        db: Database session

    Returns:
        Success message
    """
    from src.llm_manager import get_llm_manager

    manager = get_llm_manager()

    if not manager.delete_config(db, config_id):
        raise HTTPException(status_code=404, detail="LLM config not found")

    return {"message": "LLM config deleted"}


@router.post("/llm/configs/{config_id}/activate", response_model=LlmConfigResponse)
async def activate_llm_config(
    config_id: str,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    """Activate LLM configuration.

    Args:
        config_id: LLM config ID
        admin: Current admin user
        db: Database session

    Returns:
        Activated LLM configuration
    """
    from src.llm_manager import get_llm_manager
    from src.memory_manager import get_memory_manager
    from src.database import SessionLocal
    from api.models import LlmConfigResponse

    manager = get_llm_manager()

    config = manager.activate_config(config_id, db)

    if not config:
        raise HTTPException(status_code=404, detail="LLM config not found")

    # Reinitialize MemoryManager if big or embedding role config changes
    if config.role in ["big", "embedding"]:
        try:
            memory_manager = get_memory_manager()
            with SessionLocal() as db_session:
                memory_manager.reinit(db_session)
            logger.info(
                f"[Admin] MemoryManager reinitialized due to {config.role} config activation"
            )
        except Exception as e:
            logger.warning(f"[Admin] Failed to reinitialize MemoryManager: {e}")

    return LlmConfigResponse(
        id=config.id,
        name=config.name,
        display_name=config.display_name,
        description=config.description,
        provider=config.provider,
        base_url=config.base_url,
        model_name=config.model_name,
        temperature=config.temperature,
        max_tokens=config.max_tokens,
        extra_params=config.extra_params or {},
        role=config.role,
        is_active=config.is_active,
        created_at=str(config.created_at) if config.created_at else None,
        updated_at=str(config.updated_at) if config.updated_at else None,
    )


@router.post("/llm/configs/{config_id}/test", response_model=dict)
async def test_llm_config(
    config_id: str,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    """Test LLM/Embedding connection using saved config.

    Args:
        config_id: LLM config ID
        admin: Current admin user
        db: Database session

    Returns:
        Test result
    """
    from src.database import LlmConfig
    from src.llm_manager import get_llm_manager

    config = db.query(LlmConfig).filter(LlmConfig.id == config_id).first()
    if not config:
        raise HTTPException(status_code=404, detail="LLM config not found")

    manager = get_llm_manager()

    # Choose test method based on role
    if config.role == "embedding":
        result = await manager.test_embedding_connection(
            base_url=config.base_url,
            api_key=config.api_key,
            model_name=config.model_name,
        )
    else:
        result = await manager.test_connection(
            base_url=config.base_url,
            api_key=config.api_key,
            model_name=config.model_name,
        )

    return result


@router.post("/llm/test", response_model=dict)
async def test_llm_connection(
    request: dict,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    """Test LLM connection.

    Args:
        request: Test request with base_url, api_key, model_name
        admin: Current admin user
        db: Database session

    Returns:
        Test result
    """
    from src.llm_manager import get_llm_manager

    manager = get_llm_manager()

    result = await manager.test_connection(
        base_url=request["base_url"],
        api_key=request["api_key"],
        model_name=request["model_name"],
    )

    return result


@router.post("/llm/embedding/test", response_model=dict)
async def test_embedding_connection(
    request: dict,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    """Test embedding model connection.

    Args:
        request: Test request with base_url, api_key, model_name
        admin: Current admin user
        db: Database session

    Returns:
        Test result with vector dimension info
    """
    from src.llm_manager import get_llm_manager

    manager = get_llm_manager()

    result = await manager.test_embedding_connection(
        base_url=request["base_url"],
        api_key=request["api_key"],
        model_name=request["model_name"],
    )

    return result
