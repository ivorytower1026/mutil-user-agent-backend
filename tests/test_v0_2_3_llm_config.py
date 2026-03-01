"""
v0.2.3 LLM动态配置 API 测试

测试内容:
- LLM配置CRUD (/api/admin/llm/configs)
- 配置激活/停用
- 连接测试
- 权限验证

运行方式:
1. 启动服务: uv run python main.py
2. 运行测试: uv run python tests/test_v0_2_3_llm_config.py
"""

import os
import sys
import time
import uuid
import requests

BASE_URL = os.environ.get("TEST_BASE_URL", "http://localhost:8005")
ADMIN_USER = f"v023_admin_{uuid.uuid4().hex[:8]}"
ADMIN_PASSWORD = "admin_password_123"
NORMAL_USER = f"v023_normal_{uuid.uuid4().hex[:8]}"
NORMAL_PASSWORD = "normal_password_123"

_admin_token = None
_normal_token = None
_created_config_ids = []


def wait_for_server(timeout: int = 30) -> bool:
    for _ in range(timeout):
        try:
            resp = requests.get(f"{BASE_URL}/", timeout=2)
            if resp.status_code == 200:
                return True
        except requests.exceptions.RequestException:
            pass
        time.sleep(1)
    return False


def register_and_login(username: str, password: str) -> str:
    try:
        requests.post(
            f"{BASE_URL}/api/auth/register",
            json={"username": username, "password": password},
            timeout=10,
        )
    except requests.exceptions.RequestException:
        pass

    resp = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"username": username, "password": password},
        timeout=10,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Login failed: {resp.status_code} {resp.text}")
    return resp.json()["access_token"]


def make_admin(token: str):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from src.database import SessionLocal, User

    with SessionLocal() as db:
        user = db.query(User).filter(User.username == ADMIN_USER).first()
        if user:
            user.is_admin = True
            db.commit()


def get_admin_token() -> str:
    global _admin_token
    if _admin_token is None:
        _admin_token = register_and_login(ADMIN_USER, ADMIN_PASSWORD)
        make_admin(_admin_token)
    return _admin_token


def get_normal_token() -> str:
    global _normal_token
    if _normal_token is None:
        _normal_token = register_and_login(NORMAL_USER, NORMAL_PASSWORD)
    return _normal_token


def api_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def cleanup_configs():
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from src.database import SessionLocal, LlmConfig

    with SessionLocal() as db:
        for config_id in _created_config_ids:
            config = db.query(LlmConfig).filter(LlmConfig.id == config_id).first()
            if config:
                db.delete(config)
        db.commit()
    _created_config_ids.clear()


def setup_module():
    print(f"[Setup] Waiting for server at {BASE_URL}...")
    if not wait_for_server(30):
        raise RuntimeError(f"Server not started at {BASE_URL}")
    print("[Setup] Server is running\n")


def teardown_module():
    cleanup_configs()
    print("\n[Teardown] Cleaned up test configs")


def test_01_list_configs_empty():
    print("[1/14] List configs (initial)...")

    token = get_admin_token()
    resp = requests.get(
        f"{BASE_URL}/api/admin/llm/configs",
        headers=api_headers(token),
        timeout=10,
    )

    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
    data = resp.json()
    assert "configs" in data
    assert "total" in data
    assert isinstance(data["configs"], list)
    print(f"  OK - Found {data['total']} configs")


def test_02_create_config_big():
    print("[2/14] Create big LLM config...")

    token = get_admin_token()
    config_name = f"test-big-{uuid.uuid4().hex[:8]}"

    resp = requests.post(
        f"{BASE_URL}/api/admin/llm/configs",
        headers=api_headers(token),
        json={
            "name": config_name,
            "display_name": "Test Big Model",
            "description": "Test big model for v0.2.3",
            "provider": "zhipuai",
            "base_url": "https://open.bigmodel.cn/api/paas/v4",
            "api_key": "test.key",
            "model_name": "glm-4",
            "temperature": 0.7,
            "max_tokens": 4096,
            "role": "big",
            "activate": False,
        },
        timeout=10,
    )

    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    data = resp.json()
    assert data["name"] == config_name
    assert data["role"] == "big"
    assert data["is_active"] == False
    assert "id" in data

    _created_config_ids.append(data["id"])
    print(f"  OK - Created config: {data['id']}")
    return data["id"], config_name


def test_03_create_config_flash():
    print("[3/14] Create flash LLM config...")

    token = get_admin_token()
    config_name = f"test-flash-{uuid.uuid4().hex[:8]}"

    resp = requests.post(
        f"{BASE_URL}/api/admin/llm/configs",
        headers=api_headers(token),
        json={
            "name": config_name,
            "display_name": "Test Flash Model",
            "description": "Test flash model for v0.2.3",
            "provider": "zhipuai",
            "base_url": "https://open.bigmodel.cn/api/paas/v4",
            "api_key": "test.key",
            "model_name": "glm-4-flash",
            "temperature": 0.5,
            "max_tokens": 2048,
            "role": "flash",
            "activate": True,
        },
        timeout=10,
    )

    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    data = resp.json()
    assert data["name"] == config_name
    assert data["role"] == "flash"
    assert data["is_active"] == True

    _created_config_ids.append(data["id"])
    print(f"  OK - Created and activated config: {data['id']}")
    return data["id"], config_name


