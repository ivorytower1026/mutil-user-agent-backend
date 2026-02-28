"""Simple skill manager without validation."""

import os
import uuid
import zipfile
import shutil
from pathlib import Path
from typing import BinaryIO

from sqlalchemy.orm import Session

from src.config import settings
from src.database import Skill, SessionLocal
from src.utils.get_logger import get_logger

logger = get_logger("simple-skill-manager")

STATUS_ACTIVE = "active"
STATUS_DISABLED = "disabled"


def get_skills_dir() -> Path:
    """Get skills directory."""
    if settings.SKILL_DIR:
        return Path(settings.SKILL_DIR).expanduser().absolute()
    return Path(settings.SHARED_DIR).expanduser().absolute() / "skills"


def validate_skill_format(skill_path: str) -> tuple[bool, list[str], list[str]]:
    """Validate skill format using DeepAgents' parser."""
    try:
        from deepagents.middleware.skills import _parse_skill_metadata
    except ImportError:
        return True, [], []

    skill_md_path = os.path.join(skill_path, "SKILL.md")
    errors = []
    warnings = []

    if not os.path.exists(skill_md_path):
        return False, ["Missing SKILL.md"], []

    with open(skill_md_path, encoding="utf-8") as f:
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


class SimpleSkillManager:
    """Simple skill manager without validation workflow."""

    def __init__(self):
        self.skills_dir = get_skills_dir()
        self.skills_dir.mkdir(parents=True, exist_ok=True)

    def upload(
        self, db: Session, file: BinaryIO, filename: str, user_id: str | None = None
    ) -> Skill:
        """Upload skill directly to skills directory without validation."""
        skill_id = str(uuid.uuid4())
        temp_dir = self.skills_dir / f"temp_{skill_id}"

        try:
            temp_dir.mkdir(parents=True, exist_ok=True)

            zip_path = temp_dir / filename
            with open(zip_path, "wb") as f:
                f.write(file.read())

            extract_dir = temp_dir / "extracted"
            with zipfile.ZipFile(zip_path, "r") as zip_ref:
                zip_ref.extractall(extract_dir)

            extracted_items = list(extract_dir.iterdir())
            if len(extracted_items) == 1 and extracted_items[0].is_dir():
                skill_dir = extracted_items[0]
            else:
                skill_dir = extract_dir

            passed, errors, warnings = validate_skill_format(str(skill_dir))

            metadata = {}
            skill_md_path = skill_dir / "SKILL.md"
            if skill_md_path.exists():
                with open(skill_md_path, encoding="utf-8") as f:
                    content = f.read()
                try:
                    from deepagents.middleware.skills import _parse_skill_metadata

                    metadata = (
                        _parse_skill_metadata(
                            content, str(skill_md_path), skill_dir.name
                        )
                        or {}
                    )
                except ImportError:
                    pass

            name = metadata.get("name", Path(filename).stem)

            final_dir = self.skills_dir / name
            if final_dir.exists():
                shutil.rmtree(final_dir)
            shutil.move(str(skill_dir), str(final_dir))

            shutil.rmtree(temp_dir)

            existing = db.query(Skill).filter(Skill.name == name).first()
            if existing:
                existing.skill_path = str(final_dir)
                existing.display_name = metadata.get("display_name", name)
                existing.description = metadata.get("description", "")
                existing.status = STATUS_ACTIVE
                existing.format_valid = passed
                existing.format_errors = errors
                existing.format_warnings = warnings
                db.commit()
                db.refresh(existing)
                logger.info(f"[SimpleSkillManager] Updated skill: {name}")
                return existing

            skill = Skill(
                skill_id=skill_id,
                name=name,
                display_name=metadata.get("display_name", name),
                description=metadata.get("description", ""),
                status=STATUS_ACTIVE,
                skill_path=str(final_dir),
                format_valid=passed,
                format_errors=errors,
                format_warnings=warnings,
                created_by=user_id,
            )

            db.add(skill)
            db.commit()
            db.refresh(skill)

            logger.info(f"[SimpleSkillManager] Uploaded skill: {name}")
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
        """List all skills."""
        query = db.query(Skill)
        if status:
            query = query.filter(Skill.status == status)
        return query.order_by(Skill.created_at.desc()).all()

    def list_active(self, db: Session) -> list[Skill]:
        """List all active skills."""
        return self.list_all(db, status=STATUS_ACTIVE)

    def delete(self, db: Session, skill_id: str) -> bool:
        """Delete a skill."""
        skill = self.get(db, skill_id)
        if not skill:
            return False

        skill_path = Path(skill.skill_path)
        if skill_path.exists():
            shutil.rmtree(skill_path)

        db.delete(skill)
        db.commit()

        logger.info(f"[SimpleSkillManager] Deleted skill: {skill.name}")
        return True

    def delete_by_name(self, db: Session, name: str) -> bool:
        """Delete a skill by name."""
        skill = self.get_by_name(db, name)
        if not skill:
            return False
        return self.delete(db, skill.skill_id)

    def disable(self, db: Session, skill_id: str) -> Skill | None:
        """Disable a skill."""
        skill = self.get(db, skill_id)
        if not skill:
            return None

        skill.status = STATUS_DISABLED
        db.commit()
        db.refresh(skill)

        logger.info(f"[SimpleSkillManager] Disabled skill: {skill.name}")
        return skill

    def enable(self, db: Session, skill_id: str) -> Skill | None:
        """Enable a skill."""
        skill = self.get(db, skill_id)
        if not skill:
            return None

        skill.status = STATUS_ACTIVE
        db.commit()
        db.refresh(skill)

        logger.info(f"[SimpleSkillManager] Enabled skill: {skill.name}")
        return skill

    def sync_to_db(self, db: Session) -> int:
        """Sync skills directory to database."""
        synced = 0

        if not self.skills_dir.exists():
            return 0

        for skill_dir in self.skills_dir.iterdir():
            if not skill_dir.is_dir():
                continue

            skill_md = skill_dir / "SKILL.md"
            if not skill_md.exists():
                continue

            name = skill_dir.name

            metadata = {}
            if skill_md.exists():
                with open(skill_md, encoding="utf-8") as f:
                    content = f.read()
                try:
                    from deepagents.middleware.skills import _parse_skill_metadata

                    metadata = _parse_skill_metadata(content, str(skill_md), name) or {}
                except ImportError:
                    pass

            existing = db.query(Skill).filter(Skill.name == name).first()

            if existing:
                existing.skill_path = str(skill_dir)
                existing.display_name = metadata.get("display_name", name)
                existing.description = metadata.get("description", "")
                if existing.status not in [STATUS_ACTIVE, STATUS_DISABLED]:
                    existing.status = STATUS_ACTIVE
            else:
                skill = Skill(
                    skill_id=str(uuid.uuid4()),
                    name=name,
                    display_name=metadata.get("display_name", name),
                    description=metadata.get("description", ""),
                    status=STATUS_ACTIVE,
                    skill_path=str(skill_dir),
                )
                db.add(skill)

            synced += 1

        db.commit()
        logger.info(f"[SimpleSkillManager] Synced {synced} skills to database")
        return synced

    def get_skill_path(self, name: str) -> str | None:
        """Get skill path by name."""
        skill_path = self.skills_dir / name
        if skill_path.exists():
            return str(skill_path)
        return None


def get_simple_skill_manager() -> SimpleSkillManager:
    """Get simple skill manager instance."""
    return SimpleSkillManager()
