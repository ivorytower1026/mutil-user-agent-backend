"""Tests for container persistence in DockerSandboxBackend."""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.docker_sandbox import get_thread_backend, destroy_thread_backend, _thread_backends


def test_container_persistence():
    """Test that container persists between execute calls."""
    thread_id = "testuser-persistence-123"
    
    try:
        backend = get_thread_backend(thread_id)
        
        result1 = backend.execute("mkdir -p /workspace/test_dir")
        assert result1.exit_code == 0, f"mkdir failed: {result1.output}"
        
        result2 = backend.execute("ls /workspace/test_dir")
        assert result2.exit_code == 0, f"ls failed: {result2.output}"
        
        result3 = backend.execute("pip install --quiet cowsay 2>/dev/null || echo 'pip install skipped'")
        assert result3.exit_code == 0, f"pip install failed: {result3.output}"
        
        result4 = backend.execute("python -c 'import sys; print(sys.version)'")
        assert result4.exit_code == 0, f"python failed: {result4.output}"
        
        print("[PASS] test_container_persistence")
        
    finally:
        destroy_thread_backend(thread_id)


def test_container_reuse():
    """Test that same thread_id reuses the same container."""
    thread_id = "testuser-reuse-456"
    
    try:
        backend = get_thread_backend(thread_id)
        
        backend.execute("echo test1")
        assert backend._container is not None, "Container should exist after first execute"
        container_id_1 = backend._container.id
        
        backend.execute("echo test2")
        container_id_2 = backend._container.id
        
        assert container_id_1 == container_id_2, "Container should be reused"
        
        print("[PASS] test_container_reuse")
        
    finally:
        destroy_thread_backend(thread_id)


def test_destroy_session():
    """Test that destroy removes container."""
    thread_id = "testuser-destroy-789"
    
    backend = get_thread_backend(thread_id)
    backend.execute("echo test")
    
    assert thread_id in _thread_backends, "Thread should be in _thread_backends"
    assert backend._container is not None, "Container should exist"
    
    destroyed = destroy_thread_backend(thread_id)
    assert destroyed is True, "destroy_thread_backend should return True"
    assert thread_id not in _thread_backends, "Thread should be removed from _thread_backends"
    assert backend._container is None, "Container reference should be None"
    
    print("[PASS] test_destroy_session")


def test_destroy_idempotent():
    """Test that destroy can be called multiple times safely."""
    thread_id = "testuser-idempotent-012"
    
    backend = get_thread_backend(thread_id)
    backend.execute("echo test")
    
    destroy_thread_backend(thread_id)
    destroyed_again = destroy_thread_backend(thread_id)
    
    assert destroyed_again is False, "Second destroy should return False"
    
    print("[PASS] test_destroy_idempotent")


def test_file_persistence():
    """Test that files persist between execute calls."""
    thread_id = "testuser-file-345"
    
    try:
        backend = get_thread_backend(thread_id)
        
        result1 = backend.execute("echo 'hello world' > /workspace/test_file.txt")
        assert result1.exit_code == 0, f"write file failed: {result1.output}"
        
        result2 = backend.execute("cat /workspace/test_file.txt")
        assert result2.exit_code == 0, f"read file failed: {result2.output}"
        assert "hello world" in result2.output, f"File content not found: {result2.output}"
        
        print("[PASS] test_file_persistence")
        
    finally:
        destroy_thread_backend(thread_id)


def test_workspace_shared():
    """Test that same user's threads share the same /workspace directory."""
    thread_id_1 = "shareduser-sharing-001"
    thread_id_2 = "shareduser-sharing-002"
    
    try:
        backend1 = get_thread_backend(thread_id_1)
        backend2 = get_thread_backend(thread_id_2)
        
        result1 = backend1.execute("echo 'shared data' > /workspace/test.txt")
        assert result1.exit_code == 0, f"write failed: {result1.output}"
        
        result2 = backend2.execute("cat /workspace/test.txt")
        assert result2.exit_code == 0, f"read failed: {result2.output}"
        assert "shared data" in result2.output, f"Shared content not found: {result2.output}"
        
        print("[PASS] test_workspace_shared")
        
    finally:
        destroy_thread_backend(thread_id_1)
        destroy_thread_backend(thread_id_2)


def test_workspace_isolation():
    """Test that different users have isolated /workspace directories."""
    thread_id_a = "userA-isolation-001"
    thread_id_b = "userB-isolation-001"
    
    try:
        backend_a = get_thread_backend(thread_id_a)
        backend_b = get_thread_backend(thread_id_b)
        
        result_a = backend_a.execute("echo 'userA secret' > /workspace/a.txt")
        assert result_a.exit_code == 0
        
        result_b = backend_b.execute("echo 'userB secret' > /workspace/b.txt")
        assert result_b.exit_code == 0
        
        result_b_read = backend_b.execute("cat /workspace/a.txt 2>&1 || echo 'FILE_NOT_FOUND'")
        assert "userA secret" not in result_b_read.output, f"userB should not see userA's file: {result_b_read.output}"
        
        result_a_read = backend_a.execute("cat /workspace/b.txt 2>&1 || echo 'FILE_NOT_FOUND'")
        assert "userB secret" not in result_a_read.output, f"userA should not see userB's file: {result_a_read.output}"
        
        print("[PASS] test_workspace_isolation")
        
    finally:
        destroy_thread_backend(thread_id_a)
        destroy_thread_backend(thread_id_b)


if __name__ == "__main__":
    print("=" * 50)
    print("Running container persistence tests...")
    print("=" * 50)
    
    test_container_persistence()
    test_container_reuse()
    test_destroy_session()
    test_destroy_idempotent()
    test_file_persistence()
    test_workspace_shared()
    test_workspace_isolation()
    
    print("=" * 50)
    print("All tests passed!")
    print("=" * 50)
