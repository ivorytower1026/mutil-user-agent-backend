"""Integration tests for WebDAV and chunk upload functionality."""
import os
import sys
import time
import json
import subprocess
import requests

BASE_URL = "http://localhost:8002"
TEST_USER = "webdav_test_user"
TEST_PASSWORD = "test_password_123"


def start_server():
    """Start the FastAPI server."""
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8002"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )
    time.sleep(3)
    return process


def stop_server(process):
    """Stop the FastAPI server."""
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()


def get_token():
    """Register and login to get JWT token."""
    requests.post(f"{BASE_URL}/api/auth/register", json={
        "username": TEST_USER,
        "password": TEST_PASSWORD
    })
    
    response = requests.post(f"{BASE_URL}/api/auth/login", data={
        "username": TEST_USER,
        "password": TEST_PASSWORD
    })
    
    if response.status_code == 200:
        return response.json()["access_token"]
    raise Exception(f"Login failed: {response.text}")


def test_webdav_propfind():
    """Test PROPFIND - list directory."""
    print("[1/8] Test PROPFIND...")
    token = get_token()
    headers = {"Authorization": f"Bearer {token}"}
    
    response = requests.request(
        "PROPFIND",
        f"{BASE_URL}/dav/",
        headers={**headers, "Depth": "1"}
    )
    
    assert response.status_code == 207, f"Expected 207, got {response.status_code}"
    assert "multistatus" in response.text.lower(), "Response should contain multistatus"
    print("  [PASS] PROPFIND returns 207 Multi-Status")
    return True


def test_webdav_mkcol():
    """Test MKCOL - create directory."""
    print("[2/8] Test MKCOL...")
    token = get_token()
    headers = {"Authorization": f"Bearer {token}"}
    
    response = requests.request(
        "MKCOL",
        f"{BASE_URL}/dav/test_dir",
        headers=headers
    )
    
    assert response.status_code == 201, f"Expected 201, got {response.status_code}"
    print("  [PASS] MKCOL creates directory")
    
    response = requests.request(
        "PROPFIND",
        f"{BASE_URL}/dav/test_dir",
        headers={**headers, "Depth": "0"}
    )
    assert response.status_code == 207, f"Directory should exist"
    print("  [PASS] Created directory exists")
    return True


def test_webdav_put_get():
    """Test PUT and GET - upload and download file."""
    print("[3/8] Test PUT/GET...")
    token = get_token()
    headers = {"Authorization": f"Bearer {token}"}
    
    test_content = b"Hello WebDAV! This is a test file."
    
    response = requests.put(
        f"{BASE_URL}/dav/test_dir/test_file.txt",
        headers=headers,
        data=test_content
    )
    
    assert response.status_code == 201, f"Expected 201, got {response.status_code}"
    assert "ETag" in response.headers, "Response should include ETag"
    etag = response.headers["ETag"]
    print(f"  [PASS] PUT creates file with ETag: {etag}")
    
    response = requests.get(
        f"{BASE_URL}/dav/test_dir/test_file.txt",
        headers=headers
    )
    
    assert response.status_code == 200, f"Expected 200, got {response.status_code}"
    assert response.content == test_content, "Content mismatch"
    print("  [PASS] GET returns correct content")
    return True, etag


def test_webdav_etag_conflict():
    """Test ETag conflict detection."""
    print("[4/8] Test ETag conflict...")
    token = get_token()
    headers = {"Authorization": f"Bearer {token}"}
    
    test_content = b"Original content"
    response = requests.put(
        f"{BASE_URL}/dav/test_dir/conflict_test.txt",
        headers=headers,
        data=test_content
    )
    etag = response.headers["ETag"]
    
    wrong_etag = '"wrong-etag-12345"'
    response = requests.put(
        f"{BASE_URL}/dav/test_dir/conflict_test.txt",
        headers={**headers, "If-Match": wrong_etag},
        data=b"New content"
    )
    
    assert response.status_code == 409, f"Expected 409 conflict, got {response.status_code}"
    print("  [PASS] PUT with wrong ETag returns 409 Conflict")
    
    response = requests.put(
        f"{BASE_URL}/dav/test_dir/conflict_test.txt",
        headers={**headers, "If-Match": etag},
        data=b"Updated content"
    )
    assert response.status_code == 201, f"Expected 201 with correct ETag, got {response.status_code}"
    print("  [PASS] PUT with correct ETag succeeds")
    return True


def test_webdav_move():
    """Test MOVE - rename/move file."""
    print("[5/8] Test MOVE...")
    token = get_token()
    headers = {"Authorization": f"Bearer {token}"}
    
    requests.put(
        f"{BASE_URL}/dav/test_dir/original.txt",
        headers=headers,
        data=b"File to rename"
    )
    
    response = requests.request(
        "MOVE",
        f"{BASE_URL}/dav/test_dir/original.txt",
        headers={**headers, "Destination": "/dav/test_dir/renamed.txt"}
    )
    
    assert response.status_code == 201, f"Expected 201, got {response.status_code}"
    print("  [PASS] MOVE renames file")
    
    response = requests.get(
        f"{BASE_URL}/dav/test_dir/renamed.txt",
        headers=headers
    )
    assert response.status_code == 200, "Renamed file should exist"
    print("  [PASS] Renamed file accessible")
    return True


