import sys
from pathlib import Path
import json
from collections import Counter

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.config import settings
import requests

BASE_URL = f"http://localhost:{settings.PORT}/api"
TEST_USER_ID = "test-user"
TEST_PASSWORD = "test-password-123"


def test_resume_debug():
    print("=" * 50)
    print("Resume Debug Test")
    print("=" * 50)

    # 0. Login
    print("\n0. Login...")
    login_response = requests.post(
        f"{BASE_URL}/auth/login",
        json={"username": TEST_USER_ID, "password": TEST_PASSWORD}
    )
    if login_response.status_code != 200:
        print(f"   [Error] Login failed: {login_response.text}")
        return
    token = login_response.json().get("access_token")
    print(f"   Access token: {token[:20]}...")

    # 1. Create session
    print("\n1. Create session...")
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.post(f"{BASE_URL}/sessions", headers=headers)
    session = response.json()
    thread_id = session["thread_id"]
    print(f"   Thread ID: {thread_id}")

    # 2. Send message (should trigger interrupt)
    print("\n2. Send message: create hello.py...")
    response = requests.post(
        f"{BASE_URL}/chat/{thread_id}",
        json={"message": "创建一个hello.py文件，内容为：print('Hello World')"},
        headers=headers,
        stream=True
    )

    print("   Chat response:")
    event_count = Counter()
    has_interrupt = False

    for line in response.iter_lines():
        if line:
            line_str = line.decode().strip()
            if line_str.startswith("data: "):
                json_str = line_str[6:]
                try:
                    event = json.loads(json_str)
                    event_type = event.get("type", "unknown")
                    event_count[event_type] += 1

                    if event_type == "interrupt":
                        has_interrupt = True
                        print(f"   >>> HITL TRIGGERED!")
                    elif event_type == "done":
                        print(f"   >>> Chat done")
                except json.JSONDecodeError as e:
                    print(f"   [Error] Failed to parse: {json_str}")

    print(f"\n   Chat event count:")
    for etype, count in event_count.most_common():
        print(f"      {etype}: {count}")

    # 3. Resume (only if interrupt was triggered)
    print(f"\n3. Resume (has_interrupt={has_interrupt})...")
    response = requests.post(
        f"{BASE_URL}/resume/{thread_id}",
        json={"action": "continue"},
        headers=headers,
        stream=True
    )

    print("   Resume response (raw):")
    resume_event_count = Counter()
    raw_lines = []
    for line in response.iter_lines():
        if line:
            line_str = line.decode().strip()
            raw_lines.append(line_str)
            if line_str.startswith("data: "):
                json_str = line_str[6:]
                try:
                    event = json.loads(json_str)
                    event_type = event.get("type", "unknown")
                    resume_event_count[event_type] += 1
                    print(f"   [{event_type}] {event}")
                except json.JSONDecodeError as e:
                    print(f"   [Error] Failed to parse: {json_str}")

    print(f"\n   Resume event count:")
    for etype, count in resume_event_count.most_common():
        print(f"      {etype}: {count}")

    print(f"\n   Total raw lines: {len(raw_lines)}")
    print(f"   First 5 lines: {raw_lines[:5]}")

    # 4. Check workspace
    print("\n4. Check workspace...")
    workspace_root = Path(settings.WORKSPACE_ROOT)
    file_path = workspace_root / thread_id / "hello.py"

    if file_path.exists():
        print(f"   [OK] File created: {file_path}")
        with open(file_path) as f:
            content = f.read()
            print(f"   Content:\n{content}")
    else:
        print(f"   [X] File not found: {file_path}")

    print("\n" + "=" * 50)
    print("Test Complete")
    print("=" * 50)


if __name__ == "__main__":
    test_resume_debug()
