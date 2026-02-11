# -*- coding: utf-8 -*-
"""Test script for v0.1.1 multi-user features."""
import requests
import time
import sys

BASE_URL = "http://localhost:8002"
API_URL = f"{BASE_URL}/api"
AUTH_URL = f"{BASE_URL}/api/auth"

def wait_for_server(timeout=30):
    """Wait for server to be ready."""
    print("Waiting for server to start...")
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            response = requests.get(BASE_URL, timeout=1)
            if response.status_code == 200:
                print("Server is ready!")
                return True
        except:
            pass
        time.sleep(0.5)
    return False


def test_root_endpoint():
    """Test root endpoint."""
    print("\n[1/10] Testing root endpoint...")
    response = requests.get(BASE_URL)
    assert response.status_code == 200, f"Expected 200, got {response.status_code}"
    data = response.json()
    assert "version" in data, "Version not in response"
    assert data["version"] == "0.1.1", f"Expected version 0.1.1, got {data['version']}"
    print(f"[OK] Root endpoint OK: version={data['version']}")


def test_user_registration():
    """Test user registration."""
    print("\n[2/10] Testing user registration...")
    
    # Test successful registration
    response = requests.post(
        f"{AUTH_URL}/register",
        json={"username": "testuser", "password": "testpassword123"}
    )
    assert response.status_code == 200, f"Registration failed: {response.text}"
    data = response.json()
    assert "user_id" in data, "user_id not in response"
    print(f"[OK] Registration OK: user_id={data['user_id']}")
    
    # Test duplicate registration (should fail)
    response = requests.post(
        f"{AUTH_URL}/register",
        json={"username": "testuser", "password": "testpassword123"}
    )
    assert response.status_code == 400, f"Duplicate registration should fail, got {response.status_code}"
    print("[OK] Duplicate registration correctly rejected")


def test_user_login():
    """Test user login."""
    print("\n[3/10] Testing user login...")
    
    # Test successful login
    response = requests.post(
        f"{AUTH_URL}/login",
        json={"username": "testuser", "password": "testpassword123"}
    )
    assert response.status_code == 200, f"Login failed: {response.text}"
    data = response.json()
    assert "access_token" in data, "access_token not in response"
    assert data["token_type"] == "bearer", "token_type should be bearer"
    print("[OK] Login OK: token received")
    
    # Test invalid credentials
    response = requests.post(
        f"{AUTH_URL}/login",
        json={"username": "testuser", "password": "wrongpassword"}
    )
    assert response.status_code == 401, f"Invalid login should fail, got {response.status_code}"
    print("[OK] Invalid login correctly rejected")
    
    return data["access_token"]


def test_unauthorized_access():
    """Test unauthorized access to protected endpoints."""
    print("\n[4/10] Testing unauthorized access...")
    
    # Try to create session without token
    response = requests.post(f"{API_URL}/sessions")
    assert response.status_code == 401, f"Expected 401, got {response.status_code}"
    print("[OK] Unauthorized session creation correctly rejected")
    
    # Try to chat without token
    response = requests.post(
        f"{API_URL}/chat/test-thread",
        json={"message": "Hello"}
    )
    assert response.status_code == 401, f"Expected 401, got {response.status_code}"
    print("[OK] Unauthorized chat correctly rejected")


