"""Skill upload tests for Skill Admin API.

Test cases:
- UPLOAD-01: Upload valid skill
- UPLOAD-02: Upload non-ZIP file
- UPLOAD-03: Upload skill without SKILL.md
- UPLOAD-04: Upload skill with empty SKILL.md
- UPLOAD-05: Verify file storage on disk
"""
import requests
from .conftest import (
    BASE_URL, get_admin_token, make_admin_admin,
    setup_module, teardown_module, get_tmp_dir,
    create_valid_skill_zip, create_invalid_skill_zip, create_non_zip_file,
    verify_skill_file_storage, get_skill_from_db
)


def get_admin_headers():
    token = get_admin_token()
    make_admin_admin(token)
    return {"Authorization": f"Bearer {token}"}


def test_upload_01_valid_skill():
    """UPLOAD-01: Upload a valid skill ZIP."""
    print("\n[UPLOAD-01] Test upload valid skill...")
    
    headers = get_admin_headers()
    tmp_dir = get_tmp_dir()
    valid_zip = create_valid_skill_zip(tmp_dir, "upload-test-skill")
    
    with open(valid_zip, 'rb') as f:
        response = requests.post(
            f"{BASE_URL}/api/admin/skills/upload",
            headers=headers,
            files={"file": ("upload-test-skill.zip", f, "application/zip")}
        )
    
    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
    data = response.json()
    assert "skill_id" in data, "Response should contain skill_id"
    assert data["name"] == "upload-test-skill", f"Expected name 'upload-test-skill', got {data['name']}"
    assert data["status"] == "pending", f"Expected status 'pending', got {data['status']}"
    assert data["format_valid"] == True, "Valid skill should have format_valid=True"
    print(f"  [PASS] API response OK, skill_id: {data['skill_id']}")
    
    success, errors = verify_skill_file_storage(data['skill_id'], "upload-test-skill")
    assert success, f"File storage verification failed: {errors}"
    print(f"  [PASS] File storage verified")
    
    return data["skill_id"]


def test_upload_02_non_zip_file():
    """UPLOAD-02: Upload a non-ZIP file."""
    print("\n[UPLOAD-02] Test upload non-ZIP file...")
    
    headers = get_admin_headers()
    tmp_dir = get_tmp_dir()
    non_zip = create_non_zip_file(tmp_dir)
    
    with open(non_zip, 'rb') as f:
        response = requests.post(
            f"{BASE_URL}/api/admin/skills/upload",
            headers=headers,
            files={"file": ("not-a-zip.txt", f, "text/plain")}
        )
    
    assert response.status_code == 400, f"Expected 400, got {response.status_code}"
    assert "ZIP" in response.json().get("detail", "")
    print("  [PASS] Non-ZIP file rejected with 400")
    
    return True


def test_upload_03_no_skill_md():
    """UPLOAD-03: Upload a skill without SKILL.md."""
    print("\n[UPLOAD-03] Test upload skill without SKILL.md...")
    
    headers = get_admin_headers()
    tmp_dir = get_tmp_dir()
    invalid_zip = create_invalid_skill_zip(tmp_dir, "no_md")
    
    with open(invalid_zip, 'rb') as f:
        response = requests.post(
            f"{BASE_URL}/api/admin/skills/upload",
            headers=headers,
            files={"file": ("invalid-no-md.zip", f, "application/zip")}
        )
    
    assert response.status_code == 200, f"Expected 200 (uploaded but invalid), got {response.status_code}"
    data = response.json()
    assert data["format_valid"] == False, "format_valid should be False"
    assert len(data["format_errors"]) > 0, "Should have format errors"
    assert "SKILL.md" in data["format_errors"][0], f"Error should mention SKILL.md: {data['format_errors']}"
    print("  [PASS] Invalid skill (no SKILL.md) recorded with errors")
    
    skill = get_skill_from_db(data['skill_id'])
    assert skill is not None, "Skill should exist in database"
    assert skill['skill_path'] is not None, "skill_path should not be None"
    print(f"  [PASS] Skill path recorded: {skill['skill_path']}")
    
    return data["skill_id"]


