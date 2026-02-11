import os
import time
import requests
from pathlib import Path

BASE_URL = "http://localhost:8002/api"


def test_mvp():
    print("=" * 50)
    print("MVP测试脚本")
    print("=" * 50)

    # 1. 创建会话
    print("\n1. 创建会话...")
    response = requests.post(f"{BASE_URL}/sessions")
    session = response.json()
    thread_id = session["thread_id"]
    print(f"   Thread ID: {thread_id}")

    # 2. 发送消息（SSE流）
    print("\n2. 发送消息：创建hello.py文件...")
    response = requests.post(
        f"{BASE_URL}/chat/{thread_id}",
        json={"message": "创建一个hello.py文件，内容为：print('Hello World')"},
        stream=True
    )

    print("   响应流：")
    for line in response.iter_lines():
        if line:
            print(f"   {line.decode()}")



    # 3. 测试resume功能（如果HITL触发）
    print("\n3. 测试resume功能...")
    response = requests.post(
        f"{BASE_URL}/resume/{thread_id}",
        json={"action": "continue"}
    )
    print(f"   响应: {response.json()}")

    # 4. 检查工作空间
    print("\n4. 检查工作空间...")
    workspace_root = os.getenv("WORKSPACE_ROOT", "./workspaces")
    workspace_root = Path(workspace_root).expanduser().absolute()
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
