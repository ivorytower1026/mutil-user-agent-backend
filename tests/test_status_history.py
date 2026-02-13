import sys
from pathlib import Path
import json
import time
import threading

import requests

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import settings

BASE_URL = f"http://localhost:{settings.PORT}/api"

TEST_USER = "test-multi-turn-user"
TEST_PASSWORD = "test-password-123"

OTHER_USER = "other-multi-turn-user"
OTHER_PASSWORD = "other-password-123"


def get_token(username: str, password: str) -> str:
    """注册或登录获取token"""
    requests.post(
        f"{BASE_URL}/auth/register",
        json={"username": username, "password": password}
    )
    response = requests.post(
        f"{BASE_URL}/auth/login",
        json={"username": username, "password": password}
    )
    if response.status_code != 200:
        raise Exception(f"Login failed: {response.text}")
    return response.json().get("access_token")


def send_chat(thread_id: str, message: str, headers: dict, stream: bool = True):
    """发送消息并返回响应"""
    response = requests.post(
        f"{BASE_URL}/chat/{thread_id}",
        json={"message": message},
        headers=headers,
        stream=stream
    )
    return response


def collect_sse_events(response, max_events: int = None, interrupt_after: int = None):
    """收集SSE事件，支持中断"""
    events = []
    content_parts = []
    has_interrupt = False
    done_received = False
    
    for line in response.iter_lines():
        if line:
            line_str = line.decode().strip()
            if line_str.startswith("data: "):
                json_str = line_str[6:]
                try:
                    event = json.loads(json_str)
                    events.append(event)
                    
                    if event.get("type") == "content":
                        content_parts.append(event.get("content", ""))
                    elif event.get("type") == "interrupt":
                        has_interrupt = True
                    elif event.get("type") == "done":
                        done_received = True
                        
                    # 如果设置了中断点，且达到条件，提前关闭连接
                    if interrupt_after and len(events) >= interrupt_after:
                        response.close()
                        break
                        
                    if max_events and len(events) >= max_events:
                        break
                except json.JSONDecodeError:
                    pass
    
    return {
        "events": events,
        "content": "".join(content_parts),
        "has_interrupt": has_interrupt,
        "done_received": done_received,
        "event_count": len(events)
    }


def test_multi_turn_conversation():
    print("=" * 60)
    print("多轮对话测试")
    print("=" * 60)

    # 1. 获取token
    print("\n[1/8] 获取token...")
    token = get_token(TEST_USER, TEST_PASSWORD)
    headers = {"Authorization": f"Bearer {token}"}
    print(f"   Token: {token[:20]}...")

    # 2. 创建会话
    print("\n[2/8] 创建会话...")
    response = requests.post(f"{BASE_URL}/sessions", headers=headers)
    thread_id = response.json()["thread_id"]
    print(f"   Thread ID: {thread_id}")

    # 3. 第一轮对话
    print("\n[3/8] 第一轮对话：自我介绍...")
    response = send_chat(thread_id, "你好，我叫小明，我是一名程序员", headers)
    result1 = collect_sse_events(response)
    print(f"   事件数: {result1['event_count']}")
    print(f"   完成状态: {'done' if result1['done_received'] else 'interrupted'}")
    print(f"   回复预览: {result1['content'][:80]}...")

    # 4. 测试 /status 和 /history（第一轮后）
    print("\n[4/8] 验证第一轮对话后的状态...")
    status = requests.get(f"{BASE_URL}/status/{thread_id}", headers=headers).json()
    history = requests.get(f"{BASE_URL}/history/{thread_id}", headers=headers).json()
    print(f"   status: {status['status']}")
    print(f"   message_count: {status['message_count']}")
    print(f"   history 消息数: {len(history['messages'])}")
    assert status['message_count'] >= 2, "第一轮后应有至少2条消息"

    # 5. 第二轮对话
    print("\n[5/8] 第二轮对话：测试记忆...")
    response = send_chat(thread_id, "你还记得我叫什么名字吗？", headers)
    result2 = collect_sse_events(response)
    print(f"   事件数: {result2['event_count']}")
    print(f"   回复预览: {result2['content'][:80]}...")
    
    # 通过查询 history 来验证记忆（比 SSE 流更可靠）
    history2 = requests.get(f"{BASE_URL}/history/{thread_id}", headers=headers).json()
    last_assistant_msg = ""
    for msg in reversed(history2["messages"]):
        if msg["role"] == "assistant":
            last_assistant_msg = msg["content"]
            break
    
    if "小明" in last_assistant_msg:
        print("   [OK] Agent 记住了用户名字")
    else:
        print(f"   [WARN] Agent 可能没有记住名字，回复: {last_assistant_msg[:50]}...")

    # 6. 第三轮对话：用户主动中断
    print("\n[6/8] 第三轮对话：测试用户主动中断...")
    response = send_chat(thread_id, "请给我讲一个很长的故事", headers)
    
    # 只接收5个事件后主动中断
    result3 = collect_sse_events(response, interrupt_after=5)
    print(f"   接收事件数: {result3['event_count']}")
    print(f"   是否收到done: {result3['done_received']}")
    
    if not result3['done_received']:
        print("   [OK] SSE流被用户主动中断")
    else:
        print("   [WARN] SSE流已完成，未能测试中断场景")

    # 7. 中断后继续对话（第四轮）
    print("\n[7/8] 中断后继续对话：测试恢复能力...")
    
    # 先查询当前状态
    status_before = requests.get(f"{BASE_URL}/status/{thread_id}", headers=headers).json()
    print(f"   中断前 message_count: {status_before['message_count']}")
    
    # 发送新消息
    response = send_chat(thread_id, "不用讲故事了，请告诉我1+1等于多少？", headers)
    result4 = collect_sse_events(response)
    print(f"   事件数: {result4['event_count']}")
    print(f"   完成状态: {'done' if result4['done_received'] else 'interrupted'}")
    print(f"   回复预览: {result4['content'][:80]}...")

    # 验证状态
    status_after = requests.get(f"{BASE_URL}/status/{thread_id}", headers=headers).json()
    history_after = requests.get(f"{BASE_URL}/history/{thread_id}", headers=headers).json()
    print(f"   中断后 message_count: {status_after['message_count']}")

    # 8. 最终验证
    print("\n[8/8] 最终验证...")
    print(f"   总消息数: {len(history_after['messages'])}")
    
    print("\n   完整对话历史:")
    for i, msg in enumerate(history_after["messages"]):
        role = msg['role']
        content = msg['content'][:60] + "..." if len(msg['content']) > 60 else msg['content']
        # 过滤非ASCII字符避免编码问题
        content = content.encode('ascii', 'ignore').decode('ascii')
        print(f"   [{i+1}] {role}: {content}")

    # 权限测试
    print("\n[BONUS] 测试权限控制...")
    other_token = get_token(OTHER_USER, OTHER_PASSWORD)
    other_headers = {"Authorization": f"Bearer {other_token}"}
    
    r1 = requests.get(f"{BASE_URL}/status/{thread_id}", headers=other_headers)
    r2 = requests.get(f"{BASE_URL}/history/{thread_id}", headers=other_headers)
    
    if r1.status_code == 403 and r2.status_code == 403:
        print("   [OK] 越权访问被拒绝")
    else:
        print(f"   [ERROR] 权限验证失败: {r1.status_code}, {r2.status_code}")
        return False

    print("\n" + "=" * 60)
    print("多轮对话测试通过!")
    print("=" * 60)
    return True


