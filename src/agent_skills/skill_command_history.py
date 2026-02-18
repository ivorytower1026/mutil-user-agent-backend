"""Command history tracking for dependency recording."""


def get_command_history(backend) -> list[str]:
    """Get bash history commands from container."""
    backend.execute("history -a 2>/dev/null")
    result = backend.execute("cat ~/.bash_history 2>/dev/null || echo ''")
    if result.output.strip():
        return result.output.strip().split("\n")
    return []


def extract_dependencies_from_commands(commands: list[str]) -> dict:
    """Extract dependency info from command list."""
    
    dependencies = {
        "pip": [],
        "apt": [],
        "npm": [],
        "downloaded": [],
        "other_install": [],
        "raw_commands": commands
    }
    
    for cmd in commands:
        if not cmd.strip():
            continue
        cmd_lower = cmd.lower()
        
        if "pip install" in cmd_lower or "pip3 install" in cmd_lower:
            dependencies["pip"].append(cmd)
        elif "apt" in cmd_lower and "install" in cmd_lower:
            dependencies["apt"].append(cmd)
        elif "npm install" in cmd_lower:
            dependencies["npm"].append(cmd)
        elif "curl" in cmd_lower or "wget" in cmd_lower:
            dependencies["downloaded"].append(cmd)
        elif any(x in cmd_lower for x in ["setup.py install", "make install", "dpkg -i", "conda install"]):
            dependencies["other_install"].append(cmd)
    
    return dependencies


async def record_agent_commands(backend, agent_task) -> dict:
    """Record commands executed by agent (before/after comparison)."""
    
    before_history = get_command_history(backend)
    before_count = len(before_history)
    
    result = await agent_task()
    
    after_history = get_command_history(backend)
    new_commands = after_history[before_count:]
    
    dependencies = extract_dependencies_from_commands(new_commands)
    
    return {
        "new_commands": new_commands,
        "dependencies": dependencies,
        "total_new_commands": len(new_commands)
    }
