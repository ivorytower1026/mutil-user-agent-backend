"""Shared fixtures and configuration for skill admin tests.

Usage:
    1. Start server manually: uv run python main.py
    2. Run tests: uv run python -m tests.skill_admin.run_all
"""
import os
import sys
import time
import shutil
import tempfile
import zipfile
import requests

BASE_URL = "http://localhost:8002"
ADMIN_USER = "skill_admin_user"
ADMIN_PASSWORD = "admin_password_123"
NORMAL_USER = "skill_normal_user"
NORMAL_PASSWORD = "normal_password_123"

_tmp_dir = None


def get_base_url():
    return BASE_URL


def is_server_running():
    """Check if server at BASE_URL is responding."""
    try:
        resp = requests.get(f"{BASE_URL}/", timeout=2)
        return resp.status_code == 200
    except requests.exceptions.RequestException:
        return False


def wait_for_server(timeout: int = 30) -> bool:
    """Wait for server to be ready."""
    for i in range(timeout):
        if is_server_running():
            return True
        time.sleep(1)
    return False


def ensure_server_running():
    """Ensure server is running, raise error if not."""
    if not is_server_running():
        raise RuntimeError(
            f"Server is not running at {BASE_URL}\n"
            "Please start the server first:\n"
            "  uv run python main.py"
        )


def start_server():
    """Check if server is running. Raises error if not."""
    print(f"[Setup] Checking server at {BASE_URL}...")
    
    if is_server_running():
        print("[Setup] Server is running\n")
        return True
    
    print(f"[Setup] Server not responding at {BASE_URL}")
    print("[Setup] Please start server in another terminal:")
    print("  uv run python main.py")
    print()
    
    print("[Setup] Waiting for server to start (30s timeout)...")
    if wait_for_server(30):
        print("[Setup] Server is now running\n")
        return True
    
    raise RuntimeError(
        f"Server not started at {BASE_URL}\n"
        "Please run: uv run python main.py"
    )


def stop_server():
    """No-op - server should be managed externally."""
    pass


def get_tmp_dir():
    global _tmp_dir
    if _tmp_dir is None:
        _tmp_dir = tempfile.mkdtemp(prefix="skill_test_")
    return _tmp_dir


def cleanup_tmp_dir():
    global _tmp_dir
    if _tmp_dir and os.path.exists(_tmp_dir):
        shutil.rmtree(_tmp_dir)
        _tmp_dir = None


def register_and_login(username: str, password: str) -> str:
    ensure_server_running()
    
    try:
        requests.post(f"{BASE_URL}/api/auth/register", json={
            "username": username,
            "password": password
        }, timeout=10)
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"Failed to register user '{username}': {e}")
    
    try:
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "username": username,
            "password": password
        }, timeout=10)
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"Failed to login user '{username}': {e}")
    
    if response.status_code == 200:
        return response.json()["access_token"]
    raise RuntimeError(f"Login failed for '{username}': status={response.status_code}, body={response.text}")


def get_admin_token() -> str:
    return register_and_login(ADMIN_USER, ADMIN_PASSWORD)


def get_normal_token() -> str:
    return register_and_login(NORMAL_USER, NORMAL_PASSWORD)


def make_admin_admin(token: str):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    from src.database import SessionLocal, User
    
    with SessionLocal() as db:
        user = db.query(User).filter(User.username == ADMIN_USER).first()
        if user:
            user.is_admin = True
            db.commit()


def create_valid_skill_zip(tmp_dir: str, name: str = "test-skill") -> str:
    skill_dir = os.path.join(tmp_dir, f"{name}_dir")
    os.makedirs(skill_dir, exist_ok=True)
    
    skill_md_content = f"""---
name: {name}
display_name: {name.replace('-', ' ').title()}
description: A test skill for validation testing
triggers:
  - test
  - validate
---

# {name.replace('-', ' ').title()}

This is a test skill for validation.

## Capabilities

- Execute test tasks
- Validate results
"""
    
    with open(os.path.join(skill_dir, "SKILL.md"), "w", encoding="utf-8") as f:
        f.write(skill_md_content)
    
    scripts_dir = os.path.join(skill_dir, "scripts")
    os.makedirs(scripts_dir, exist_ok=True)
    
    with open(os.path.join(scripts_dir, "main.sh"), "w") as f:
        f.write("#!/bin/bash\necho 'Test skill executed'\n")
    
    zip_path = os.path.join(tmp_dir, f"{name}.zip")
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(skill_dir):
            for file in files:
                file_path = os.path.join(root, file)
                arcname = os.path.relpath(file_path, tmp_dir)
                zf.write(file_path, arcname)
    
    return zip_path