def test_interrupt_and_resume():
    """测试HITL中断和恢复（如果触发了工具调用）"""
    print("\n" + "=" * 60)
    print("HITL 中断恢复测试")
    print("=" * 60)

    token = get_token("test-hitl-user", "test-hitl-password")
    headers = {"Authorization": f"Bearer {token}"}
    
    # 创建新会话
    response = requests.post(f"{BASE_URL}/sessions", headers=headers)
    thread_id = response.json()["thread_id"]
    print(f"Thread ID: {thread_id}")

    # 发送会触发工具调用的消息
    print("\n[1/3] 发送会触发文件操作的消息...")
    response = send_chat(
        thread_id, 
        "请创建一个test.txt文件，内容为Hello World", 
        headers
    )
    result = collect_sse_events(response)
    print(f"   事件数: {result['event_count']}")
    print(f"   是否触发HITL中断: {result['has_interrupt']}")

    # 查询状态
    status = requests.get(f"{BASE_URL}/status/{thread_id}", headers=headers).json()
    print(f"   当前状态: {status['status']}")
    print(f"   has_pending_tasks: {status['has_pending_tasks']}")
    
    if status['has_pending_tasks']:
        print(f"   interrupt_info: {status.get('interrupt_info')}")
        
        # 测试恢复
        print("\n[2/3] 测试 HITL 恢复...")
        response = requests.post(
            f"{BASE_URL}/resume/{thread_id}",
            json={"action": "continue"},
            headers=headers,
            stream=True
        )
        
        resume_result = collect_sse_events(response)
        print(f"   恢复后事件数: {resume_result['event_count']}")
        print(f"   完成状态: {'done' if resume_result['done_received'] else '未完成'}")
        
        # 再次查询状态
        print("\n[3/3] 恢复后状态...")
        status = requests.get(f"{BASE_URL}/status/{thread_id}", headers=headers).json()
        print(f"   状态: {status['status']}")
        print(f"   has_pending_tasks: {status['has_pending_tasks']}")
    else:
        print("\n   [INFO] 未触发HITL中断，跳过恢复测试")

    print("\n" + "=" * 60)
    print("HITL 测试完成")
    print("=" * 60)
    return True


if __name__ == "__main__":
    success1 = test_multi_turn_conversation()
    print("\n" + "-" * 60 + "\n")
    success2 = test_interrupt_and_resume()
    
    sys.exit(0 if (success1 and success2) else 1)
