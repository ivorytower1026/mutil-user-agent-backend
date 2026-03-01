"""Agent configuration management API endpoints."""

from typing import Optional

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.database import get_db, User
from src.auth import get_current_user
from src.agent_config_manager import get_agent_config_manager
from src.utils.get_logger import get_logger
from api.server import agent_manager

router = APIRouter()
logger = get_logger("agent-config-api")


async def get_admin_user(
    token: str = Depends(get_current_user), db: Session = Depends(get_db)
) -> User:
    """Get current user and verify admin status."""
    user = db.query(User).filter(User.user_id == token).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


class MainAgentConfigUpdate(BaseModel):
    """Main agent config update request."""

    system_prompt: Optional[str] = None
    mcp_servers: Optional[list[str]] = None
    skills: Optional[list[str]] = None
    subagents: Optional[list[str]] = None


class SubagentCreate(BaseModel):
    """Subagent creation request."""

    name: str
    description: Optional[str] = None
    system_prompt: Optional[str] = None
    mcp_servers: Optional[list[str]] = None
    skills: Optional[list[str]] = None
    model: Optional[str] = None


class SubagentUpdate(BaseModel):
    """Subagent update request."""

    description: Optional[str] = None
    system_prompt: Optional[str] = None
    mcp_servers: Optional[list[str]] = None
    skills: Optional[list[str]] = None
    model: Optional[str] = None


class AgentConfigResponse(BaseModel):
    """Agent config response."""

    id: str
    name: str
    is_main: bool
    description: Optional[str] = None
    system_prompt: Optional[str] = None
    mcp_servers: list[str] = []
    skills: list[str] = []
    subagents: list[str] = []
    model: Optional[str] = None


class AllConfigsResponse(BaseModel):
    """All configs response."""

    main: AgentConfigResponse
    subagents: list[AgentConfigResponse]


def _config_to_response(config) -> AgentConfigResponse:
    """Convert config to response."""
    if isinstance(config, dict):
        return AgentConfigResponse(
            id=config["id"],
            name=config["name"],
            is_main=config.get("is_main", False),
            description=config.get("description"),
            system_prompt=config.get("system_prompt"),
            mcp_servers=config.get("mcp_servers") or [],
            skills=config.get("skills") or [],
            subagents=config.get("subagents") or [],
            model=config.get("model"),
        )
    return AgentConfigResponse(
        id=config.id,
        name=config.name,
        is_main=config.is_main,
        description=config.description,
        system_prompt=config.system_prompt,
        mcp_servers=config.mcp_servers or [],
        skills=config.skills or [],
        subagents=config.subagents or [],
        model=config.model,
    )


@router.get("", response_model=AllConfigsResponse)
async def get_all_agent_configs(
    admin: User = Depends(get_admin_user), db: Session = Depends(get_db)
):
    """Get all agent configurations."""
    manager = get_agent_config_manager()
    configs = manager.get_all_configs(db)

    main_config = manager.get_main_config(db)

    return AllConfigsResponse(
        main=_config_to_response(main_config),
        subagents=[_config_to_response(c) for c in configs.get("subagents", [])],
    )


@router.put("/main", response_model=AgentConfigResponse)
async def update_main_agent_config(
    request: MainAgentConfigUpdate,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    """Update main agent configuration."""
    manager = get_agent_config_manager()

    update_data = {k: v for k, v in request.model_dump().items() if v is not None}

    if not update_data:
        raise HTTPException(status_code=400, detail="No fields to update")

    config = manager.update_main_config(db, update_data)

    await agent_manager.reload_configs()

    return _config_to_response(config)


@router.post("/subagents", response_model=AgentConfigResponse)
async def create_subagent(
    request: SubagentCreate,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    """Create a new subagent."""
    manager = get_agent_config_manager()

    if not request.name:
        raise HTTPException(status_code=400, detail="Name is required")

    if not request.name.replace("-", "").replace("_", "").isalnum():
        raise HTTPException(
            status_code=400,
            detail="Name must be alphanumeric with hyphens or underscores",
        )

    try:
        config = manager.create_subagent(db, request.model_dump())
        await agent_manager.reload_configs()
        return _config_to_response(config)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/subagents/{name}", response_model=AgentConfigResponse)
async def get_subagent_config(
    name: str, admin: User = Depends(get_admin_user), db: Session = Depends(get_db)
):
    """Get subagent configuration by name."""
    manager = get_agent_config_manager()
    config = manager.get_config(name, db)

    if not config or config.is_main:
        raise HTTPException(status_code=404, detail=f"Subagent '{name}' not found")

    return _config_to_response(config)


@router.put("/subagents/{name}", response_model=AgentConfigResponse)
async def update_subagent_config(
    name: str,
    request: SubagentUpdate,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    """Update subagent configuration."""
    manager = get_agent_config_manager()

    update_data = {k: v for k, v in request.model_dump().items() if v is not None}

    if not update_data:
        raise HTTPException(status_code=400, detail="No fields to update")

    try:
        config = manager.update_subagent(db, name, update_data)
        await agent_manager.reload_configs()
        return _config_to_response(config)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/subagents/{name}")
async def delete_subagent_config(
    name: str, admin: User = Depends(get_admin_user), db: Session = Depends(get_db)
):
    """Delete subagent configuration."""
    manager = get_agent_config_manager()

    if not manager.delete_subagent(db, name):
        raise HTTPException(status_code=404, detail=f"Subagent '{name}' not found")

    await agent_manager.reload_configs()

    return {"message": f"Subagent '{name}' deleted"}


@router.post("/reload")
async def reload_agent_configs(
    admin: User = Depends(get_admin_user), db: Session = Depends(get_db)
):
    """Reload agent configurations from database."""
    manager = get_agent_config_manager()
    manager.load_configs(db)

    success = await agent_manager.reload_configs()

    return {"message": "Agent configs reloaded", "success": success}
