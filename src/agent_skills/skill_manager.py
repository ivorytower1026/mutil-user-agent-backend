"""Skill manager for CRUD operations, state transitions, and file operations."""
import os
import uuid
import zipfile
import shutil
from pathlib import Path
from datetime import datetime
from typing import BinaryIO

from sqlalchemy.orm import Session
from sqlalchemy import or_

from src.database import Skill, SessionLocal
from src.config import settings
from src.utils.get_logger import get_logger

logger = get_logger("valid-agent-skill")


STATUS_PENDING = "pending"
STATUS_VALIDATING = "validating"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"

VALIDATION_STAGE_LAYER1 = "layer1"
VALIDATION_STAGE_LAYER2 = "layer2"
VALIDATION_STAGE_COMPLETED = "completed"
VALIDATION_STAGE_FAILED = "failed"


def get_skill_pending_dir() -> Path:
    """Get pending skills directory."""
    if settings.SKILL_PENDING_DIR:
        return Path(settings.SKILL_PENDING_DIR).expanduser().absolute()
    return Path(settings.WORKSPACE_ROOT).expanduser().absolute() / "skills_pending"


def get_skill_approved_dir() -> Path:
    """Get approved skills directory."""
    if settings.SKILL_APPROVED_DIR:
        return Path(settings.SKILL_APPROVED_DIR).expanduser().absolute()
    return Path(settings.SHARED_DIR).expanduser().absolute() / "skills"


def validate_skill_format(skill_path: str) -> tuple[bool, list[str], list[str]]:
    """Validate skill format using DeepAgents' parser."""
    from deepagents.middleware.skills import _parse_skill_metadata
    
    skill_md_path = os.path.join(skill_path, "SKILL.md")
    errors = []
    warnings = []
    
    if not os.path.exists(skill_md_path):
        return False, ["Missing SKILL.md"], []
    
    with open(skill_md_path, encoding='utf-8') as f:
        content = f.read()
    
    if not content.strip():
        return False, ["SKILL.md is empty"], []
    
    directory_name = os.path.basename(skill_path)
    metadata = _parse_skill_metadata(content, skill_md_path, directory_name)
    
    if metadata is None:
        return False, ["Invalid frontmatter format or missing name/description"], []
    
    if not os.path.exists(os.path.join(skill_path, "scripts")):
        warnings.append("No scripts/ directory (optional)")
    
    return True, errors, warnings