def test_upload_04_empty_skill_md():
    """UPLOAD-04: Upload a skill with empty SKILL.md."""
    print("\n[UPLOAD-04] Test upload skill with empty SKILL.md...")
    
    headers = get_admin_headers()
    tmp_dir = get_tmp_dir()
    invalid_zip = create_invalid_skill_zip(tmp_dir, "empty_md")
    
    with open(invalid_zip, 'rb') as f:
        response = requests.post(
            f"{BASE_URL}/api/admin/skills/upload",
            headers=headers,
            files={"file": ("invalid-empty.zip", f, "application/zip")}
        )
    
    assert response.status_code == 200, f"Expected 200, got {response.status_code}"
    data = response.json()
    assert data["format_valid"] == False, "format_valid should be False"
    assert len(data["format_errors"]) > 0, "Should have format errors"
    print("  [PASS] Invalid skill (empty SKILL.md) recorded with errors")
    
    return True


def test_upload_05_file_storage():
    """UPLOAD-05: Verify file storage with custom skill name."""
    print("\n[UPLOAD-05] Test file storage verification...")
    
    headers = get_admin_headers()
    tmp_dir = get_tmp_dir()
    skill_name = "storage-verify-skill"
    valid_zip = create_valid_skill_zip(tmp_dir, skill_name)
    
    with open(valid_zip, 'rb') as f:
        response = requests.post(
            f"{BASE_URL}/api/admin/skills/upload",
            headers=headers,
            files={"file": (f"{skill_name}.zip", f, "application/zip")}
        )
    
    assert response.status_code == 200, f"Expected 200, got {response.status_code}"
    data = response.json()
    skill_id = data['skill_id']
    print(f"  [INFO] Uploaded skill: {skill_id}")
    
    success, errors = verify_skill_file_storage(skill_id, skill_name)
    assert success, f"File storage verification failed: {errors}"
    print(f"  [PASS] File storage verified for {skill_name}")
    
    skill = get_skill_from_db(skill_id)
    assert skill is not None
    print(f"  [PASS] Database record exists")
    
    skill_path = skill['skill_path']
    import os
    assert skill_path is not None, "skill_path is None"
    assert os.path.exists(skill_path), f"Path does not exist: {skill_path}"
    print(f"  [PASS] Directory exists: {skill_path}")
    
    skill_md = os.path.join(skill_path, "SKILL.md")
    assert os.path.exists(skill_md), f"SKILL.md not found: {skill_md}"
    print(f"  [PASS] SKILL.md exists")
    
    scripts_dir = os.path.join(skill_path, "scripts")
    assert os.path.exists(scripts_dir), f"scripts/ directory not found: {scripts_dir}"
    print(f"  [PASS] scripts/ directory exists")
    
    main_sh = os.path.join(scripts_dir, "main.sh")
    assert os.path.exists(main_sh), f"main.sh not found: {main_sh}"
    print(f"  [PASS] scripts/main.sh exists")
    
    with open(skill_md, 'r', encoding='utf-8') as f:
        content = f.read()
    assert f"name: {skill_name}" in content, f"SKILL.md should contain name: {skill_name}"
    assert "description:" in content, "SKILL.md should contain description"
    print(f"  [PASS] SKILL.md content verified")
    
    return True


def run_tests():
    """Run all upload tests. Returns list of (name, result) tuples."""
    results = [
        ("UPLOAD-01: Valid skill", test_upload_01_valid_skill() is not None),
        ("UPLOAD-02: Non-ZIP rejected", test_upload_02_non_zip_file()),
        ("UPLOAD-03: No SKILL.md", test_upload_03_no_skill_md() is not None),
        ("UPLOAD-04: Empty SKILL.md", test_upload_04_empty_skill_md()),
        ("UPLOAD-05: File storage", test_upload_05_file_storage()),
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
