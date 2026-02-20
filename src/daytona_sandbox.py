"""Daytona Sandbox 后端，实现 BaseSandbox 接口"""
import hashlib
from deepagents.backends.sandbox import BaseSandbox
from deepagents.backends.protocol import (
    ExecuteResponse,
    FileUploadResponse,
    FileDownloadResponse,
)

WORKSPACE_PATH = "/home/daytona"


def _compute_etag(content: bytes) -> str:
    """计算文件内容的ETag（MD5哈希）"""
    return f'"{hashlib.md5(content).hexdigest()}"'


class DaytonaSandboxBackend(BaseSandbox):
    """Daytona Sandbox 后端"""
    
    def __init__(self, sandbox_id: str, sandbox):
        self.sandbox_id = sandbox_id
        self._sandbox = sandbox
        self._etags: dict[str, str] = {}
    
    @property
    def id(self) -> str:
        return self.sandbox_id
    
    def execute(self, command: str) -> ExecuteResponse:
        """执行命令"""
        response = self._sandbox.process.exec(command, timeout=300)
        return ExecuteResponse(
            output=response.result,
            exit_code=response.exit_code,
            truncated=False
        )
    
    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        """上传文件"""
        results = []
        for file_path, content in files:
            try:
                self._sandbox.fs.upload_file(content, f"{WORKSPACE_PATH}/{file_path}")
                results.append(FileUploadResponse(path=file_path, error=None))
            except Exception as e:
                results.append(FileUploadResponse(path=file_path, error=str(e)))
        return results
    
    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        """下载文件"""
        results = []
        for file_path in paths:
            try:
                content = self._sandbox.fs.download_file(f"{WORKSPACE_PATH}/{file_path}")
                results.append(FileDownloadResponse(path=file_path, content=content, error=None))
            except Exception as e:
                results.append(FileDownloadResponse(path=file_path, content=None, error=str(e)))
        return results
    
    # Files Sandbox 专用方法（WebDAV 用）
    def fs_download(self, path: str) -> bytes:
        """下载文件"""
        return self._sandbox.fs.download_file(f"{WORKSPACE_PATH}/{path}")
    
    def fs_upload(self, path: str, content: bytes) -> str:
        """上传文件，返回ETag"""
        self._sandbox.fs.upload_file(content, f"{WORKSPACE_PATH}/{path}")
        etag = _compute_etag(content)
        self._etags[path] = etag
        return etag
    
    def fs_get_etag(self, path: str) -> str | None:
        """获取文件的ETag，如果不在缓存中则下载文件计算"""
        if path in self._etags:
            return self._etags[path]
        try:
            content = self.fs_download(path)
            etag = _compute_etag(content)
            self._etags[path] = etag
            return etag
        except Exception:
            return None
    
    def fs_list(self, path: str) -> list:
        """列出目录"""
        return self._sandbox.fs.list_files(f"{WORKSPACE_PATH}/{path}")
    
    def fs_delete(self, path: str):
        """删除文件"""
        self._sandbox.fs.delete_file(f"{WORKSPACE_PATH}/{path}")
        self._etags.pop(path, None)
    
    def destroy(self):
        """销毁 Sandbox"""
        from src.daytona_client import get_daytona_client
        get_daytona_client().client.delete(self._sandbox)
