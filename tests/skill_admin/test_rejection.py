"""Skill rejection tests for Skill Admin API.

Test cases:
- REJECT-01: Reject skill successfully
- REJECT-02: Reject non-existent skill
- REJECT-03: Reject without reason
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


def upload_test_skill(name: str = "rejection-test-skill") -> str:
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


def test_reject_01_success():
    """REJECT-01: Reject a skill successfully."""
    print("\n[REJECT-01] Test reject skill...")
    
    skill_id = upload_test_skill("reject-test-skill")
    assert skill_id is not None, "Failed to upload test skill"
    
    headers = get_admin_headers()
    response = requests.post(
        f"{BASE_URL}/api/admin/skills/{skill_id}/reject",
        headers=headers,
        json={"reason": "Test rejection reason for REJECT-01"}
    )
    
    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
    data = response.json()
    assert "rejected" in data.get("message", "").lower() or data.get("skill_id") == skill_id
    print("  [PASS] Skill rejected successfully")
    
    response = requests.get(
        f"{BASE_URL}/api/admin/skills/{skill_id}",
        headers=headers
    )
    if response.status_code == 200:
        skill_data = response.json()
        assert skill_data["status"] == "rejected", f"Expected status 'rejected', got {skill_data['status']}"
        print("  [PASS] Skill status is 'rejected'")
    
    return True


def test_reject_02_nonexistent_skill():
    """REJECT-02: Reject a non-existent skill."""
    print("\n[REJECT-02] Test reject non-existent skill...")
    
    headers = get_admin_headers()
    response = requests.post(
        f"{BASE_URL}/api/admin/skills/nonexistent-reject-skill/reject",
        headers=headers,
        json={"reason": "Test"}
    )
    
    assert response.status_code in [400, 404], \
        f"Expected 400 or 404, got {response.status_code}"
    print("  [PASS] Rejecting non-existent skill returns error")
    
    return True


def test_reject_03_without_reason():
    """REJECT-03: Reject a skill without providing a reason."""
    print("\n[REJECT-03] Test reject without reason...")
    
    skill_id = upload_test_skill("reject-no-reason-skill")
    assert skill_id is not None, "Failed to upload test skill"
    
    headers = get_admin_headers()
    response = requests.post(
        f"{BASE_URL}/api/admin/skills/{skill_id}/reject",
        headers=headers,
        json={}
    )
    
    assert response.status_code == 422, f"Expected 422 (validation error), got {response.status_code}"
    print("  [PASS] Reject without reason returns 422")
    
    return True


def run_tests():
    """Run all rejection tests. Returns list of (name, result) tuples."""
    results = [
        ("REJECT-01: Success", test_reject_01_success()),
        ("REJECT-02: Nonexistent skill", test_reject_02_nonexistent_skill()),
        ("REJECT-03: Without reason", test_reject_03_without_reason()),
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
