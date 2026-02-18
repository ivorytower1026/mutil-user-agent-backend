"""Skill image management with pluggable backend support."""
import subprocess
from pathlib import Path
from typing import Protocol
import docker

from src.config import settings


class ImageBackend(Protocol):
    """Protocol for image storage backends."""
    
    def save(self, container_id: str, version: str) -> str:
        """Save container as image, return image identifier."""
        ...
    
    def load(self, version: str) -> str:
        """Load image by version, return image ID."""
        ...
    
    def list_versions(self) -> list[str]:
        """List all available versions."""
        ...
    
    def delete(self, version: str) -> bool:
        """Delete a version, return True if successful."""
        ...
    
    def get_current(self) -> str | None:
        """Get current production version."""
        ...


class LocalFileImageBackend:
    """Local file-based image storage backend using docker save/load."""
    
    def __init__(self):
        self.images_dir = Path(settings.SKILL_IMAGES_DIR).expanduser().absolute()
        self.images_dir.mkdir(parents=True, exist_ok=True)
        self.max_versions = settings.SKILL_IMAGE_VERSIONS_TO_KEEP
        self.prefix = "skill-runtime"
        self.client = docker.from_env()
    
    def save(self, container_id: str, version: str) -> str:
        """Save container as tar file using docker save."""
        container = self.client.containers.get(container_id)
        
        image_name = f"{self.prefix}:{version}"
        image = container.commit(repository=self.prefix, tag=version)
        
        tar_file = self.images_dir / f"{self.prefix}-{version}.tar"
        with open(tar_file, 'wb') as f:
            for chunk in image.save():
                f.write(chunk)
        
        self._cleanup_old_versions()
        self._update_current_version(version)
        
        print(f"[ImageManager] Saved image to {tar_file}")
        return str(tar_file)
    
    def load(self, version: str) -> str:
        """Load image from tar file."""
        tar_file = self.images_dir / f"{self.prefix}-{version}.tar"
        
        if not tar_file.exists():
            raise FileNotFoundError(f"Image file not found: {tar_file}")
        
        result = subprocess.run(
            ["docker", "load", "-i", str(tar_file)],
            capture_output=True,
            text=True
        )
        
        if result.returncode != 0:
            raise RuntimeError(f"Failed to load image: {result.stderr}")
        
        print(f"[ImageManager] Loaded image {version}")
        return f"{self.prefix}:{version}"
    
    def list_versions(self) -> list[str]:
        """List all saved versions."""
        tar_files = list(self.images_dir.glob(f"{self.prefix}-v*.tar"))
        versions = sorted([f.stem.replace(f"{self.prefix}-", "") for f in tar_files])
        return versions
    
    def delete(self, version: str) -> bool:
        """Delete a version's tar file."""
        tar_file = self.images_dir / f"{self.prefix}-{version}.tar"
        if tar_file.exists():
            tar_file.unlink()
            print(f"[ImageManager] Deleted {version}")
            return True
        return False
    
    def get_current(self) -> str | None:
        """Get the latest version."""
        versions = self.list_versions()
        return versions[-1] if versions else None
    
    def get_next_version(self) -> str:
        """Get next version number."""
        versions = self.list_versions()
        if not versions:
            return "v1.0"
        last = versions[-1]
        num = int(last.replace("v", "").replace(".", ""))
        return f"v1.{num}"
    
    def _cleanup_old_versions(self):
        """Keep only the last N versions."""
        versions = self.list_versions()
        if len(versions) > self.max_versions:
            for v in versions[:-self.max_versions]:
                self.delete(v)
    
    def _update_current_version(self, version: str):
        """Update current version in database."""
        from src.database import SessionLocal, ImageVersion
        
        with SessionLocal() as db:
            db.query(ImageVersion).update({"is_current": False})
            
            new_version = ImageVersion(
                version=version,
                is_current=True
            )
            db.add(new_version)
            db.commit()


def get_image_backend() -> ImageBackend:
    """Get the configured image backend."""
    return LocalFileImageBackend()
