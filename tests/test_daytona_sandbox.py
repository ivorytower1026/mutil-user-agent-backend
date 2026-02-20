"""Daytona Sandbox 核心功能测试"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.daytona_sandbox_manager import get_sandbox_manager


def test_agent_sandbox():
    """测试 Agent Sandbox"""
    print("=" * 50)
    print("Test Agent Sandbox...")
    print("=" * 50)
    
    manager = get_sandbox_manager()
    
    # 创建 Sandbox
    backend = manager.get_thread_backend("test-user-001-test-thread-001")
    print(f"[OK] Created: {backend.id}")
    
    # 执行命令
    result = backend.execute("echo 'Hello Daytona!'")
    print(f"[OK] Execute: {result.output.strip()}")
    assert "Hello Daytona!" in result.output
    assert result.exit_code == 0
    
    # 创建目录并写文件
    backend.execute("mkdir -p /home/daytona/test")
    backend.execute("echo 'test content' > /home/daytona/test/test.txt")
    result = backend.execute("cat /home/daytona/test/test.txt")
    print(f"[OK] Write file: {result.output.strip()}")
    assert "test content" in result.output
    
    # 清理
    manager.destroy_thread_backend("test-user-001-test-thread-001")
    print("[OK] Destroyed")


def test_files_sandbox():
    """测试 Files Sandbox"""
    print("\n" + "=" * 50)
    print("Test Files Sandbox...")
    print("=" * 50)
    
    manager = get_sandbox_manager()
    
    # 创建 Sandbox
    backend = manager.get_files_backend("test-user-001")
    print(f"[OK] Created: {backend.id}")
    
    # 执行命令测试
    result = backend.execute("echo 'Files Sandbox works!'")
    print(f"[OK] Execute: {result.output.strip()}")
    
    # 创建测试目录
    backend.execute("mkdir -p /home/daytona/webdav")
    
    # 上传文件
    backend.fs_upload("webdav/test.txt", b"WebDAV test content")
    print("[OK] Upload file")
    
    # 下载文件
    content = backend.fs_download("webdav/test.txt")
    print(f"[OK] Download: {content}")
    assert content == b"WebDAV test content"
    
    # 列出目录
    files = backend.fs_list("webdav")
    print(f"[OK] List dir: {len(files)} files")
    
    # 删除文件
    backend.fs_delete("webdav/test.txt")
    print("[OK] Delete file")


if __name__ == "__main__":
    print("\n" + "=" * 50)
    print("Daytona Sandbox Core Test")
    print("=" * 50 + "\n")
    
    test_agent_sandbox()
    test_files_sandbox()
    
    print("\n" + "=" * 50)
    print("[OK] All tests passed!")
    print("=" * 50)
