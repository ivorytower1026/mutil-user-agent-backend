"""Skill deletion tests for Skill Admin API.

Test cases:
- DEL-01: Delete skill successfully
- DEL-02: Delete non-existent skill
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


def upload_test_skill(name: str = "deletion-test-skill") -> str:
    headers = get_admin_headers()
    tmp_dir = get_tmp_dir()
    valid_zip = create_valid_skill_zip(tmp_dir, name)
    
    with open(valid_zip, 'rb') as f:
        response = requests.post(
            f"{BASE_URL}/api/admin/skills/upload",
            headers=headers,
            files={"file": (f"{name}.zip", f, "application/zip")}
        )
    
    if response.status_code == 200:
        return response.json()["skill_id"]
    return None


def test_del_01_success():
    """DEL-01: Delete a skill successfully."""
    print("\n[DEL-01] Test delete skill...")
    
    skill_id = upload_test_skill("delete-test-skill")
    assert skill_id is not None, "Failed to upload test skill"
    
    headers = get_admin_headers()
    response = requests.delete(
        f"{BASE_URL}/api/admin/skills/{skill_id}",
        headers=headers
    )
    
    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
    print("  [PASS] Skill deleted successfully")
    
    response = requests.get(
        f"{BASE_URL}/api/admin/skills/{skill_id}",
        headers=headers
    )
    assert response.status_code == 404, f"Skill should no longer exist, got {response.status_code}"
    print("  [PASS] Deleted skill returns 404 on GET")
    
    return True


def test_del_02_nonexistent_skill():
    """DEL-02: Delete a non-existent skill."""
    print("\n[DEL-02] Test delete non-existent skill...")
    
    headers = get_admin_headers()
    response = requests.delete(
        f"{BASE_URL}/api/admin/skills/nonexistent-delete-skill",
        headers=headers
    )
    
    assert response.status_code == 404, f"Expected 404, got {response.status_code}"
    print("  [PASS] Deleting non-existent skill returns 404")
    
    return True


def run_tests():
    """Run all deletion tests. Returns list of (name, result) tuples."""
    results = [
        ("DEL-01: Success", test_del_01_success()),
        ("DEL-02: Nonexistent skill", test_del_02_nonexistent_skill()),
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
