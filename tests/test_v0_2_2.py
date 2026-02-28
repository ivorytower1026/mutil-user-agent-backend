"""
v0.2.2 配置管理 API 测试

测试内容:
- MCP服务管理 (/api/admin/mcp)
- 代理配置管理 (/api/admin/agents)
- 简化Skill管理 (/api/admin/skills/simple)

运行方式:
1. 启动服务: uv run python main.py
2. 运行测试: uv run python tests/test_v0_2_2.py

依赖: Node.js/npx (用于 MCP 连接测试)
"""

import os
import sys
import time
import uuid
import zipfile
import tempfile
import shutil
import requests

BASE_URL = os.environ.get("TEST_BASE_URL", "http://localhost:8005")
ADMIN_USER = f"v022_admin_{uuid.uuid4().hex[:8]}"
ADMIN_PASSWORD = "admin_password_123"

_tmp_dir = None


def get_tmp_dir():
    global _tmp_dir
    if _tmp_dir is None:
        _tmp_dir = tempfile.mkdtemp(prefix="v022_test_")
    return _tmp_dir


def cleanup_tmp_dir():
    global _tmp_dir
    if _tmp_dir and os.path.exists(_tmp_dir):
        shutil.rmtree(_tmp_dir)
        _tmp_dir = None


def wait_for_server(timeout: int = 30) -> bool:
    """等待服务器启动"""
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
    """注册并登录，返回token"""
    try:
        requests.post(
            f"{BASE_URL}/api/auth/register",
            json={"username": username, "password": password},
            timeout=10,
        )
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"注册失败: {e}")

    resp = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"username": username, "password": password},
        timeout=10,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"登录失败: {resp.status_code} {resp.text}")
    return resp.json()["access_token"]


def make_admin(token: str):
    """设置用户为管理员"""
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from src.database import SessionLocal, User

    with SessionLocal() as db:
        user = db.query(User).filter(User.username == ADMIN_USER).first()
        if user:
            user.is_admin = True
            db.commit()


def api_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def create_valid_skill_zip(tmp_dir: str, name: str = "test-skill") -> str:
    """创建有效的 skill ZIP 文件"""
    skill_dir = os.path.join(tmp_dir, f"{name}_dir")
    os.makedirs(skill_dir, exist_ok=True)

    skill_md_content = f"""---
name: {name}
display_name: {name.replace("-", " ").title()}
description: A test skill for v0.2.2 testing
triggers:
  - test
  - v022
---

# {name.replace("-", " ").title()}

This is a test skill for v0.2.2 API testing.
"""

    with open(os.path.join(skill_dir, "SKILL.md"), "w", encoding="utf-8") as f:
        f.write(skill_md_content)

    scripts_dir = os.path.join(skill_dir, "scripts")
    os.makedirs(scripts_dir, exist_ok=True)

    with open(os.path.join(scripts_dir, "main.sh"), "w") as f:
        f.write("#!/bin/bash\necho 'Test skill executed'\n")

    zip_path = os.path.join(tmp_dir, f"{name}.zip")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(skill_dir):
            for file in files:
                file_path = os.path.join(root, file)
                arcname = os.path.relpath(file_path, tmp_dir)
                zf.write(file_path, arcname)

    return zip_path


# ============ MCP API 测试 ============


