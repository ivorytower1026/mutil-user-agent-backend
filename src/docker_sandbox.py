import os
import docker
from pathlib import Path
from deepagents.backends.sandbox import BaseSandbox
from deepagents.backends.protocol import (
    ExecuteResponse,
    FileUploadResponse,
    FileDownloadResponse
)
from src.config import settings


_thread_backends = {}


def get_thread_backend(thread_id: str) -> 'DockerSandboxBackend':
    """Get or create a thread backend.
    
    Workspace directory structure: workspaces/{user_id}/{thread_id}/
    where thread_id format is {user_id}-{uuid}
    """
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


def destroy_thread_backend(thread_id: str) -> bool:
    """Destroy a thread backend and its container.
    
    Args:
        thread_id: The thread ID to destroy
        
    Returns:
        True if destroyed, False if not found
    """
    if thread_id in _thread_backends:
        _thread_backends[thread_id].destroy()
        del _thread_backends[thread_id]
        return True
    return False


class DockerSandboxBackend(BaseSandbox):
    """Docker-based sandbox backend with persistent container.
    
    Container is created on first execute() and reused for subsequent calls.
    Must be explicitly destroyed via destroy() or destroy_thread_backend().
    """
    
    def __init__(self, thread_id: str, workspace_dir: str):
        self.thread_id = thread_id
        self.workspace_dir = workspace_dir
        self.image = settings.DOCKER_IMAGE
        self.client = docker.from_env()
        self._container: docker.models.containers.Container | None = None

    @property
    def id(self) -> str:
        return self.thread_id

    def _ensure_container(self) -> docker.models.containers.Container:
        """Ensure container exists and is running (lazy initialization).
        
        Creates container on first call, returns existing container on subsequent calls.
        Handles container recovery if it was stopped or removed externally.
        """
        if self._container is None:
            self._container = self._create_container()
            self._container.start()
            print(f"[DockerSandbox] Created container for thread {self.thread_id}")
        else:
            try:
                self._container.reload()
                if self._container.status != "running":
                    print(f"[DockerSandbox] Container not running (status={self._container.status}), recreating...")
                    self._container.remove(force=True)
                    self._container = self._create_container()
                    self._container.start()
            except docker.errors.NotFound:
                print(f"[DockerSandbox] Container not found, recreating...")
                self._container = self._create_container()
                self._container.start()
        return self._container

    def execute(self, command: str) -> ExecuteResponse:
        """Execute a command in the sandbox.
        
        Container is created on first call and reused for subsequent calls.
        """
        container = self._ensure_container()

        exit_code, output = container.exec_run(
            cmd=["/bin/bash", "-lc", command],
            workdir=settings.CONTAINER_WORKSPACE_DIR,
        )

        return ExecuteResponse(
            output=output.decode('utf-8'),
            exit_code=exit_code,
            truncated=False
        )

    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        """Upload files - files are written directly to workspace directory."""
        results = []
        for file_path, content in files:
            try:
                full_path = os.path.join(self.workspace_dir, file_path.lstrip('/'))
                os.makedirs(os.path.dirname(full_path), exist_ok=True)
                with open(full_path, 'wb') as f:
                    f.write(content)
                results.append(FileUploadResponse(path=file_path, error=None))
            except Exception as e:
                results.append(FileUploadResponse(path=file_path, error=str(e)))
        return results

    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        """Download files - files are read directly from workspace directory."""
        results = []
        for file_path in paths:
            try:
                full_path = os.path.join(self.workspace_dir, file_path.lstrip('/'))
                with open(full_path, 'rb') as f:
                    content = f.read()
                results.append(FileDownloadResponse(path=file_path, content=content, error=None))
            except Exception as e:
                results.append(FileDownloadResponse(path=file_path, content=None, error=str(e)))
        return results

    def destroy(self) -> None:
        """Destroy the container explicitly.
        
        Should be called when the session is no longer needed.
        Safe to call multiple times.
        """
        if self._container is not None:
            try:
                self._container.remove(force=True)
                print(f"[DockerSandbox] Destroyed container for thread {self.thread_id}")
            except docker.errors.APIError as e:
                print(f"[DockerSandbox] Warning: Failed to destroy container: {e}")
            finally:
                self._container = None

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
        
        # Global shared directory
        shared_dir = str(Path(settings.SHARED_DIR).expanduser().absolute())
        os.makedirs(shared_dir, exist_ok=True)
        
        # Global skills directory (独立挂载)
        skills_dir = os.path.join(shared_dir, "skills")
        os.makedirs(skills_dir, exist_ok=True)
        
        return self.client.containers.create(
            image=self.image,
            command="sleep infinity",
            working_dir=settings.CONTAINER_WORKSPACE_DIR,
            volumes={
                self.workspace_dir: {"bind": settings.CONTAINER_WORKSPACE_DIR, "mode": "rw"},
                user_shared_dir: {"bind": settings.USER_SHARED, "mode": "rw"},
                shared_dir: {"bind": settings.CONTAINER_SHARED_DIR, "mode": "ro"},
                skills_dir: {"bind": settings.CONTAINER_SKILLS_DIR, "mode": "ro"}
            }
        )
