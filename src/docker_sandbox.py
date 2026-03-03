import os
import time
import redis
import docker
from pathlib import Path
from deepagents.backends.sandbox import BaseSandbox
from deepagents.backends.protocol import (
    ExecuteResponse,
    FileUploadResponse,
    FileDownloadResponse,
)
from src.config import settings


def _to_docker_path(path: str) -> str:
    """Convert Windows path to Docker-compatible path format.

    Windows Docker Desktop expects paths in Unix format:
    - D:\\path -> /d/path
    - D:/path -> /d/path
    """
    p = Path(path).absolute()
    path_str = str(p).replace("\\", "/")
    if len(path_str) >= 2 and path_str[1] == ":":
        path_str = "/" + path_str[0].lower() + path_str[2:]
    return path_str


_redis_client = None


def _get_redis():
    """Get or create Redis client."""
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis_client


_thread_backends: dict[str, "DockerSandboxBackend"] = {}


def get_thread_backend(thread_id: str) -> "DockerSandboxBackend":
    """Get or create a thread-level backend.

    Each thread has its own container, but shares workspace with other threads of same user.
    Workspace directory: workspaces/{user_id}/
    """
    user_id = thread_id[:36]

    if thread_id not in _thread_backends:
        workspace_dir = os.path.join(
            Path(settings.WORKSPACE_ROOT).expanduser().absolute(), user_id
        )
        os.makedirs(workspace_dir, exist_ok=True)
        _thread_backends[thread_id] = DockerSandboxBackend(thread_id, workspace_dir)

    backend = _thread_backends[thread_id]
    backend._update_activity()
    return backend


def destroy_thread_backend(thread_id: str) -> bool:
    """Destroy a thread's container.

    Args:
        thread_id: The thread ID

    Returns:
        True if destroyed, False if not found
    """
    if thread_id in _thread_backends:
        _thread_backends[thread_id].destroy()
        del _thread_backends[thread_id]

    r = _get_redis()
    r.delete(f"sandbox:{thread_id}")
    return True