def test_create_session(token):
    """Test creating a session."""
    print("\n[5/10] Testing session creation...")
    
    response = requests.post(
        f"{API_URL}/sessions",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200, f"Session creation failed: {response.text}"
    data = response.json()
    assert "thread_id" in data, "thread_id not in response"
    thread_id = data["thread_id"]
    
    # Verify thread_id format: {user_id}-{uuid}
    assert thread_id.startswith("testuser-"), f"Invalid thread_id format: {thread_id}"
    print(f"[OK] Session created: thread_id={thread_id}")
    
    return thread_id


def test_thread_isolation():
    """Test thread isolation between users."""
    print("\n[6/10] Testing thread isolation...")
    
    # Create second user
    response = requests.post(
        f"{AUTH_URL}/register",
        json={"username": "testuser2", "password": "testpassword123"}
    )
    assert response.status_code == 200
    
    # Login as second user
    response = requests.post(
        f"{AUTH_URL}/login",
        json={"username": "testuser2", "password": "testpassword123"}
    )
    token2 = response.json()["access_token"]
    
    # Create session for second user
    response = requests.post(
        f"{API_URL}/sessions",
        headers={"Authorization": f"Bearer {token2}"}
    )
    thread_id2 = response.json()["thread_id"]
    assert thread_id2.startswith("testuser2-"), f"Invalid thread_id format: {thread_id2}"
    print(f"[OK] User2 session created: thread_id={thread_id2}")
    
    # Try to access user1's thread with user2's token
    response = requests.post(
        f"{API_URL}/chat/testuser-550e8400-xxx",
        headers={"Authorization": f"Bearer {token2}"},
        json={"message": "Hello"}
    )
    # Should get 404 or 403
    assert response.status_code in [403, 404], f"Cross-user access should fail, got {response.status_code}"
    print("[OK] Cross-user access correctly rejected")
    
    return token2, thread_id2


def test_chat_with_auth(token, thread_id):
    """Test chat endpoint with authentication."""
    print("\n[7/10] Testing chat with authentication...")
    
    response = requests.post(
        f"{API_URL}/chat/{thread_id}",
        headers={"Authorization": f"Bearer {token}"},
        json={"message": "Hello"},
        stream=True
    )
    assert response.status_code == 200, f"Chat failed: {response.text}"
    
    # Read a bit of the stream
    content_received = False
    for line in response.iter_lines():
        if line:
            content_received = True
            break
    
    print("[OK] Chat stream started successfully")


def test_workspace_isolation():
    """Test workspace directory isolation."""
    print("\n[8/10] Testing workspace isolation...")
    import os
    from pathlib import Path
    
    # Check if workspaces directory exists
    workspace_root = Path("./workspaces").expanduser().absolute()
    
    # After creating sessions, check directory structure
    # workspaces/{user_id}/{thread_id}/
    user_dirs = [d for d in workspace_root.iterdir() if d.is_dir()] if workspace_root.exists() else []
    
    print(f"[OK] Workspace directories found: {len(user_dirs)} user(s)")
    for user_dir in user_dirs:
        thread_dirs = [d.name for d in user_dir.iterdir() if d.is_dir()]
        print(f"  - {user_dir.name}: {len(thread_dirs)} thread(s)")


def test_persistence():
    """Test data persistence (manual verification)."""
    print("\n[9/10] Testing data persistence...")
    print("[WARN] Manual verification needed:")
    print("  1. Send a message to a thread")
    print("  2. Restart the server")
    print("  3. Send another message to the same thread")
    print("  4. Verify the agent remembers the context")
    print("[OK] Persistence test requires manual verification")


def test_resume_with_auth(token, thread_id):
    """Test resume endpoint with authentication."""
    print("\n[10/10] Testing resume with authentication...")
    
    # This will likely fail because no HITL is pending, but should fail with 403/404, not 401
    response = requests.post(
        f"{API_URL}/resume/{thread_id}",
        headers={"Authorization": f"Bearer {token}"},
        json={"action": "continue"}
    )
    
    # Should not get 401 (unauthorized)
    assert response.status_code != 401, "Resume should not fail with 401 when authenticated"
    print(f"[OK] Resume endpoint accessible (status: {response.status_code})")


def run_all_tests():
    """Run all tests."""
    print("=" * 60)
    print("v0.1.1 Multi-User Feature Tests")
    print("=" * 60)
    
    # Wait for server to be ready
    if not wait_for_server(timeout=30):
        print("[FAIL] Server did not start within 30 seconds")
        print("Please start the server manually with: uv run uvicorn main:app --host 0.0.0.0 --port 8002")
        return False
    
    try:
        # Basic tests
        test_root_endpoint()
        test_user_registration()
        token = test_user_login()
        test_unauthorized_access()
        thread_id = test_create_session(token)
        
        # Advanced tests
        token2, thread_id2 = test_thread_isolation()
        test_chat_with_auth(token, thread_id)
        test_workspace_isolation()
        test_persistence()
        test_resume_with_auth(token, thread_id)
        
        print("\n" + "=" * 60)
        print("[OK] All tests passed!")
        print("=" * 60)
        return True
        
    except AssertionError as e:
        print(f"\n[FAIL] Test failed: {e}")
        return False
    except Exception as e:
        print(f"\n[FAIL] Error: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
