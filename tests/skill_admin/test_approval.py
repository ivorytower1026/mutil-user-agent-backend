"""Skill approval tests for Skill Admin API.

Test cases:
- APPROVE-01: Approve non-existent skill
- APPROVE-02: Approve skill without completed validation
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


def upload_test_skill(name: str = "approval-test-skill") -> str:
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


def test_approve_01_nonexistent_skill():
    """APPROVE-01: Approve a non-existent skill."""
    print("\n[APPROVE-01] Test approve non-existent skill...")
    
    headers = get_admin_headers()
    response = requests.post(
        f"{BASE_URL}/api/admin/skills/nonexistent-approve-skill/approve",
        headers=headers
    )
    
    assert response.status_code in [400, 404], \
        f"Expected 400 or 404, got {response.status_code}"
    print("  [PASS] Approving non-existent skill returns error")
    
    return True


def test_approve_02_wrong_validation_stage():
    """APPROVE-02: Approve a skill that hasn't completed validation."""
    print("\n[APPROVE-02] Test approve skill without completed validation...")
    
    skill_id = upload_test_skill("approve-no-val-skill")
    assert skill_id is not None, "Failed to upload test skill"
    
    headers = get_admin_headers()
    response = requests.post(
        f"{BASE_URL}/api/admin/skills/{skill_id}/approve",
        headers=headers
    )
    
    assert response.status_code == 400, f"Expected 400, got {response.status_code}: {response.text}"
    detail = response.json().get("detail", "").lower()
    assert "validation" in detail or "completed" in detail, \
        f"Error should mention validation: {detail}"
    print("  [PASS] Cannot approve skill without completed validation")
    
    return True


def run_tests():
    """Run all approval tests. Returns list of (name, result) tuples."""
    results = [
        ("APPROVE-01: Nonexistent skill", test_approve_01_nonexistent_skill()),
        ("APPROVE-02: Wrong validation stage", test_approve_02_wrong_validation_stage()),
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
