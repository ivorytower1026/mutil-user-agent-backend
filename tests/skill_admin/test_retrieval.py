"""Skill retrieval tests for Skill Admin API.

Test cases:
- GET-01: Get skill by ID (with file storage verification)
- GET-02: Get non-existent skill
"""
import os
import requests
from .conftest import (
    BASE_URL, get_admin_token, make_admin_admin,
    setup_module, teardown_module, get_tmp_dir,
    create_valid_skill_zip, verify_skill_file_storage, get_skill_from_db
)


def get_admin_headers():
    token = get_admin_token()
    make_admin_admin(token)
    return {"Authorization": f"Bearer {token}"}


def upload_test_skill(name: str = "retrieval-test-skill") -> str:
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


def test_get_01_by_id():
    """GET-01: Get a skill by ID."""
    print("\n[GET-01] Test get skill by ID...")
    
    skill_id = upload_test_skill("get-test-skill")
    assert skill_id is not None, "Failed to upload test skill"
    
    success, errors = verify_skill_file_storage(skill_id, "get-test-skill")
    assert success, f"File storage verification failed: {errors}"
    print("  [PASS] File storage verified")
    
    headers = get_admin_headers()
    response = requests.get(
        f"{BASE_URL}/api/admin/skills/{skill_id}",
        headers=headers
    )
    
    assert response.status_code == 200, f"Expected 200, got {response.status_code}"
    data = response.json()
    assert data["skill_id"] == skill_id, f"Skill ID mismatch: {data['skill_id']} != {skill_id}"
    assert "name" in data, "Should have name"
    assert "status" in data, "Should have status"
    assert "format_valid" in data, "Should have format_valid"
    assert "format_errors" in data, "Should have format_errors"
    assert "format_warnings" in data, "Should have format_warnings"
    print(f"  [PASS] API response OK: {data['name']} (id={skill_id})")
    
    db_skill = get_skill_from_db(skill_id)
    assert db_skill is not None, "Skill should exist in database"
    assert db_skill['skill_path'] is not None, "skill_path should not be None"
    assert os.path.exists(db_skill['skill_path']), f"Path should exist: {db_skill['skill_path']}"
    print(f"  [PASS] DB record OK, path exists: {db_skill['skill_path']}")
    
    return True


def test_get_02_not_found():
    """GET-02: Get a non-existent skill."""
    print("\n[GET-02] Test get non-existent skill...")
    
    headers = get_admin_headers()
    response = requests.get(
        f"{BASE_URL}/api/admin/skills/nonexistent-skill-id-12345",
        headers=headers
    )
    
    assert response.status_code == 404, f"Expected 404, got {response.status_code}"
    assert "not found" in response.json().get("detail", "").lower()
    print("  [PASS] Non-existent skill returns 404")
    
    return True


def run_tests():
    """Run all retrieval tests. Returns list of (name, result) tuples."""
    results = [
        ("GET-01: By ID", test_get_01_by_id()),
        ("GET-02: Not found", test_get_02_not_found()),
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
