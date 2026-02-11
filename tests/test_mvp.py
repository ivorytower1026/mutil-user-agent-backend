import sys
from pathlib import Path
import json
from collections import Counter

import requests

# 添加项目根目录到Python路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import settings

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



    # 3. 测试resume功能（如果HITL触发）
    print("\n3. 测试resume功能...")
    response = requests.post(
        f"{BASE_URL}/resume/{thread_id}",
        json={"action": "continue"}
    )
    print(f"   响应: {response.json()}")

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
