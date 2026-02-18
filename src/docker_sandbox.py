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


def _to_docker_path(path: str) -> str:
    """Convert Windows path to Docker-compatible path format.
    
    Windows Docker Desktop expects paths in Unix format:
    - D:\\path -> /d/path
    - D:/path -> /d/path
    """
    p = Path(path).absolute()
    path_str = str(p).replace('\\', '/')
    if len(path_str) >= 2 and path_str[1] == ':':
        path_str = '/' + path_str[0].lower() + path_str[2:]
    return path_str


_user_backends = {}


def get_thread_backend(thread_id: str) -> 'DockerSandboxBackend':
    """Get or create a user-level backend.
    
    All threads of the same user share the same container.
    Workspace directory: workspaces/{user_id}/
    """
    user_id = thread_id[:36]
    
    if user_id not in _user_backends:
        workspace_dir = os.path.join(
            Path(settings.WORKSPACE_ROOT).expanduser().absolute(),
            user_id
        )
        os.makedirs(workspace_dir, exist_ok=True)
        _user_backends[user_id] = DockerSandboxBackend(user_id, workspace_dir)
    
    return _user_backends[user_id]


def destroy_user_backend(user_id: str) -> bool:
    """Destroy a user's backend and its container.
    
    Args:
        user_id: The user ID to destroy
        
    Returns:
        True if destroyed, False if not found
    """
    if user_id in _user_backends:
        _user_backends[user_id].destroy()
        del _user_backends[user_id]
        return True
    return False


def destroy_thread_backend(thread_id: str) -> bool:
    """Destroy a thread's container (compatibility wrapper).
    
    Args:
        thread_id: The thread ID (will extract user_id)
        
    Returns:
        True if destroyed, False if not found
    """
    user_id = thread_id[:36]
    return destroy_user_backend(user_id)


class DockerSandboxBackend(BaseSandbox):
    """Docker-based sandbox backend with user-level container sharing.
    
    Container is created on first execute() and reused for subsequent calls.
    All threads of the same user share this container.
    """
    
    def __init__(self, user_id: str, workspace_dir: str):
        self.user_id = user_id
        self.workspace_dir = workspace_dir
        self.image = settings.DOCKER_IMAGE
        self.client = docker.from_env()
        self._container: docker.models.containers.Container | None = None

    @property
    def id(self) -> str:
        return self.user_id

    def _ensure_container(self) -> docker.models.containers.Container:
        """Ensure container exists and is running (lazy initialization).
        
        Creates container on first call, returns existing container on subsequent calls.
        Handles container recovery if it was stopped or removed externally.
        """
        if self._container is None:
            self._container = self._create_container()
            self._container.start()
            print(f"[DockerSandbox] Created container for user {self.user_id}")
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
                print(f"[DockerSandbox] Destroyed container for user {self.user_id}")
            except docker.errors.APIError as e:
                print(f"[DockerSandbox] Warning: Failed to destroy container: {e}")
            finally:
                self._container = None

    def _create_container(self) -> docker.models.containers.Container:
        """Create a new container (does not start it).
        
        Mounts:
        - /workspace: User-level workspace (rw) - shared by all user's threads
        - /shared: Global shared directory (ro)
        - /skills: Global skills directory (ro)
        """
        shared_dir = str(Path(settings.SHARED_DIR).expanduser().absolute())
        os.makedirs(shared_dir, exist_ok=True)
        
        skills_dir = os.path.join(shared_dir, "skills")
        os.makedirs(skills_dir, exist_ok=True)
        
        return self.client.containers.create(
            image=self.image,
            command="sleep infinity",
            working_dir=settings.CONTAINER_WORKSPACE_DIR,
            volumes={
                _to_docker_path(self.workspace_dir): {"bind": settings.CONTAINER_WORKSPACE_DIR, "mode": "rw"},
                _to_docker_path(shared_dir): {"bind": settings.CONTAINER_SHARED_DIR, "mode": "ro"},
                _to_docker_path(skills_dir): {"bind": settings.CONTAINER_SKILLS_DIR, "mode": "ro"}
            }
        )

    def disconnect_network(self) -> bool:
        """Disconnect container from network (for offline testing).
        
        Returns:
            True if successfully disconnected, False otherwise
        """
        container = self._ensure_container()
        try:
            self.client.networks.get("bridge").disconnect(container)
            print(f"[DockerSandbox] Disconnected container from network for user {self.user_id}")
            return True
        except docker.errors.APIError as e:
            print(f"[DockerSandbox] Failed to disconnect network: {e}")
            return False

    def reconnect_network(self) -> bool:
        """Reconnect container to network.
        
        Returns:
            True if successfully reconnected, False otherwise
        """
        container = self._ensure_container()
        try:
            self.client.networks.get("bridge").connect(container)
            print(f"[DockerSandbox] Reconnected container to network for user {self.user_id}")
            return True
        except docker.errors.APIError as e:
            print(f"[DockerSandbox] Failed to reconnect network: {e}")
            return False

    def get_container_stats(self) -> dict:
        """Get container resource statistics.
        
        Returns:
            Dict with cpu_percent, memory_mb, etc.
        """
        container = self._ensure_container()
        try:
            stats = container.stats(stream=False)
            
            cpu_delta = stats["cpu_stats"]["cpu_usage"]["total_usage"] - stats["precpu_stats"]["cpu_usage"]["total_usage"]
            system_delta = stats["cpu_stats"]["system_cpu_usage"] - stats["precpu_stats"]["system_cpu_usage"]
            
            cpu_percent = 0.0
            if system_delta > 0 and cpu_delta > 0:
                cpu_percent = (cpu_delta / system_delta) * 100.0
            
            memory_mb = stats["memory_stats"].get("usage", 0) / 1024 / 1024
            
            return {
                "cpu_percent": round(cpu_percent, 2),
                "memory_mb": round(memory_mb, 2),
                "container_id": container.id[:12],
            }
        except Exception as e:
            print(f"[DockerSandbox] Failed to get stats: {e}")
            return {
                "cpu_percent": 0.0,
                "memory_mb": 0.0,
                "error": str(e)
            }

    @property
    def container_id(self) -> str | None:
        """Get container ID if container exists."""
        if self._container:
            return self._container.id
        return None
