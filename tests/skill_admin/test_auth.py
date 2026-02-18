"""Authentication and authorization tests for Skill Admin API.

Test cases:
- AUTH-01: Non-admin user access denied
- AUTH-02: No token access denied
- AUTH-03: Invalid token access denied
"""
import requests
from .conftest import (
    BASE_URL, get_normal_token, get_admin_token, make_admin_admin,
    setup_module, teardown_module, get_tmp_dir, create_valid_skill_zip
)


def test_auth_01_non_admin_access_denied():
    """AUTH-01: Non-admin user cannot access admin endpoints."""
    print("\n[AUTH-01] Test non-admin access denied...")
    
    normal_token = get_normal_token()
    headers = {"Authorization": f"Bearer {normal_token}"}
    
    response = requests.get(f"{BASE_URL}/api/admin/skills", headers=headers)
    assert response.status_code == 403, f"Expected 403, got {response.status_code}"
    assert "Admin access required" in response.json().get("detail", "")
    print("  [PASS] Non-admin cannot list skills (GET /api/admin/skills)")
    
    tmp_dir = get_tmp_dir()
    valid_zip = create_valid_skill_zip(tmp_dir, "auth-test-skill")
    with open(valid_zip, 'rb') as f:
        response = requests.post(
            f"{BASE_URL}/api/admin/skills/upload",
            headers=headers,
            files={"file": ("test.zip", f, "application/zip")}
        )
    assert response.status_code == 403, f"Expected 403 for upload, got {response.status_code}"
    print("  [PASS] Non-admin cannot upload skills (POST /api/admin/skills/upload)")
    
    return True


def test_auth_02_no_token_denied():
    """AUTH-02: Requests without token are denied."""
    print("\n[AUTH-02] Test no token access denied...")
    
    response = requests.get(f"{BASE_URL}/api/admin/skills")
    assert response.status_code == 401, f"Expected 401, got {response.status_code}"
    print("  [PASS] GET /api/admin/skills returns 401 without token")
    
    response = requests.post(f"{BASE_URL}/api/admin/skills/dummy-skill/approve")
    assert response.status_code == 401, f"Expected 401, got {response.status_code}"
    print("  [PASS] POST /api/admin/skills/{id}/approve returns 401 without token")
    
    return True


def test_auth_03_invalid_token_denied():
    """AUTH-03: Invalid tokens are denied."""
    print("\n[AUTH-03] Test invalid token denied...")
    
    headers = {"Authorization": "Bearer invalid_token_12345"}
    response = requests.get(f"{BASE_URL}/api/admin/skills", headers=headers)
    assert response.status_code == 401, f"Expected 401, got {response.status_code}"
    print("  [PASS] Invalid token returns 401")
    
    return True


def run_tests():
    """Run all authentication tests. Returns list of (name, result) tuples."""
    results = [
        ("AUTH-01: Non-admin denied", test_auth_01_non_admin_access_denied()),
        ("AUTH-02: No token denied", test_auth_02_no_token_denied()),
        ("AUTH-03: Invalid token denied", test_auth_03_invalid_token_denied()),
    ]
    
    for name, result in results:
        status = "PASS" if result is True else "FAIL"
        print(f"  [{status}] {name}")
    
    return results


if __name__ == "__main__":
    import sys
    success = run_tests()
    sys.exit(0 if success else 1)
