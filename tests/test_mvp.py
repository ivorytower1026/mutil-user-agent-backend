import sys
from pathlib import Path
import json
from collections import Counter

import requests

# 添加项目根目录到Python路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import settings
import requests.auth

BASE_URL = "http://localhost:8002/api"

# 简单认证 - 使用固定的用户ID和密码
TEST_USER_ID = "test-user"
TEST_PASSWORD = "test-password-123"


def test_mvp():
    print("=" * 50)
    print("MVP测试脚本")
    print("=" * 50)

    # 0. 注册或登录获取token
    print("\n0. 注册或登录获取token...")
    register_response = requests.post(
        f"{BASE_URL}/auth/register",
        json={"username": TEST_USER_ID, "password": TEST_PASSWORD}
    )
    if register_response.status_code == 200:
        print(f"   [Register] User registered: {TEST_USER_ID}")
    elif register_response.status_code == 400 and "already registered" in register_response.text.lower():
        print(f"   [Info] User already exists, trying login...")
    else:
        print(f"   [Error] Register failed: {register_response.text}")

    login_response = requests.post(
        f"{BASE_URL}/auth/login",
        json={"username": TEST_USER_ID, "password": TEST_PASSWORD}
    )
    if login_response.status_code != 200:
        print(f"   [Error] Login failed: {login_response.text}")
        return
    token = login_response.json().get("access_token")
    print(f"   Access token: {token[:20]}...")

    # 1. 创建会话
    print("\n1. 创建会话...")
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.post(f"{BASE_URL}/sessions", headers=headers)
    if response.status_code == 401:
        print(f"   [Error] Authentication failed: {response.text}")
        return
    session = response.json()
    thread_id = session["thread_id"]
    print(f"   Thread ID: {thread_id}")

    # 2. 发送消息（SSE流）
    print("\n2. 发送消息：创建hello.py文件...")
    response = requests.post(
        f"{BASE_URL}/chat/{thread_id}",
        json={"message": "创建一个hello.py文件，内容为：print('Hello World')"},
        headers=headers,
        stream=True
    )

    print("   响应流：")
    event_count = Counter()
    content_chunks = []
    tool_calls = []

    for line in response.iter_lines():
        if line:
            line_str = line.decode().strip()
            if line_str.startswith("data: "):
                json_str = line_str[6:]
                try:
                    event = json.loads(json_str)
                    event_type = event.get("type", "unknown")
                    event_count[event_type] += 1

                    if event_type == "content":
                        content = event.get("content", "")
                        content_chunks.append(content)
                        if len(content) < 100:
                            print(f"   [Content] {content}")
                        else:
                            print(f"   [Content] {content[:100]}...")
                    elif event_type == "tool_start":
                        tool = event.get("tool", "unknown")
                        tool_input = event.get("input", {})
                        tool_calls.append(tool)
                        print(f"   [Tool Start] {tool}")
                        if isinstance(tool_input, dict) and len(tool_input) > 0:
                            print(f"      Input keys: {list(tool_input.keys())}")
                    elif event_type == "tool_end":
                        tool = event.get("tool", "unknown")
                        print(f"   [Tool End] {tool}")
                    elif event_type == "structured":
                        print(f"   [Structured] {event.get('data', {})}")
                    else:
                        print(f"   [{event_type}] {event}")
                except json.JSONDecodeError as e:
                    print(f"   [Error] Failed to parse: {json_str}")

    print(f"\n   事件统计:")
    for event_type, count in event_count.most_common():
        print(f"      {event_type}: {count}")
    print(f"   Content chunks: {len(content_chunks)}")
    print(f"   Tool calls: {len(tool_calls)}")


    
    # 3. 测试resume功能（如果HITL触发）- 流式输出
    print("\n3. 测试流式resume功能...")
    response = requests.post(
        f"{BASE_URL}/resume/{thread_id}",
        json={"action": "continue"},
        headers=headers,
        stream=True
    )
    
    print("   响应流:")
    resume_event_count = Counter()
    for line in response.iter_lines():
        if line:
            line_str = line.decode().strip()
            if line_str.startswith("data: "):
                json_str = line_str[6:]
                try:
                    event = json.loads(json_str)
                    event_type = event.get("type", "unknown")
                    resume_event_count[event_type] += 1
                    
                    if event_type == "content":
                        content = event.get("content", "")
                        if len(content) < 100:
                            print(f"   [{event_type}] {content}")
                        else:
                            print(f"   [{event_type}] {content[:100]}...")
                    elif event_type == "tool_start":
                        tool = event.get("tool", "unknown")
                        print(f"   [{event_type}] {tool}")
                    elif event_type == "tool_end":
                        tool = event.get("tool", "unknown")
                        print(f"   [{event_type}] {tool}")
                    elif event_type == "interrupt":
                        info = event.get("info", "")
                        print(f"   [{event_type}] {info}")
                    elif event_type == "update":
                        print(f"   [{event_type}] {event.get('data', {})}")
                    elif event_type == "done":
                        action = event.get("action", "")
                        print(f"   >>> Resume completed ({action})")
                        break
                except json.JSONDecodeError:
                    pass
    
    print(f"\n   Resume 事件统计:")
    for etype, count in resume_event_count.most_common():
        print(f"      {etype}: {count}")

    # 4. 检查工作空间
    print("\n4. 检查工作空间...")
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
    print("测试完成")
    print("=" * 50)


if __name__ == "__main__":
    test_mvp()
