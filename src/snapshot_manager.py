"""Skills 快照管理服务"""
from datetime import datetime
from pathlib import Path

from src.config import settings
from src.daytona_client import get_daytona_client
from src.database import SessionLocal, Skill
from src.utils.get_logger import get_logger

logger = get_logger("snapshot-manager")


class SnapshotManager:
    """管理全局 Skills 快照"""
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._current_snapshot_id: str | None = None
            logger.info("[SnapshotManager] Initialized")
        return cls._instance
    
    def get_current_snapshot_id(self) -> str | None:
        """获取当前快照 ID"""
        if self._current_snapshot_id:
            return self._current_snapshot_id
        if settings.DAYTONA_SKILLS_SNAPSHOT_ID:
            self._current_snapshot_id = settings.DAYTONA_SKILLS_SNAPSHOT_ID
            logger.info(f"[SnapshotManager] Using snapshot from config: {self._current_snapshot_id[:8]}...")
        return self._current_snapshot_id
    
    def rebuild_skills_snapshot(self) -> str | None:
        """重建包含所有已验证 Skills 的快照"""
        client = get_daytona_client().client
        
        with SessionLocal() as db:
            approved_skills = db.query(Skill).filter(
                Skill.status == "approved"
            ).all()
        
        if not approved_skills:
            logger.warning("[SnapshotManager] No approved skills, skipping snapshot rebuild")
            return None
        
        skills_dir = Path(settings.SHARED_DIR) / "skills"
        if not skills_dir.exists():
            logger.warning(f"[SnapshotManager] Skills directory not found: {skills_dir}")
            return None
        
        logger.info(f"[SnapshotManager] Rebuilding snapshot with {len(approved_skills)} skills...")
        
        sandbox = client.create()
        logger.info(f"[SnapshotManager] Created temp sandbox {sandbox.id}")
        
        try:
            for skill in approved_skills:
                skill_path = skills_dir / skill.name
                if skill_path.exists():
                    self._upload_skill(sandbox, skill_path, skill.name)
                    logger.info(f"[SnapshotManager] Uploaded skill: {skill.name}")
                else:
                    logger.warning(f"[SnapshotManager] Skill path not found: {skill_path}")
            
            snapshot_name = f"skills-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
            snapshot = client.create_snapshot(sandbox.id, name=snapshot_name)
            logger.info(f"[SnapshotManager] Created snapshot: {snapshot.id}")
            
            old_snapshot_id = self._current_snapshot_id
            self._current_snapshot_id = snapshot.id
            
            self._cleanup_old_snapshots(keep=3)
            
            return snapshot.id
            
        except Exception as e:
            logger.error(f"[SnapshotManager] Failed to rebuild snapshot: {e}")
            return None
        finally:
            try:
                client.delete(sandbox)
                logger.info(f"[SnapshotManager] Cleaned up temp sandbox")
            except Exception:
                pass
    
    def _upload_skill(self, sandbox, skill_path: Path, skill_name: str):
        """上传单个 Skill 到 /skills/ 目录"""
        for file_path in skill_path.rglob("*"):
            if file_path.is_file():
                relative = file_path.relative_to(skill_path)
                sandbox_path = f"/skills/{skill_name}/{relative}"
                content = file_path.read_bytes()
                sandbox.fs.upload_file(content, sandbox_path)
    
    def _cleanup_old_snapshots(self, keep: int = 3):
        """清理旧快照"""
        try:
            client = get_daytona_client().client
            snapshots = client.list_snapshots()
            skills_snapshots = [s for s in snapshots if s.name.startswith("skills-")]
            skills_snapshots.sort(key=lambda x: x.created_at, reverse=True)
            
            for snapshot in skills_snapshots[keep:]:
                client.delete_snapshot(snapshot.id)
                logger.info(f"[SnapshotManager] Deleted old snapshot: {snapshot.id}")
        except Exception as e:
            logger.warning(f"[SnapshotManager] Failed to cleanup old snapshots: {e}")


def get_snapshot_manager() -> SnapshotManager:
    return SnapshotManager()
