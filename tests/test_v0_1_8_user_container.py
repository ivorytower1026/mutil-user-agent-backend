#!/usr/bin/env python
"""v0.1.8 用户级容器共享测试

直接测试 docker_sandbox 模块的用户级容器共享逻辑。
"""

import sys
import subprocess

sys.path.insert(0, ".")

from src.docker_sandbox import (
    get_thread_backend,
    destroy_user_backend,
    _user_backends
)


def get_container_count() -> int:
    result = subprocess.run(
        ["docker", "ps", "-q"],
        capture_output=True,
        text=True
    )
    lines = result.stdout.strip().split('\n')
    return len([l for l in lines if l])


def test_same_user_shares_backend():
    """验证：同一用户的多个 thread 共享同一个 backend 实例"""
    print("[Test 1] 同一用户多对话共享 backend 实例...")
    
    user_id = "test_user_001"
    thread1 = f"{user_id}-thread-aaa"
    thread2 = f"{user_id}-thread-bbb"
    thread3 = f"{user_id}-thread-ccc"
    
    backend1 = get_thread_backend(thread1)
    backend2 = get_thread_backend(thread2)
    backend3 = get_thread_backend(thread3)
    
    assert backend1 is backend2, "thread1 和 thread2 应该返回同一个 backend"
    assert backend2 is backend3, "thread2 和 thread3 应该返回同一个 backend"
    assert backend1.user_id == user_id, f"backend.user_id 应该是 {user_id}"
    
    print(f"  ✓ 通过: 3 个 thread 共享同一个 backend (user_id={user_id})")
    
    destroy_user_backend(user_id)
    return True


def test_different_users_different_backends():
    """验证：不同用户获得不同的 backend 实例"""
    print("[Test 2] 不同用户获得独立 backend...")
    
    user_a = "user_a_001"
    user_b = "user_b_001"
    
    thread_a = f"{user_a}-thread-xxx"
    thread_b = f"{user_b}-thread-yyy"
    
    backend_a = get_thread_backend(thread_a)
    backend_b = get_thread_backend(thread_b)
    
    assert backend_a is not backend_b, "不同用户应该返回不同的 backend"
    assert backend_a.user_id == user_a, f"backend_a.user_id 应该是 {user_a}"
    assert backend_b.user_id == user_b, f"backend_b.user_id 应该是 {user_b}"
    
    print(f"  ✓ 通过: 用户 {user_a} 和 {user_b} 使用不同 backend")
    
    destroy_user_backend(user_a)
    destroy_user_backend(user_b)
    return True


def test_cache_by_user_id():
    """验证：缓存按 user_id 存储，而非 thread_id"""
    print("[Test 3] 缓存按 user_id 存储...")
    
    initial_count = len(_user_backends)
    
    user_id = f"cache_test_user"
    thread1 = f"{user_id}-thread-111"
    thread2 = f"{user_id}-thread-222"
    
    get_thread_backend(thread1)
    count_after_t1 = len(_user_backends)
    
    get_thread_backend(thread2)
    count_after_t2 = len(_user_backends)
    
    assert count_after_t1 == initial_count + 1, f"创建 thread1 后缓存应增加 1"
    assert count_after_t2 == count_after_t1, f"创建 thread2 后缓存不应增加（共享）"
    assert user_id in _user_backends, f"user_id {user_id} 应该在缓存中"
    
    print(f"  ✓ 通过: 缓存数量 {count_after_t1}，thread2 复用了现有缓存")
    
    destroy_user_backend(user_id)
    return True


def test_destroy_user_backend():
    """验证：destroy_user_backend 正确销毁用户容器"""
    print("[Test 4] destroy_user_backend 正确工作...")
    
    user_id = f"destroy_test_user"
    thread_id = f"{user_id}-thread-abc"
    
    backend = get_thread_backend(thread_id)
    assert user_id in _user_backends, "用户应该在缓存中"
    
    result = destroy_user_backend(user_id)
    assert result == True, "destroy_user_backend 应该返回 True"
    assert user_id not in _user_backends, "用户应该从缓存中移除"
    
    result2 = destroy_user_backend(user_id)
    assert result2 == False, "重复销毁应该返回 False"
    
    print(f"  ✓ 通过: destroy_user_backend 正确清理缓存")
    return True


def main():
    print("=== v0.1.8 用户级容器共享测试 ===\n")
    
    test_same_user_shares_backend()
    test_different_users_different_backends()
    test_cache_by_user_id()
    test_destroy_user_backend()
    
    print("\n=== 所有测试通过 ===")


if __name__ == "__main__":
    main()