def test_webdav_delete():
    """Test DELETE - remove file and directory."""
    print("[6/8] Test DELETE...")
    token = get_token()
    headers = {"Authorization": f"Bearer {token}"}
    
    requests.put(
        f"{BASE_URL}/dav/test_dir/to_delete.txt",
        headers=headers,
        data=b"Delete me"
    )
    
    response = requests.delete(
        f"{BASE_URL}/dav/test_dir/to_delete.txt",
        headers=headers
    )
    
    assert response.status_code == 204, f"Expected 204, got {response.status_code}"
    print("  [PASS] DELETE removes file")
    
    response = requests.get(
        f"{BASE_URL}/dav/test_dir/to_delete.txt",
        headers=headers
    )
    assert response.status_code == 404, "Deleted file should not exist"
    print("  [PASS] Deleted file returns 404")
    return True


def test_chunk_upload():
    """Test chunk upload - init, upload, complete."""
    print("[7/8] Test chunk upload...")
    token = get_token()
    headers = {"Authorization": f"Bearer {token}"}
    
    init_response = requests.post(
        f"{BASE_URL}/api/files/init-upload",
        headers={**headers, "Content-Type": "application/json"},
        json={
            "filename": "large_file.bin",
            "total_chunks": 3,
            "total_size": 30,
            "target_path": "test_dir/large_file.bin"
        }
    )
    
    assert init_response.status_code == 200, f"Init failed: {init_response.text}"
    upload_id = init_response.json()["upload_id"]
    chunk_size = init_response.json()["chunk_size"]
    print(f"  [PASS] Init upload: upload_id={upload_id}, chunk_size={chunk_size}")
    
    for i in range(3):
        chunk_data = bytes([i] * 10)
        files = {"chunk": (f"chunk_{i}", chunk_data, "application/octet-stream")}
        response = requests.post(
            f"{BASE_URL}/api/files/upload-chunk",
            headers=headers,
            files=files,
            data={"upload_id": upload_id, "chunk_index": i}
        )
        assert response.status_code == 200, f"Chunk {i} upload failed: {response.text}"
    print("  [PASS] All chunks uploaded")
    
    complete_response = requests.post(
        f"{BASE_URL}/api/files/complete-upload",
        headers={**headers, "Content-Type": "application/json"},
        json={
            "upload_id": upload_id,
            "target_path": "test_dir/large_file.bin"
        }
    )
    
    assert complete_response.status_code == 200, f"Complete failed: {complete_response.text}"
    print("  [PASS] Upload completed and merged")
    
    response = requests.get(
        f"{BASE_URL}/dav/test_dir/large_file.bin",
        headers=headers
    )
    assert response.status_code == 200, "Merged file should exist"
    assert len(response.content) == 30, f"Expected 30 bytes, got {len(response.content)}"
    print("  [PASS] Merged file has correct size")
    return True


def test_path_traversal_protection():
    """Test path traversal attack protection."""
    print("[8/8] Test path traversal protection...")
    token = get_token()
    headers = {"Authorization": f"Bearer {token}"}
    
    response = requests.put(
        f"{BASE_URL}/dav/../escape_attempt.txt",
        headers=headers,
        data=b"Should not work"
    )
    
    assert response.status_code == 403, f"Expected 403, got {response.status_code}"
    print("  [PASS] Path traversal blocked")
    return True


def cleanup():
    """Clean up test data by destroying Daytona sandbox."""
    print("\n[CLEANUP] Destroying test sandbox...")
    try:
        from src.daytona_sandbox_manager import get_sandbox_manager
        manager = get_sandbox_manager()
        if TEST_USER in manager._files_sandboxes:
            manager._files_sandboxes[TEST_USER].destroy()
            del manager._files_sandboxes[TEST_USER]
            print(f"  Destroyed sandbox for {TEST_USER}")
    except Exception as e:
        print(f"  Cleanup warning: {e}")


def main():
    """Run all tests."""
    print("=" * 60)
    print("WebDAV & Chunk Upload Integration Tests")
    print("=" * 60)
    
    server_process = None
    try:
        print("\n[STARTUP] Starting server...")
        server_process = start_server()
        
        print(f"[STARTUP] Server started at {BASE_URL}\n")
        
        tests = [
            test_webdav_propfind,
            test_webdav_mkcol,
            test_webdav_put_get,
            test_webdav_etag_conflict,
            test_webdav_move,
            test_webdav_delete,
            test_chunk_upload,
            test_path_traversal_protection,
        ]
        
        passed = 0
        failed = 0
        
        for test in tests:
            try:
                result = test()
                if result:
                    passed += 1
            except Exception as e:
                print(f"  [FAIL] {e}")
                failed += 1
        
        print("\n" + "=" * 60)
        print(f"Results: {passed} passed, {failed} failed")
        print("=" * 60)
        
        cleanup()
        
        return failed == 0
        
    finally:
        if server_process:
            print("\n[SHUTDOWN] Stopping server...")
            stop_server(server_process)


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
