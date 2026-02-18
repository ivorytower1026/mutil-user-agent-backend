"""Shared fixtures and configuration for skill admin tests."""
import os
import sys
import time
import shutil
import tempfile
import zipfile
import subprocess
import requests

BASE_URL = "http://localhost:8002"
ADMIN_USER = "skill_admin_user"
ADMIN_PASSWORD = "admin_password_123"
NORMAL_USER = "skill_normal_user"
NORMAL_PASSWORD = "normal_password_123"

_server_process = None
_tmp_dir = None


def get_base_url():
    return BASE_URL


def start_server():
    global _server_process
    if _server_process is not None:
        return _server_process
    
    _server_process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8002"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    )
    
    for _ in range(30):
        try:
            requests.get(f"{BASE_URL}/", timeout=1)
            break
        except:
            time.sleep(1)
    
    return _server_process


def stop_server():
    global _server_process
    if _server_process is not None:
        _server_process.terminate()
        try:
            _server_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _server_process.kill()
        _server_process = None


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
    requests.post(f"{BASE_URL}/api/auth/register", json={
        "username": username,
        "password": password
    })
    
    response = requests.post(f"{BASE_URL}/api/auth/login", data={
        "username": username,
        "password": password
    })
    
    if response.status_code == 200:
        return response.json()["access_token"]
    raise Exception(f"Login failed: {response.text}")


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


def setup_module():
    start_server()


def teardown_module():
    cleanup_tmp_dir()