class DockerSandboxBackend(BaseSandbox):
    """Docker-based sandbox backend with thread-level isolation.

    Container is created on first execute() and reused for subsequent calls.
    Each thread has its own container and workspace.
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

    def _update_activity(self):
        """Update last activity timestamp in Redis."""
        r = _get_redis()
        r.hset(
            f"sandbox:{self.thread_id}",
            mapping={
                "container_id": self._container.id if self._container else "",
                "last_active_at": str(time.time()),
            },
        )

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
                    print(
                        f"[DockerSandbox] Container not running (status={self._container.status}), recreating..."
                    )
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
        self._update_activity()
        container = self._ensure_container()

        exit_code, output = container.exec_run(
            cmd=["/bin/bash", "-lc", command],
            workdir=settings.CONTAINER_WORKSPACE_DIR,
        )

        return ExecuteResponse(
            output=output.decode("utf-8"), exit_code=exit_code, truncated=False
        )

    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        """Upload files - files are written directly to workspace directory."""
        self._update_activity()
        results = []
        for file_path, content in files:
            try:
                full_path = os.path.join(self.workspace_dir, file_path.lstrip("/"))
                os.makedirs(os.path.dirname(full_path), exist_ok=True)
                with open(full_path, "wb") as f:
                    f.write(content)
                results.append(FileUploadResponse(path=file_path, error=None))
            except Exception as e:
                results.append(FileUploadResponse(path=file_path, error=str(e)))
        return results

    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        """Download files - reads from mounted directories based on path prefix."""
        self._update_activity()
        results = []
        
        for file_path in paths:
            try:
                if file_path.startswith(settings.CONTAINER_SKILLS_DIR + "/"):
                    base_dir = str(Path(settings.SKILL_DIR).expanduser().absolute())
                    relative_path = file_path[len(settings.CONTAINER_SKILLS_DIR) + 1:]
                elif file_path.startswith(settings.CONTAINER_SHARED_DIR + "/"):
                    base_dir = str(Path(settings.SHARED_DIR).expanduser().absolute())
                    relative_path = file_path[len(settings.CONTAINER_SHARED_DIR) + 1:]
                elif file_path.startswith(settings.CONTAINER_WORKSPACE_DIR + "/"):
                    base_dir = self.workspace_dir
                    relative_path = file_path[len(settings.CONTAINER_WORKSPACE_DIR) + 1:]
                else:
                    base_dir = self.workspace_dir
                    relative_path = file_path.lstrip("/")
                
                full_path = os.path.join(base_dir, relative_path)
                with open(full_path, "rb") as f:
                    content = f.read()
                results.append(
                    FileDownloadResponse(path=file_path, content=content, error=None)
                )
            except Exception as e:
                results.append(
                    FileDownloadResponse(path=file_path, content=None, error=str(e))
                )
        return results

    def destroy(self) -> None:
        """Destroy the container explicitly.

        Should be called when the session is no longer needed.
        Safe to call multiple times.
        """
        if self._container is not None:
            try:
                self._container.remove(force=True)
                print(
                    f"[DockerSandbox] Destroyed container for thread {self.thread_id}"
                )
            except docker.errors.APIError as e:
                print(f"[DockerSandbox] Warning: Failed to destroy container: {e}")
            finally:
                self._container = None

        r = _get_redis()
        r.delete(f"sandbox:{self.thread_id}")

    def _create_container(self) -> docker.models.containers.Container:
        """Create a new container (does not start it).

        Mounts:
        - /workspace: Thread workspace (rw)
        - /shared: Global shared directory (ro)
        - /skills: Global skills directory (ro)

        Resource limits:
        - CPU: DOCKER_CPU_LIMIT cores
        - Memory: DOCKER_MEMORY_LIMIT
        """
        shared_dir = str(Path(settings.SHARED_DIR).expanduser().absolute())
        os.makedirs(shared_dir, exist_ok=True)
        
        skills_dir = str(Path(settings.SKILL_DIR).expanduser().absolute())
        os.makedirs(skills_dir, exist_ok=True)

        return self.client.containers.create(
            image=self.image,
            command="sleep infinity",
            working_dir=settings.CONTAINER_WORKSPACE_DIR,
            volumes={
                _to_docker_path(self.workspace_dir): {
                    "bind": settings.CONTAINER_WORKSPACE_DIR,
                    "mode": "rw",
                },
                _to_docker_path(shared_dir): {
                    "bind": settings.CONTAINER_SHARED_DIR,
                    "mode": "ro",
                },
                _to_docker_path(skills_dir): {
                    "bind": settings.CONTAINER_SKILLS_DIR,
                    "mode": "ro",
                },
            },
            cpu_quota=int(settings.DOCKER_CPU_LIMIT * 100000),
            mem_limit=settings.DOCKER_MEMORY_LIMIT,
        )

    def disconnect_network(self) -> bool:
        """Disconnect container from network (for offline testing).

        Returns:
            True if successfully disconnected, False otherwise
        """
        container = self._ensure_container()
        try:
            self.client.networks.get("bridge").disconnect(container)
            print(
                f"[DockerSandbox] Disconnected container from network for thread {self.thread_id}"
            )
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
            print(
                f"[DockerSandbox] Reconnected container to network for thread {self.thread_id}"
            )
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

            cpu_delta = (
                stats["cpu_stats"]["cpu_usage"]["total_usage"]
                - stats["precpu_stats"]["cpu_usage"]["total_usage"]
            )
            system_delta = (
                stats["cpu_stats"]["system_cpu_usage"]
                - stats["precpu_stats"]["system_cpu_usage"]
            )

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
            return {"cpu_percent": 0.0, "memory_mb": 0.0, "error": str(e)}

    @property
    def container_id(self) -> str | None:
        """Get container ID if container exists."""
        if self._container:
            return self._container.id
        return None

    @staticmethod
    def cleanup_idle_containers() -> int:
        """Clean up containers that have been idle for too long.

        Scans Redis for all sandbox entries and removes those exceeding
        DOCKER_IDLE_TIMEOUT_SECONDS.

        Returns:
            Number of containers cleaned up
        """
        r = _get_redis()
        now = time.time()
        timeout = settings.DOCKER_IDLE_TIMEOUT_SECONDS
        cleaned = 0

        client = docker.from_env()

        for key in r.scan_iter("sandbox:*"):
            try:
                last_active_str = r.hget(key, "last_active_at")
                if not last_active_str:
                    continue

                last_active = float(last_active_str)
                if now - last_active > timeout:
                    container_id = r.hget(key, "container_id")
                    thread_id = key.replace("sandbox:", "")

                    if container_id:
                        try:
                            container = client.containers.get(container_id)
                            container.remove(force=True)
                            print(
                                f"[DockerSandbox] Cleaned up idle container for thread {thread_id}"
                            )
                        except docker.errors.NotFound:
                            pass
                        except Exception as e:
                            print(
                                f"[DockerSandbox] Error removing container {container_id}: {e}"
                            )

                    r.delete(key)

                    if thread_id in _thread_backends:
                        del _thread_backends[thread_id]

                    cleaned += 1
            except Exception as e:
                print(f"[DockerSandbox] Error processing key {key}: {e}")

        return cleaned
