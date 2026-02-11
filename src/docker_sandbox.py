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
    if thread_id not in _thread_backends:
        workspace_dir = os.path.join(
            Path(settings.WORKSPACE_ROOT).expanduser().absolute(),
            thread_id
        )
        os.makedirs(workspace_dir, exist_ok=True)
        _thread_backends[thread_id] = DockerSandboxBackend(thread_id, workspace_dir)
    return _thread_backends[thread_id]


class DockerSandboxBackend(BaseSandbox):
    def __init__(self, thread_id: str, workspace_dir: str):
        self.thread_id = thread_id
        self.workspace_dir = workspace_dir
        self.image = settings.DOCKER_IMAGE
        self.client = docker.from_env()

    @property
    def id(self) -> str:
        return self.thread_id

    def execute(self, command: str) -> ExecuteResponse:
        container = None
        try:
            container = self._create_container()
            container.start()

            exit_code, output = container.exec_run(
                cmd=["/bin/bash", "-lc", command],
                workdir=settings.CONTAINER_WORKSPACE_DIR,
            )

            return ExecuteResponse(
                output=output.decode('utf-8'),
                exit_code=exit_code,
                truncated=False
            )
        finally:
            if container:
                container.remove(force=True)

    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        """Upload files - not needed for DockerSandboxBackend as all operations happen in container."""
        results = []
        for file_path, _ in files:
            results.append(FileUploadResponse(path=file_path, error=None))
        return results

    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        """Download files - not needed for DockerSandboxBackend as all operations happen in container."""
        results = []
        for file_path in paths:
            results.append(FileDownloadResponse(path=file_path, content=None, error=None))
        return results

    def _create_container(self):
        return self.client.containers.create(
            image=self.image,
            command="sleep infinity",
            working_dir=settings.CONTAINER_WORKSPACE_DIR,
            volumes={
                self.workspace_dir: {"bind": settings.CONTAINER_WORKSPACE_DIR, "mode": "rw"},
                str(Path(settings.SHARED_DIR).expanduser().absolute()): {"bind": settings.CONTAINER_SHARED_DIR, "mode": "ro"}
            }
        )