def test_04_create_duplicate_name():
    print("[4/14] Create config with duplicate name...")

    token = get_admin_token()

    config_name = f"test-dup-{uuid.uuid4().hex[:8]}"

    resp1 = requests.post(
        f"{BASE_URL}/api/admin/llm/configs",
        headers=api_headers(token),
        json={
            "name": config_name,
            "provider": "ollama",
            "base_url": "http://localhost:11434/v1",
            "api_key": "EMPTY",
            "model_name": "llama3",
            "role": "big",
        },
        timeout=10,
    )
    assert resp1.status_code == 200
    _created_config_ids.append(resp1.json()["id"])

    resp2 = requests.post(
        f"{BASE_URL}/api/admin/llm/configs",
        headers=api_headers(token),
        json={
            "name": config_name,
            "provider": "ollama",
            "base_url": "http://localhost:11434/v1",
            "api_key": "EMPTY",
            "model_name": "llama3",
            "role": "big",
        },
        timeout=10,
    )

    assert resp2.status_code == 400, f"Expected 400, got {resp2.status_code}"
    assert "already exists" in resp2.json().get("detail", "").lower()
    print("  OK - Duplicate name rejected with 400")


def test_05_get_config():
    print("[5/14] Get single config...")

    config_id, config_name = test_02_create_config_big()
    token = get_admin_token()

    resp = requests.get(
        f"{BASE_URL}/api/admin/llm/configs/{config_id}",
        headers=api_headers(token),
        timeout=10,
    )

    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
    data = resp.json()
    assert data["id"] == config_id
    assert data["name"] == config_name
    assert data["provider"] == "zhipuai"
    assert data["model_name"] == "glm-4"
    print(f"  OK - Retrieved config: {config_id}")


def test_06_get_config_not_found():
    print("[6/14] Get non-existent config...")

    token = get_admin_token()

    resp = requests.get(
        f"{BASE_URL}/api/admin/llm/configs/non-existent-id",
        headers=api_headers(token),
        timeout=10,
    )

    assert resp.status_code == 404, f"Expected 404, got {resp.status_code}"
    print("  OK - Non-existent config returns 404")


def test_07_update_config():
    print("[7/14] Update config...")

    config_id, _ = test_02_create_config_big()
    token = get_admin_token()

    resp = requests.put(
        f"{BASE_URL}/api/admin/llm/configs/{config_id}",
        headers=api_headers(token),
        json={
            "display_name": "Updated Display Name",
            "description": "Updated description",
            "temperature": 0.9,
            "max_tokens": 8192,
        },
        timeout=10,
    )

    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    data = resp.json()
    assert data["display_name"] == "Updated Display Name"
    assert data["description"] == "Updated description"
    assert data["temperature"] == 0.9
    assert data["max_tokens"] == 8192
    print(f"  OK - Updated config: {config_id}")


def test_08_activate_config():
    print("[8/14] Activate config (should deactivate others)...")

    token = get_admin_token()

    config_name_1 = f"test-act1-{uuid.uuid4().hex[:8]}"
    resp1 = requests.post(
        f"{BASE_URL}/api/admin/llm/configs",
        headers=api_headers(token),
        json={
            "name": config_name_1,
            "provider": "ollama",
            "base_url": "http://localhost:11434/v1",
            "api_key": "EMPTY",
            "model_name": "llama3",
            "role": "big",
            "activate": True,
        },
        timeout=10,
    )
    assert resp1.status_code == 200
    config_id_1 = resp1.json()["id"]
    _created_config_ids.append(config_id_1)

    config_name_2 = f"test-act2-{uuid.uuid4().hex[:8]}"
    resp2 = requests.post(
        f"{BASE_URL}/api/admin/llm/configs",
        headers=api_headers(token),
        json={
            "name": config_name_2,
            "provider": "ollama",
            "base_url": "http://localhost:11434/v1",
            "api_key": "EMPTY",
            "model_name": "llama3.1",
            "role": "big",
            "activate": False,
        },
        timeout=10,
    )
    assert resp2.status_code == 200
    config_id_2 = resp2.json()["id"]
    _created_config_ids.append(config_id_2)

    resp_activate = requests.post(
        f"{BASE_URL}/api/admin/llm/configs/{config_id_2}/activate",
        headers=api_headers(token),
        timeout=10,
    )

    assert resp_activate.status_code == 200
    assert resp_activate.json()["is_active"] == True

    resp_check = requests.get(
        f"{BASE_URL}/api/admin/llm/configs/{config_id_1}",
        headers=api_headers(token),
        timeout=10,
    )
    assert resp_check.json()["is_active"] == False

    print("  OK - Activating config deactivates others with same role")