class SkillManager:
    """Manager for skill CRUD operations and state transitions."""
    
    def __init__(self):
        self.pending_dir = get_skill_pending_dir()
        self.approved_dir = get_skill_approved_dir()
        self.pending_dir.mkdir(parents=True, exist_ok=True)
        self.approved_dir.mkdir(parents=True, exist_ok=True)
    
    def create(self, db: Session, file: BinaryIO, admin_id: str, filename: str) -> Skill:
        """Upload and create a new skill from zip file."""
        skill_id = str(uuid.uuid4())
        temp_dir = self.pending_dir / f"temp_{skill_id}"
        
        try:
            temp_dir.mkdir(parents=True, exist_ok=True)
            
            zip_path = temp_dir / filename
            with open(zip_path, 'wb') as f:
                f.write(file.read())
            
            extract_dir = temp_dir / "extracted"
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(extract_dir)
            
            extracted_items = list(extract_dir.iterdir())
            if len(extracted_items) == 1 and extracted_items[0].is_dir():
                skill_dir = extracted_items[0]
            else:
                skill_dir = extract_dir
            
            passed, errors, warnings = validate_skill_format(str(skill_dir))
            
            skill_md_path = skill_dir / "SKILL.md"
            metadata = {}
            if skill_md_path.exists():
                with open(skill_md_path, encoding='utf-8') as f:
                    content = f.read()
                from deepagents.middleware.skills import _parse_skill_metadata
                metadata = _parse_skill_metadata(content, str(skill_md_path), skill_dir.name) or {}
            
            name = metadata.get('name', Path(filename).stem)
            
            final_dir = self.pending_dir / name
            if final_dir.exists():
                shutil.rmtree(final_dir)
            shutil.move(str(skill_dir), str(final_dir))
            
            shutil.rmtree(temp_dir)
            
            skill = Skill(
                skill_id=skill_id,
                name=name,
                display_name=metadata.get('display_name', name),
                description=metadata.get('description', ''),
                status=STATUS_PENDING,
                skill_path=str(final_dir),
                format_valid=passed,
                format_errors=errors,
                format_warnings=warnings,
                created_by=admin_id,
            )
            
            db.add(skill)
            db.commit()
            db.refresh(skill)
            
            return skill
            
        except Exception as e:
            if temp_dir.exists():
                shutil.rmtree(temp_dir)
            raise e
    
    def get(self, db: Session, skill_id: str) -> Skill | None:
        """Get a skill by ID."""
        return db.query(Skill).filter(Skill.skill_id == skill_id).first()
    
    def get_by_name(self, db: Session, name: str) -> Skill | None:
        """Get a skill by name."""
        return db.query(Skill).filter(Skill.name == name).first()
    
    def list_all(self, db: Session, status: str | None = None) -> list[Skill]:
        """List all skills, optionally filtered by status."""
        query = db.query(Skill)
        if status:
            query = query.filter(Skill.status == status)
        return query.order_by(Skill.created_at.desc()).all()
    
    def list_approved(self, db: Session) -> list[Skill]:
        """List all approved skills."""
        return self.list_all(db, status=STATUS_APPROVED)

    def list_pending_validation(self, db: Session) -> list[Skill]:
        return db.query(Skill).filter(
            or_(
                Skill.status.in_([STATUS_PENDING, STATUS_VALIDATING]),
                Skill.validation_stage.in_([VALIDATION_STAGE_LAYER1, VALIDATION_STAGE_LAYER2])
            )
        ).order_by(Skill.created_at.desc()).all()
    
    def approve(self, db: Session, skill_id: str, admin_id: str) -> Skill:
        """Approve a skill and move to approved directory."""
        skill = self.get(db, skill_id)
        if not skill:
            raise ValueError(f"Skill not found: {skill_id}")
        
        if skill.status not in [STATUS_PENDING]:
            raise ValueError(f"Cannot approve skill with status: {skill.status}")
        
        if skill.validation_stage != VALIDATION_STAGE_COMPLETED:
            raise ValueError(f"Skill validation not completed: {skill.validation_stage}")
        
        old_path = Path(skill.skill_path)
        new_path = self.approved_dir / skill.name
        
        if new_path.exists():
            shutil.rmtree(new_path)
        
        shutil.move(str(old_path), str(new_path))
        
        skill.status = STATUS_APPROVED
        skill.approved_by = admin_id
        skill.approved_at = datetime.utcnow()
        skill.skill_path = str(new_path)
        
        db.commit()
        db.refresh(skill)
        
        return skill
    
    def reject(self, db: Session, skill_id: str, admin_id: str, reason: str) -> Skill:
        """Reject a skill."""
        skill = self.get(db, skill_id)
        if not skill:
            raise ValueError(f"Skill not found: {skill_id}")
        
        skill.status = STATUS_REJECTED
        skill.rejected_by = admin_id
        skill.rejected_at = datetime.utcnow()
        skill.reject_reason = reason
        
        db.commit()
        db.refresh(skill)
        
        return skill
    
    def delete(self, db: Session, skill_id: str) -> bool:
        """Delete a skill and its files."""
        skill = self.get(db, skill_id)
        if not skill:
            return False
        
        skill_path = Path(skill.skill_path)
        if skill_path.exists():
            shutil.rmtree(skill_path)
        
        db.delete(skill)
        db.commit()
        
        return True
    
    def update_validation_result(
        self,
        db: Session,
        skill_id: str,
        validation_stage: str,
        layer1_report: dict | None = None,
        layer2_report: dict | None = None,
        scores: dict | None = None,
        installed_dependencies: dict | None = None,
    ) -> Skill:
        """Update skill validation results."""
        skill = self.get(db, skill_id)
        if not skill:
            raise ValueError(f"Skill not found: {skill_id}")
        
        logger.info(f"[update_validation_result] 更新验证结果 skill_id={skill_id} stage={validation_stage}")
        
        skill.validation_stage = validation_stage
        
        if layer1_report:
            skill.layer1_report = layer1_report
            skill.layer1_passed = layer1_report.get("passed", False)
            logger.info(f"[update_validation_result] layer1_passed={skill.layer1_passed}")
        
        if layer2_report:
            skill.layer2_report = layer2_report
            skill.layer2_passed = layer2_report.get("passed", False)
        
        if scores:
            skill.completion_score = scores.get("completion_score")
            skill.trigger_accuracy_score = scores.get("trigger_score")
            skill.offline_capability_score = scores.get("offline_score")
            skill.resource_efficiency_score = scores.get("resource_score")
            skill.validation_score = scores.get("overall")
            skill.score_weights = scores.get("weights")
            logger.info(f"[update_validation_result] scores: completion={skill.completion_score}, trigger={skill.trigger_accuracy_score}, offline={skill.offline_capability_score}, resource={skill.resource_efficiency_score}, overall={skill.validation_score}")
        
        if installed_dependencies:
            skill.installed_dependencies = installed_dependencies
            logger.info(f"[update_validation_result] 依赖数量: {len(installed_dependencies) if installed_dependencies else 0}")
        
        if validation_stage == VALIDATION_STAGE_COMPLETED:
            skill.validated_at = datetime.utcnow()
            logger.info(f"[update_validation_result] 验证完成时间: {skill.validated_at}")
        
        db.commit()
        db.refresh(skill)
        
        return skill
    
    def set_validating(self, db: Session, skill_id: str) -> Skill:
        """Set skill status to validating."""
        skill = self.get(db, skill_id)
        if not skill:
            raise ValueError(f"Skill not found: {skill_id}")
        
        logger.info(f"[set_validating] 状态变更 skill_id={skill_id} {skill.status} -> {STATUS_VALIDATING}")
        
        skill.status = STATUS_VALIDATING
        skill.validation_stage = VALIDATION_STAGE_LAYER1
        
        db.commit()
        db.refresh(skill)
        
        return skill
    
    def set_validation_failed(self, db: Session, skill_id: str) -> Skill:
        """Set skill validation as failed."""
        skill = self.get(db, skill_id)
        if not skill:
            raise ValueError(f"Skill not found: {skill_id}")
        
        logger.warning(f"[set_validation_failed] 验证失败 skill_id={skill_id} {skill.status} -> {STATUS_PENDING}")
        
        skill.status = STATUS_PENDING
        skill.validation_stage = VALIDATION_STAGE_FAILED
        
        db.commit()
        db.refresh(skill)
        
        return skill
    
    def move_to_approved_dir(self, skill: Skill) -> Skill:
        """Move skill files to approved directory."""
        old_path = Path(skill.skill_path)
        new_path = self.approved_dir / skill.name
        
        if new_path.exists():
            shutil.rmtree(new_path)
        
        shutil.move(str(old_path), str(new_path))
        
        return skill


def get_skill_manager() -> SkillManager:
    """Get skill manager instance."""
    return SkillManager()