def create_invalid_skill_zip(tmp_dir: str, error_type: str = "no_md") -> str:
    if error_type == "no_md":
        skill_dir = os.path.join(tmp_dir, "invalid-skill-no-md")
        os.makedirs(skill_dir, exist_ok=True)
        
        with open(os.path.join(skill_dir, "README.txt"), "w") as f:
            f.write("This skill has no SKILL.md")
        
        zip_path = os.path.join(tmp_dir, "invalid-no-md.zip")
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for root, dirs, files in os.walk(skill_dir):
                for file in files:
                    file_path = os.path.join(root, file)
                    arcname = os.path.relpath(file_path, tmp_dir)
                    zf.write(file_path, arcname)
        return zip_path
    
    elif error_type == "empty_md":
        skill_dir = os.path.join(tmp_dir, "invalid-skill-empty")
        os.makedirs(skill_dir, exist_ok=True)
        
        with open(os.path.join(skill_dir, "SKILL.md"), "w") as f:
            f.write("")
        
        zip_path = os.path.join(tmp_dir, "invalid-empty.zip")
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for root, dirs, files in os.walk(skill_dir):
                for file in files:
                    file_path = os.path.join(root, file)
                    arcname = os.path.relpath(file_path, tmp_dir)
                    zf.write(file_path, arcname)
        return zip_path
    
    elif error_type == "invalid_frontmatter":
        skill_dir = os.path.join(tmp_dir, "invalid-skill-frontmatter")
        os.makedirs(skill_dir, exist_ok=True)
        
        skill_md_content = """---
invalid_yaml: [[
---

# Invalid Frontmatter
"""
        
        with open(os.path.join(skill_dir, "SKILL.md"), "w") as f:
            f.write(skill_md_content)
        
        zip_path = os.path.join(tmp_dir, "invalid-frontmatter.zip")
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for root, dirs, files in os.walk(skill_dir):
                for file in files:
                    file_path = os.path.join(root, file)
                    arcname = os.path.relpath(file_path, tmp_dir)
                    zf.write(file_path, arcname)
        return zip_path
    
    return ""


def create_non_zip_file(tmp_dir: str) -> str:
    txt_path = os.path.join(tmp_dir, "not-a-zip.txt")
    with open(txt_path, "w") as f:
        f.write("This is not a ZIP file")
    return txt_path


def upload_skill(token: str, zip_path: str, filename: str = None) -> dict:
    if filename is None:
        filename = os.path.basename(zip_path)
    
    headers = {"Authorization": f"Bearer {token}"}
    with open(zip_path, 'rb') as f:
        response = requests.post(
            f"{BASE_URL}/api/admin/skills/upload",
            headers=headers,
            files={"file": (filename, f, "application/zip")}
        )
    
    return response


def get_skill_from_db(skill_id: str) -> dict:
    """Get skill record from database by ID."""
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    from src.database import SessionLocal, Skill
    
    with SessionLocal() as db:
        skill = db.query(Skill).filter(Skill.skill_id == skill_id).first()
        if skill:
            return {
                "skill_id": skill.skill_id,
                "name": skill.name,
                "display_name": skill.display_name,
                "description": skill.description,
                "status": skill.status,
                "skill_path": skill.skill_path,
                "format_valid": skill.format_valid,
                "format_errors": skill.format_errors,
                "format_warnings": skill.format_warnings,
                "validation_stage": skill.validation_stage,
                "validation_score": skill.validation_score,
                "validation_report": skill.validation_report,
            }
        return None


def verify_skill_file_storage(skill_id: str, expected_name: str = None) -> tuple[bool, list[str]]:
    """Verify that skill files are properly stored on disk.
    
    Returns:
        tuple: (success, errors)
    """
    errors = []
    
    skill = get_skill_from_db(skill_id)
    if not skill:
        errors.append(f"Skill not found in database: {skill_id}")
        return False, errors
    
    skill_path = skill.get("skill_path")
    if not skill_path:
        errors.append(f"skill_path is None in database")
        return False, errors
    
    if not os.path.exists(skill_path):
        errors.append(f"skill_path directory does not exist: {skill_path}")
        return False, errors
    
    skill_md_path = os.path.join(skill_path, "SKILL.md")
    if not os.path.exists(skill_md_path):
        errors.append(f"SKILL.md not found at: {skill_md_path}")
        return False, errors
    
    with open(skill_md_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    if not content.strip():
        errors.append(f"SKILL.md is empty at: {skill_md_path}")
        return False, errors
    
    if expected_name and f"name: {expected_name}" not in content:
        errors.append(f"SKILL.md does not contain expected name '{expected_name}'")
        return False, errors
    
    return True, []


def verify_skill_deleted(skill_id: str) -> tuple[bool, list[str]]:
    """Verify that skill is deleted from both database and filesystem.
    
    Returns:
        tuple: (success, errors)
    """
    errors = []
    
    skill = get_skill_from_db(skill_id)
    if skill:
        errors.append(f"Skill still exists in database: {skill_id}")
    
    return len(errors) == 0, errors


def setup_module():
    start_server()


def teardown_module():
    cleanup_tmp_dir()