def test_09_filter_by_role():
    print("[9/14] Filter configs by role...")

    token = get_admin_token()

    resp_big = requests.get(
        f"{BASE_URL}/api/admin/llm/configs?role=big",
        headers=api_headers(token),
        timeout=10,
    )
    assert resp_big.status_code == 200
    big_configs = resp_big.json()["configs"]
    for c in big_configs:
        assert c["role"] == "big"

    resp_flash = requests.get(
        f"{BASE_URL}/api/admin/llm/configs?role=flash",
        headers=api_headers(token),
        timeout=10,
    )
    assert resp_flash.status_code == 200
    flash_configs = resp_flash.json()["configs"]
    for c in flash_configs:
        assert c["role"] == "flash"

    print(f"  OK - Found {len(big_configs)} big, {len(flash_configs)} flash configs")


def test_10_filter_by_provider():
    print("[10/14] Filter configs by provider...")

    token = get_admin_token()

    resp = requests.get(
        f"{BASE_URL}/api/admin/llm/configs?provider=zhipuai",
        headers=api_headers(token),
        timeout=10,
    )

    assert resp.status_code == 200
    configs = resp.json()["configs"]
    for c in configs:
        assert c["provider"] == "zhipuai"

    print(f"  OK - Found {len(configs)} zhipuai configs")


def test_11_delete_config():
    print("[11/14] Delete config...")

    token = get_admin_token()
    config_name = f"test-del-{uuid.uuid4().hex[:8]}"

    resp_create = requests.post(
        f"{BASE_URL}/api/admin/llm/configs",
        headers=api_headers(token),
        json={
            "name": config_name,
            "provider": "ollama",
            "base_url": "http://localhost:11434/v1",
            "api_key": "EMPTY",
            "model_name": "llama3",
            "role": "big",
        },
        timeout=10,
    )
    assert resp_create.status_code == 200
    config_id = resp_create.json()["id"]

    resp_delete = requests.delete(
        f"{BASE_URL}/api/admin/llm/configs/{config_id}",
        headers=api_headers(token),
        timeout=10,
    )

    assert resp_delete.status_code == 200, (
        f"Expected 200, got {resp_delete.status_code}"
    )

    resp_check = requests.get(
        f"{BASE_URL}/api/admin/llm/configs/{config_id}",
        headers=api_headers(token),
        timeout=10,
    )
    assert resp_check.status_code == 404

    print(f"  OK - Deleted config: {config_id}")


def test_12_test_connection_mock():
    print("[12/14] Test LLM connection (will fail with mock credentials)...")

    token = get_admin_token()

    resp = requests.post(
        f"{BASE_URL}/api/admin/llm/test",
        headers=api_headers(token),
        json={
            "base_url": "https://open.bigmodel.cn/api/paas/v4",
            "api_key": "invalid.key.for.testing",
            "model_name": "glm-4",
        },
        timeout=30,
    )

    assert resp.status_code == 200
    data = resp.json()
    assert "success" in data
    assert "message" in data

    if data["success"]:
        print(f"  OK - Connection successful ({data.get('response_time_ms')}ms)")
    else:
        print(f"  OK - Connection failed as expected: {data['message'][:50]}...")


def test_13_non_admin_access():
    print("[13/14] Non-admin access should be denied...")

    normal_token = get_normal_token()

    resp = requests.get(
        f"{BASE_URL}/api/admin/llm/configs",
        headers=api_headers(normal_token),
        timeout=10,
    )

    assert resp.status_code == 403, f"Expected 403, got {resp.status_code}"
    print("  OK - Non-admin denied with 403")


def test_14_unauthenticated_access():
    print("[14/14] Unauthenticated access should be denied...")

    resp = requests.get(
        f"{BASE_URL}/api/admin/llm/configs",
        timeout=10,
    )

    assert resp.status_code in [401, 403], f"Expected 401/403, got {resp.status_code}"
    print("  OK - Unauthenticated denied with 401/403")


if __name__ == "__main__":
    print("=" * 60)
    print("v0.2.3 LLM Config API Tests")
    print("=" * 60)
    print()

    setup_module()

    tests = [
        test_01_list_configs_empty,
        test_02_create_config_big,
        test_03_create_config_flash,
        test_04_create_duplicate_name,
        test_05_get_config,
        test_06_get_config_not_found,
        test_07_update_config,
        test_08_activate_config,
        test_09_filter_by_role,
        test_10_filter_by_provider,
        test_11_delete_config,
        test_12_test_connection_mock,
        test_13_non_admin_access,
        test_14_unauthenticated_access,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            test()
            passed += 1
        except AssertionError as e:
            print(f"  FAILED - {e}")
            failed += 1
        except Exception as e:
            print(f"  ERROR - {e}")
            failed += 1

    teardown_module()

    print()
    print("=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 60)

    sys.exit(0 if failed == 0 else 1)
