"""Validation report tests for Skill Admin API.

Test cases:
- REPORT-01: Get report for pending validation skill
- REPORT-02: Get report for non-existent skill
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


def upload_test_skill(name: str = "report-test-skill") -> str:
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


def test_report_01_pending_validation():
    """REPORT-01: Get report for a skill with pending validation."""
    print("\n[REPORT-01] Test get report for pending validation...")
    
    skill_id = upload_test_skill("report-test-skill")
    assert skill_id is not None, "Failed to upload test skill"
    
    headers = get_admin_headers()
    response = requests.get(
        f"{BASE_URL}/api/admin/skills/{skill_id}/report",
        headers=headers
    )
    
    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
    data = response.json()
    assert "content" in data, "Response should contain content"
    assert "content_type" in data, "Response should contain content_type"
    assert data["content_type"] == "markdown", f"Expected markdown, got {data['content_type']}"
    assert len(data["content"]) > 0, "Content should not be empty"
    print("  [PASS] Report returned for pending validation")
    
    return True


def test_report_02_nonexistent_skill():
    """REPORT-02: Get report for a non-existent skill."""
    print("\n[REPORT-02] Test get report for non-existent skill...")
    
    headers = get_admin_headers()
    response = requests.get(
        f"{BASE_URL}/api/admin/skills/nonexistent-report-skill/report",
        headers=headers
    )
    
    assert response.status_code == 404, f"Expected 404, got {response.status_code}"
    print("  [PASS] Report for non-existent skill returns 404")
    
    return True


def run_tests():
    """Run all report tests. Returns list of (name, result) tuples."""
    results = [
        ("REPORT-01: Pending validation", test_report_01_pending_validation()),
        ("REPORT-02: Nonexistent skill", test_report_02_nonexistent_skill()),
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