def test_mcp_crud(token: str) -> str:
    """测试 MCP 服务 CRUD"""
    print("\n=== MCP CRUD 测试 ===")

    mcp_name = f"test-fs-{uuid.uuid4().hex[:6]}"

    # 1. 创建 stdio MCP 服务
    create_resp = requests.post(
        f"{BASE_URL}/api/admin/mcp",
        headers=api_headers(token),
        json={
            "name": mcp_name,
            "transport": "stdio",
            "command": "npx",
            "args": ["-y", "@anthropic/mcp-server-filesystem", "/tmp"],
            "enabled": True,
        },
    )
    assert create_resp.status_code == 200, f"创建失败: {create_resp.text}"
    print(f"  [PASS] 创建 MCP 服务: {mcp_name}")

    # 2. 列出服务
    list_resp = requests.get(f"{BASE_URL}/api/admin/mcp", headers=api_headers(token))
    assert list_resp.status_code == 200
    servers = list_resp.json()["servers"]
    assert any(s["name"] == mcp_name for s in servers)
    print(f"  [PASS] 列出服务: {len(servers)} 个")

    # 3. 获取详情
    get_resp = requests.get(
        f"{BASE_URL}/api/admin/mcp/{mcp_name}", headers=api_headers(token)
    )
    assert get_resp.status_code == 200
    data = get_resp.json()
    assert data["transport"] == "stdio"
    assert data["name"] == mcp_name
    print(f"  [PASS] 获取详情: transport={data['transport']}")

    # 4. 更新服务 (禁用)
    update_resp = requests.put(
        f"{BASE_URL}/api/admin/mcp/{mcp_name}",
        headers=api_headers(token),
        json={"enabled": False},
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["enabled"] == False
    print(f"  [PASS] 更新服务: enabled=False")

    # 5. 重新启用
    update_resp2 = requests.put(
        f"{BASE_URL}/api/admin/mcp/{mcp_name}",
        headers=api_headers(token),
        json={"enabled": True},
    )
    assert update_resp2.status_code == 200
    assert update_resp2.json()["enabled"] == True
    print(f"  [PASS] 重新启用: enabled=True")

    return mcp_name


def test_mcp_connection(token: str, mcp_name: str):
    """测试 MCP 连接"""
    print("\n=== MCP 连接测试 ===")

    # 测试连接
    test_resp = requests.post(
        f"{BASE_URL}/api/admin/mcp/{mcp_name}/test", headers=api_headers(token)
    )
    result = test_resp.json()
    print(f"  连接结果: success={result.get('success')}")

    if result.get("success"):
        print(f"  [PASS] MCP 连接成功, tools_count={result.get('tools_count')}")
    else:
        print(f"  [WARN] MCP 连接失败: {result.get('error')}")


def test_mcp_tools(token: str, mcp_name: str):
    """测试获取 MCP 工具列表"""
    print("\n=== MCP 工具列表测试 ===")

    tools_resp = requests.get(
        f"{BASE_URL}/api/admin/mcp/{mcp_name}/tools",
        headers=api_headers(token),
    )
    if tools_resp.status_code == 200:
        tools = tools_resp.json()
        print(f"  [PASS] 获取到 {len(tools)} 个工具")
        for t in tools[:3]:
            desc = t.get("description", "")[:40]
            print(f"    - {t['name']}: {desc}...")
    else:
        print(f"  [FAIL] 获取工具失败: {tools_resp.status_code}")


def test_mcp_reload(token: str):
    """测试 MCP 重载"""
    print("\n=== MCP 重载测试 ===")

    reload_resp = requests.post(
        f"{BASE_URL}/api/admin/mcp/reload", headers=api_headers(token)
    )
    assert reload_resp.status_code == 200
    print(f"  [PASS] MCP 重载成功")


def test_mcp_http(token: str) -> str:
    """测试 HTTP 模式 MCP 服务"""
    print("\n=== MCP HTTP 模式测试 ===")

    mcp_name = f"test-http-{uuid.uuid4().hex[:6]}"

    # 创建 HTTP 模式 MCP 服务
    create_resp = requests.post(
        f"{BASE_URL}/api/admin/mcp",
        headers=api_headers(token),
        json={
            "name": mcp_name,
            "transport": "http",
            "url": "https://api.example.com/mcp",
            "headers": {"Authorization": "Bearer test"},
            "enabled": True,
        },
    )
    assert create_resp.status_code == 200, f"创建失败: {create_resp.text}"
    print(f"  [PASS] 创建 HTTP MCP 服务: {mcp_name}")

    # 测试连接 (预期失败，因为是假URL)
    test_resp = requests.post(
        f"{BASE_URL}/api/admin/mcp/{mcp_name}/test", headers=api_headers(token)
    )
    result = test_resp.json()
    print(
        f"  连接结果: success={result.get('success')}, error={result.get('error')[:50] if result.get('error') else None}..."
    )

    return mcp_name


def cleanup_mcp(token: str, mcp_name: str):
    """清理 MCP 服务"""
    requests.delete(f"{BASE_URL}/api/admin/mcp/{mcp_name}", headers=api_headers(token))


# ============ Agent Config API 测试 ============


def test_agent_get_all(token: str):
    """测试获取所有代理配置"""
    print("\n=== Agent 配置获取测试 ===")

    resp = requests.get(f"{BASE_URL}/api/admin/agents", headers=api_headers(token))
    assert resp.status_code == 200
    data = resp.json()
    assert "main" in data
    assert "subagents" in data
    print(f"  [PASS] 主代理: {data['main']['name']}")
    print(f"  [PASS] 子代理数量: {len(data['subagents'])}")


def test_agent_update_main(token: str):
    """测试更新主代理配置"""
    print("\n=== 主代理更新测试 ===")

    # 获取当前配置
    get_resp = requests.get(f"{BASE_URL}/api/admin/agents", headers=api_headers(token))
    original_skills = get_resp.json()["main"].get("skills", [])

    # 更新
    update_resp = requests.put(
        f"{BASE_URL}/api/admin/agents/main",
        headers=api_headers(token),
        json={
            "system_prompt": "测试系统提示词 v0.2.2",
            "skills": ["test-skill-1", "test-skill-2"],
        },
    )
    assert update_resp.status_code == 200
    data = update_resp.json()
    assert "test-skill-1" in data["skills"]
    assert "test-skill-2" in data["skills"]
    print(f"  [PASS] 更新成功, skills={data['skills']}")

    # 恢复原配置
    requests.put(
        f"{BASE_URL}/api/admin/agents/main",
        headers=api_headers(token),
        json={"skills": original_skills},
    )


def test_subagent_crud(token: str) -> str:
    """测试子代理 CRUD"""
    print("\n=== 子代理 CRUD 测试 ===")

    subagent_name = f"test-subagent-{uuid.uuid4().hex[:6]}"

    # 1. 创建子代理
    create_resp = requests.post(
        f"{BASE_URL}/api/admin/agents/subagents",
        headers=api_headers(token),
        json={
            "name": subagent_name,
            "description": "测试子代理 v0.2.2",
            "system_prompt": "你是一个测试子代理",
            "skills": ["test-skill"],
            "model": "glm-5",
        },
    )
    assert create_resp.status_code == 200, f"创建失败: {create_resp.text}"
    print(f"  [PASS] 创建子代理: {subagent_name}")

    # 2. 获取子代理
    get_resp = requests.get(
        f"{BASE_URL}/api/admin/agents/subagents/{subagent_name}",
        headers=api_headers(token),
    )
    assert get_resp.status_code == 200
    data = get_resp.json()
    assert data["description"] == "测试子代理 v0.2.2"
    print(f"  [PASS] 获取子代理详情")

    # 3. 更新子代理
    update_resp = requests.put(
        f"{BASE_URL}/api/admin/agents/subagents/{subagent_name}",
        headers=api_headers(token),
        json={"description": "更新后的测试子代理", "model": "qwen3-vl"},
    )
    assert update_resp.status_code == 200
    data = update_resp.json()
    assert data["description"] == "更新后的测试子代理"
    assert data["model"] == "qwen3-vl"
    print(f"  [PASS] 更新子代理")

    # 4. 删除子代理
    delete_resp = requests.delete(
        f"{BASE_URL}/api/admin/agents/subagents/{subagent_name}",
        headers=api_headers(token),
    )
    assert delete_resp.status_code == 200
    print(f"  [PASS] 删除子代理")

    return subagent_name


def test_agent_reload(token: str):
    """测试代理配置重载"""
    print("\n=== Agent 配置重载测试 ===")

    reload_resp = requests.post(
        f"{BASE_URL}/api/admin/agents/reload", headers=api_headers(token)
    )
    assert reload_resp.status_code == 200
    print(f"  [PASS] Agent 配置重载成功")


# ============ Simple Skill API 测试 ============


def test_skill_upload(token: str) -> str:
    """测试上传 skill"""
    print("\n=== Skill 上传测试 ===")

    tmp_dir = get_tmp_dir()
    zip_path = create_valid_skill_zip(tmp_dir, "test-simple-skill")

    with open(zip_path, "rb") as f:
        upload_resp = requests.post(
            f"{BASE_URL}/api/admin/skills/simple/upload",
            headers=api_headers(token),
            files={"file": ("test-simple-skill.zip", f, "application/zip")},
        )

    assert upload_resp.status_code == 200, f"上传失败: {upload_resp.text}"
    data = upload_resp.json()
    print(f"  [PASS] 上传成功: {data['name']}, skill_id={data['skill_id']}")
    return data["skill_id"], data["name"]


def test_skill_list(token: str):
    """测试列出 skill"""
    print("\n=== Skill 列表测试 ===")

    # 列出所有
    list_resp = requests.get(
        f"{BASE_URL}/api/admin/skills/simple", headers=api_headers(token)
    )
    assert list_resp.status_code == 200
    data = list_resp.json()
    print(f"  [PASS] 列出所有: {data['total']} 个")

    # 按 status 过滤
    active_resp = requests.get(
        f"{BASE_URL}/api/admin/skills/simple?status=active",
        headers=api_headers(token),
    )
    assert active_resp.status_code == 200
    print(f"  [PASS] 按 status 过滤: {active_resp.json()['total']} 个 active")


def test_skill_disable_enable(token: str, skill_id: str):
    """测试禁用/启用 skill"""
    print("\n=== Skill 禁用/启用测试 ===")

    # 禁用
    disable_resp = requests.post(
        f"{BASE_URL}/api/admin/skills/simple/{skill_id}/disable",
        headers=api_headers(token),
    )
    assert disable_resp.status_code == 200
    assert disable_resp.json()["status"] == "disabled"
    print(f"  [PASS] 禁用成功: status=disabled")

    # 启用
    enable_resp = requests.post(
        f"{BASE_URL}/api/admin/skills/simple/{skill_id}/enable",
        headers=api_headers(token),
    )
    assert enable_resp.status_code == 200
    assert enable_resp.json()["status"] == "active"
    print(f"  [PASS] 启用成功: status=active")


def test_skill_delete(token: str, name: str):
    """测试删除 skill"""
    print("\n=== Skill 删除测试 ===")

    delete_resp = requests.delete(
        f"{BASE_URL}/api/admin/skills/simple/{name}", headers=api_headers(token)
    )
    assert delete_resp.status_code == 200
    print(f"  [PASS] 删除成功: {name}")


def test_skill_sync(token: str):
    """测试 skill 同步"""
    print("\n=== Skill 同步测试 ===")

    sync_resp = requests.post(
        f"{BASE_URL}/api/admin/skills/simple/sync", headers=api_headers(token)
    )
    assert sync_resp.status_code == 200
    data = sync_resp.json()
    print(f"  [PASS] 同步成功: {data['synced']} 个 skills")


# ============ 错误处理测试 ============


def test_error_cases(token: str):
    """测试错误情况"""
    print("\n=== 错误处理测试 ===")

    # 1. 创建重复名称的 MCP
    mcp_name = f"dup-test-{uuid.uuid4().hex[:6]}"
    resp = requests.post(
        f"{BASE_URL}/api/admin/mcp",
        headers=api_headers(token),
        json={"name": mcp_name, "transport": "stdio", "command": "test"},
    )
    if resp.status_code == 200:
        resp2 = requests.post(
            f"{BASE_URL}/api/admin/mcp",
            headers=api_headers(token),
            json={"name": mcp_name, "transport": "stdio", "command": "test"},
        )
        assert resp2.status_code == 400
        print(f"  [PASS] 重复名称返回 400")
        requests.delete(
            f"{BASE_URL}/api/admin/mcp/{mcp_name}", headers=api_headers(token)
        )

    # 2. 获取不存在的 MCP
    resp = requests.get(
        f"{BASE_URL}/api/admin/mcp/nonexistent", headers=api_headers(token)
    )
    assert resp.status_code == 404
    print(f"  [PASS] 不存在的 MCP 返回 404")

    # 3. 获取不存在的子代理
    resp = requests.get(
        f"{BASE_URL}/api/admin/agents/subagents/nonexistent",
        headers=api_headers(token),
    )
    assert resp.status_code == 404
    print(f"  [PASS] 不存在的子代理返回 404")

    # 4. 删除不存在的 skill
    resp = requests.delete(
        f"{BASE_URL}/api/admin/skills/simple/nonexistent",
        headers=api_headers(token),
    )
    assert resp.status_code == 404
    print(f"  [PASS] 不存在的 skill 返回 404")

    # 5. 非管理员访问
    normal_user = f"normal_{uuid.uuid4().hex[:6]}"
    normal_token = register_and_login(normal_user, "password123")
    resp = requests.get(f"{BASE_URL}/api/admin/mcp", headers=api_headers(normal_token))
    assert resp.status_code == 403
    print(f"  [PASS] 非管理员返回 403")

    # 6. 无效的 MCP transport
    resp = requests.post(
        f"{BASE_URL}/api/admin/mcp",
        headers=api_headers(token),
        json={"name": "invalid-transport", "transport": "invalid"},
    )
    assert resp.status_code == 400
    print(f"  [PASS] 无效 transport 返回 400")

    # 7. stdio 模式没有 command
    resp = requests.post(
        f"{BASE_URL}/api/admin/mcp",
        headers=api_headers(token),
        json={"name": "no-command", "transport": "stdio"},
    )
    assert resp.status_code == 400
    print(f"  [PASS] stdio 没有 command 返回 400")

    # 8. HTTP 模式没有 url
    resp = requests.post(
        f"{BASE_URL}/api/admin/mcp",
        headers=api_headers(token),
        json={"name": "no-url", "transport": "http"},
    )
    assert resp.status_code == 400
    print(f"  [PASS] HTTP 没有 url 返回 400")


# ============ 主函数 ============


def main():
    print("=" * 60)
    print("v0.2.2 配置管理 API 测试")
    print("=" * 60)

    # 等待服务器
    print(f"\n等待服务器 {BASE_URL}...")
    if not wait_for_server():
        print(f"错误: 服务器未启动")
        print(f"请先运行: uv run python main.py")
        sys.exit(1)
    print("服务器就绪")

    # 登录管理员
    print(f"\n创建管理员用户: {ADMIN_USER}")
    token = register_and_login(ADMIN_USER, ADMIN_PASSWORD)
    make_admin(token)
    print("管理员设置完成")

    mcp_names = []
    skill_info = None

    try:
        # ========== MCP 测试 ==========
        print("\n" + "=" * 40)
        print("MCP 服务管理 API 测试")
        print("=" * 40)

        mcp_name = test_mcp_crud(token)
        mcp_names.append(mcp_name)

        test_mcp_connection(token, mcp_name)
        test_mcp_tools(token, mcp_name)

        # HTTP 模式测试
        mcp_name_http = test_mcp_http(token)
        mcp_names.append(mcp_name_http)

        test_mcp_reload(token)

        # ========== Agent Config 测试 ==========
        print("\n" + "=" * 40)
        print("代理配置管理 API 测试")
        print("=" * 40)

        test_agent_get_all(token)
        test_agent_update_main(token)
        test_subagent_crud(token)
        test_agent_reload(token)

        # ========== Simple Skill 测试 ==========
        print("\n" + "=" * 40)
        print("简化 Skill 管理 API 测试")
        print("=" * 40)

        skill_info = test_skill_upload(token)
        test_skill_list(token)
        test_skill_disable_enable(token, skill_info[0])
        test_skill_sync(token)
        test_skill_delete(token, skill_info[1])

        # ========== 错误处理测试 ==========
        print("\n" + "=" * 40)
        print("错误处理测试")
        print("=" * 40)

        test_error_cases(token)

        print("\n" + "=" * 60)
        print("所有测试通过!")
        print("=" * 60)

    except AssertionError as e:
        print(f"\n测试失败: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n异常: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
    finally:
        # 清理 MCP 服务
        for name in mcp_names:
            try:
                cleanup_mcp(token, name)
                print(f"\n清理 MCP: {name}")
            except:
                pass

        cleanup_tmp_dir()
        print("\n测试完成")


if __name__ == "__main__":
    main()
