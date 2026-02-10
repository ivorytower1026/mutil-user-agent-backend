import os
import base64
import docker
import json
from deepagents.backends.sandbox import BaseSandbox
from deepagents.backends.protocol import (
    ExecuteResponse,
    FileUploadResponse,
    FileDownloadResponse
)
from src.config import (
    DOCKER_IMAGE,
    WORKSPACE_ROOT,
    SHARED_DIR,
    CONTAINER_WORKSPACE_DIR,
    CONTAINER_SHARED_DIR
)


_thread_backends = {}


def get_thread_backend(thread_id: str) -> 'DockerSandboxBackend':
    if thread_id not in _thread_backends:
        workspace_dir = os.path.join(WORKSPACE_ROOT, thread_id)
        os.makedirs(workspace_dir, exist_ok=True)
        _thread_backends[thread_id] = DockerSandboxBackend(thread_id, workspace_dir)
    return _thread_backends[thread_id]


class DockerSandboxBackend(BaseSandbox):
    def __init__(self, thread_id: str, workspace_dir: str):
        self.thread_id = thread_id
        self.workspace_dir = workspace_dir
        self.image = DOCKER_IMAGE
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
                f"cd {CONTAINER_WORKSPACE_DIR} && {command}",
                workdir=CONTAINER_WORKSPACE_DIR
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
        results = []
        for file_path, content in files:
            try:
                full_path = os.path.join(self.workspace_dir, file_path)
                os.makedirs(os.path.dirname(full_path), exist_ok=True)
                with open(full_path, 'wb') as f:
                    f.write(content)
                results.append(FileUploadResponse(path=file_path, error=None))
            except Exception as e:
                results.append(FileUploadResponse(path=file_path, error="permission_denied"))
        return results

    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        results = []
        for file_path in paths:
            try:
                full_path = os.path.join(self.workspace_dir, file_path.lstrip('/'))
                with open(full_path, 'rb') as f:
                    content = f.read()
                results.append(FileDownloadResponse(path=file_path, content=content, error=None))
            except FileNotFoundError:
                results.append(FileDownloadResponse(path=file_path, content=None, error="file_not_found"))
            except Exception:
                results.append(FileDownloadResponse(path=file_path, content=None, error="permission_denied"))
        return results

    def _create_container(self):
        return self.client.containers.create(
            image=self.image,
            command="sleep infinity",
            volumes={
                self.workspace_dir: {"bind": CONTAINER_WORKSPACE_DIR, "mode": "rw"},
                SHARED_DIR: {"bind": CONTAINER_SHARED_DIR, "mode": "ro"}
            }
        )
