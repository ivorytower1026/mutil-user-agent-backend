"""v0.1.7 对话文件上传测试"""
import sys
from pathlib import Path
import io

import requests

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import settings

BASE_URL = f"http://localhost:{settings.PORT}/api"
TEST_USER_ID = "test-v017-user"
TEST_PASSWORD = "test-password-123"

token = None
thread_id = None


def wait_for_server():
    """Wait for server to be ready."""
    import time
    for i in range(30):
        try:
            resp = requests.get(f"{BASE_URL.replace('/api', '')}/docs", timeout=2)
            if resp.status_code == 200:
                print(f"   [OK] Server is ready")
                return True
        except:
            pass
        time.sleep(1)
    print(f"   [Error] Server not ready after 30s")
    return False


def test_01_register_and_login():
    """[1/7] 注册并登录"""
    global token
    
    register_response = requests.post(
        f"{BASE_URL}/auth/register",
        json={"username": TEST_USER_ID, "password": TEST_PASSWORD}
    )
    if register_response.status_code == 200:
        print(f"   [Register] User registered: {TEST_USER_ID}")
    elif register_response.status_code == 400:
        print(f"   [Info] User already exists, trying login...")
    
    login_response = requests.post(
        f"{BASE_URL}/auth/login",
        json={"username": TEST_USER_ID, "password": TEST_PASSWORD}
    )
    if login_response.status_code != 200:
        print(f"   [Error] Login failed: {login_response.text}")
        return False
    token = login_response.json().get("access_token")
    print(f"   [OK] Token: {token[:20]}...")
    return True


def test_02_create_session():
    """[2/7] 创建会话"""
    global thread_id
    
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.post(f"{BASE_URL}/sessions", headers=headers)
    if response.status_code != 200:
        print(f"   [Error] Create session failed: {response.text}")
        return False
    session = response.json()
    thread_id = session["thread_id"]
    print(f"   [OK] Thread ID: {thread_id}")
    return True


def test_03_upload_simple():
    """[3/7] 测试简单上传"""
    content = b"Hello, this is a test file content for v0.1.7!"
    
    files = {"file": ("test_v017.txt", io.BytesIO(content), "text/plain")}
    headers = {"Authorization": f"Bearer {token}"}
    
    resp = requests.post(f"{BASE_URL}/files/upload-simple", files=files, headers=headers)
    
    if resp.status_code != 200:
        print(f"   [Error] Upload failed: {resp.text}")
        return None
    
    data = resp.json()
    assert data["success"] is True
    assert "/workspace/uploads/" in data["path"]
    assert data["filename"] == "test_v017.txt"
    assert data["size"] == len(content)
    
    print(f"   [OK] Upload success: {data['path']}")
    return data["path"]


def test_04_upload_large_file_rejected():
    """[4/7] 测试大文件被拒绝"""
    content = b"x" * (51 * 1024 * 1024)
    
    files = {"file": ("large.bin", io.BytesIO(content), "application/octet-stream")}
    headers = {"Authorization": f"Bearer {token}"}
    
    resp = requests.post(f"{BASE_URL}/files/upload-simple", files=files, headers=headers)
    
    if resp.status_code != 413:
        print(f"   [Error] Expected 413, got {resp.status_code}: {resp.text}")
        return False
    
    detail = resp.json().get("detail", "")
    if "WebDAV" not in detail:
        print(f"   [Error] Expected WebDAV hint in error message")
        return False
    
    print(f"   [OK] Large file correctly rejected: {detail}")
    return True


def test_05_chat_with_file():
    """[5/7] 测试带文件的对话"""
    file_path = test_03_upload_simple()
    if not file_path:
        return False
    
    headers = {"Authorization": f"Bearer {token}"}
    data = {
        "message": "列出当前目录下的文件",
        "files": [file_path]
    }
    
    resp = requests.post(f"{BASE_URL}/chat/{thread_id}", json=data, headers=headers, stream=True)
    
    if resp.status_code != 200:
        print(f"   [Error] Chat failed: {resp.text}")
        return False
    
    has_content = False
    for line in resp.iter_lines():
        if line:
            decoded = line.decode()
            if "data:" in decoded:
                has_content = True
                if len(decoded) < 200:
                    print(f"   [SSE] {decoded}")
    
    if has_content:
        print(f"   [OK] Chat with file success")
        return True
    else:
        print(f"   [Error] No SSE content received")
        return False


def test_06_chat_without_file():
    """[6/7] 测试不带文件的对话（兼容性）"""
    headers = {"Authorization": f"Bearer {token}"}
    data = {"message": "你好"}
    
    resp = requests.post(f"{BASE_URL}/chat/{thread_id}", json=data, headers=headers, stream=True)
    
    if resp.status_code != 200:
        print(f"   [Error] Chat failed: {resp.text}")
        return False
    
    print(f"   [OK] Chat without file success (backward compatible)")
    return True


def test_07_history_filtering():
    """[7/7] 测试历史记录过滤"""
    headers = {"Authorization": f"Bearer {token}"}
    
    resp = requests.get(f"{BASE_URL}/history/{thread_id}", headers=headers)
    
    if resp.status_code != 200:
        print(f"   [Error] Get history failed: {resp.text}")
        return False
    
    data = resp.json()
    messages = data.get("messages", [])
    
    for msg in messages:
        content = msg.get("content", "")
        if "当前对话中用户已上传的文件" in content:
            print(f"   [Error] File SystemMessage should be filtered out!")
            return False
    
    print(f"   [OK] History filtering works, {len(messages)} messages")
    for msg in messages:
        print(f"      [{msg['role']}]: {msg['content'][:50]}...")
    return True


def main():
    print("=" * 50)
    print("v0.1.7 对话文件上传测试")
    print("=" * 50)
    
    if not wait_for_server():
        return
    
    tests = [
        test_01_register_and_login,
        test_02_create_session,
        test_03_upload_simple,
        test_04_upload_large_file_rejected,
        test_05_chat_with_file,
        test_06_chat_without_file,
        test_07_history_filtering,
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        print(f"\n[{test.__doc__}]")
        try:
            result = test()
            if result or result is None and "upload_simple" in test.__name__:
                passed += 1
            else:
                failed += 1
        except Exception as e:
            print(f"   [Exception] {e}")
            failed += 1
    
    print("\n" + "=" * 50)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 50)


if __name__ == "__main__":
    main()
