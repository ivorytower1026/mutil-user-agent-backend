"""Skill listing tests for Skill Admin API.

Test cases:
- LIST-01: List all skills
- LIST-02: List skills filtered by status
- LIST-03: List skills with nonexistent status
"""
import requests
from .conftest import (
    BASE_URL, get_admin_token, make_admin_admin,
    setup_module, teardown_module, get_tmp_dir,
    create_valid_skill_zip
)


def get_admin_headers():
    token = get_admin_token()
    make_admin_admin(token)
    return {"Authorization": f"Bearer {token}"}


def test_list_01_all_skills():
    """LIST-01: List all skills."""
    print("\n[LIST-01] Test list all skills...")
    
    headers = get_admin_headers()
    response = requests.get(f"{BASE_URL}/api/admin/skills", headers=headers)
    
    assert response.status_code == 200, f"Expected 200, got {response.status_code}"
    data = response.json()
    assert "skills" in data, "Response should contain skills array"
    assert "total" in data, "Response should contain total count"
    assert isinstance(data["skills"], list), "Skills should be a list"
    print(f"  [PASS] Listed {data['total']} skills")
    
    return True


def test_list_02_filter_by_status():
    """LIST-02: List skills filtered by status."""
    print("\n[LIST-02] Test list skills filtered by status...")
    
    headers = get_admin_headers()
    tmp_dir = get_tmp_dir()
    
    create_valid_skill_zip(tmp_dir, "list-test-skill-1")
    create_valid_skill_zip(tmp_dir, "list-test-skill-2")
    
    response = requests.get(
        f"{BASE_URL}/api/admin/skills",
        headers=headers,
        params={"status": "pending"}
    )
    
    assert response.status_code == 200, f"Expected 200, got {response.status_code}"
    data = response.json()
    
    for skill in data["skills"]:
        assert skill["status"] == "pending", f"Expected pending, got {skill['status']}"
    
    print(f"  [PASS] Listed {data['total']} pending skills, all have status='pending'")
    
    return True


def test_list_03_empty_result():
    """LIST-03: List skills with status that has no results."""
    print("\n[LIST-03] Test list skills with empty result...")
    
    headers = get_admin_headers()
    
    response = requests.get(
        f"{BASE_URL}/api/admin/skills",
        headers=headers,
        params={"status": "nonexistent_status_xyz"}
    )
    
    assert response.status_code == 200, f"Expected 200, got {response.status_code}"
    data = response.json()
    assert data["total"] == 0, "Should have 0 skills"
    assert data["skills"] == [], "Skills should be empty array"
    print("  [PASS] Empty result for nonexistent status")
    
    return True


def run_tests():
    """Run all listing tests. Returns list of (name, result) tuples."""
    results = [
        ("LIST-01: All skills", test_list_01_all_skills()),
        ("LIST-02: Filter by status", test_list_02_filter_by_status()),
        ("LIST-03: Empty result", test_list_03_empty_result()),
    ]
    
    for name, result in results:
        status = "PASS" if result is True else "FAIL"
        print(f"  [{status}] {name}")
    
    return results


if __name__ == "__main__":
    import sys
    from .conftest import setup_module, teardown_module
    setup_module()
    try:
        results = run_tests()
        failed = sum(1 for _, r in results if r is not True)
        sys.exit(0 if failed == 0 else 1)
    finally:
        teardown_module()
