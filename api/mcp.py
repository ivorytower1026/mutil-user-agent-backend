"""MCP server management API endpoints."""

from typing import Optional

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.database import get_db, User
from src.auth import get_current_user
from src.mcp_manager import get_mcp_manager
from src.utils.get_logger import get_logger

router = APIRouter()
logger = get_logger("mcp-api")


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


class McpServerCreate(BaseModel):
    """MCP server creation request."""

    name: str
    transport: str
    command: Optional[str] = None
    args: Optional[list[str]] = None
    url: Optional[str] = None
    env: Optional[dict[str, str]] = None
    headers: Optional[dict[str, str]] = None
    enabled: bool = True


class McpServerUpdate(BaseModel):
    """MCP server update request."""

    transport: Optional[str] = None
    command: Optional[str] = None
    args: Optional[list[str]] = None
    url: Optional[str] = None
    env: Optional[dict[str, str]] = None
    headers: Optional[dict[str, str]] = None
    enabled: Optional[bool] = None


class McpServerResponse(BaseModel):
    """MCP server response."""

    id: str
    name: str
    transport: str
    command: Optional[str] = None
    args: Optional[list[str]] = None
    url: Optional[str] = None
    env: Optional[dict[str, str]] = None
    headers: Optional[dict[str, str]] = None
    enabled: bool
    created_by: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class McpServerListResponse(BaseModel):
    """MCP server list response."""

    servers: list[McpServerResponse]
    total: int


class McpToolResponse(BaseModel):
    """MCP tool response."""

    name: str
    description: str


class McpTestResponse(BaseModel):
    """MCP connection test response."""

    success: bool
    tools_count: Optional[int] = None
    tools: Optional[list[McpToolResponse]] = None
    error: Optional[str] = None


def _server_to_response(server) -> McpServerResponse:
    """Convert server model to response."""
    return McpServerResponse(
        id=server.id,
        name=server.name,
        transport=server.transport,
        command=server.command,
        args=server.args,
        url=server.url,
        env=server.env,
        headers=server.headers,
        enabled=server.enabled,
        created_by=server.created_by,
        created_at=str(server.created_at) if server.created_at else None,
        updated_at=str(server.updated_at) if server.updated_at else None,
    )


@router.post("", response_model=McpServerResponse)
async def create_mcp_server(
    request: McpServerCreate,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    """Create a new MCP server."""
    manager = get_mcp_manager()

    existing = manager.get_server(db, request.name)
    if existing:
        raise HTTPException(
            status_code=400, detail=f"MCP server '{request.name}' already exists"
        )

    if request.transport not in ("stdio", "http", "sse"):
        raise HTTPException(
            status_code=400, detail="Transport must be 'stdio', 'http', or 'sse'"
        )

    if request.transport == "stdio" and not request.command:
        raise HTTPException(
            status_code=400, detail="Command is required for stdio transport"
        )

    if request.transport in ("http", "sse") and not request.url:
        raise HTTPException(
            status_code=400, detail="URL is required for HTTP/SSE transport"
        )

    try:
        server = await manager.add_server(db, request.model_dump(), admin.user_id)
        return _server_to_response(server)
    except Exception as e:
        logger.exception(f"[create_mcp_server] Failed to create server: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("", response_model=McpServerListResponse)
async def list_mcp_servers(
    admin: User = Depends(get_admin_user), db: Session = Depends(get_db)
):
    """List all MCP servers."""
    manager = get_mcp_manager()
    servers = manager.list_servers(db)

    return McpServerListResponse(
        servers=[_server_to_response(s) for s in servers],
        total=len(servers),
    )


@router.get("/{name}", response_model=McpServerResponse)
async def get_mcp_server(
    name: str, admin: User = Depends(get_admin_user), db: Session = Depends(get_db)
):
    """Get MCP server by name."""
    manager = get_mcp_manager()
    server = manager.get_server(db, name)

    if not server:
        raise HTTPException(status_code=404, detail=f"MCP server '{name}' not found")

    return _server_to_response(server)


@router.put("/{name}", response_model=McpServerResponse)
async def update_mcp_server(
    name: str,
    request: McpServerUpdate,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    """Update an MCP server."""
    manager = get_mcp_manager()

    update_data = {k: v for k, v in request.model_dump().items() if v is not None}

    if not update_data:
        raise HTTPException(status_code=400, detail="No fields to update")

    server = await manager.update_server(db, name, update_data)

    if not server:
        raise HTTPException(status_code=404, detail=f"MCP server '{name}' not found")

    return _server_to_response(server)


@router.delete("/{name}")
async def delete_mcp_server(
    name: str, admin: User = Depends(get_admin_user), db: Session = Depends(get_db)
):
    """Delete an MCP server."""
    manager = get_mcp_manager()

    if not await manager.remove_server(db, name):
        raise HTTPException(status_code=404, detail=f"MCP server '{name}' not found")

    return {"message": f"MCP server '{name}' deleted"}


@router.post("/{name}/test", response_model=McpTestResponse)
async def test_mcp_server(
    name: str, admin: User = Depends(get_admin_user), db: Session = Depends(get_db)
):
    """Test MCP server connection."""
    manager = get_mcp_manager()

    server = manager.get_server(db, name)
    if not server:
        raise HTTPException(status_code=404, detail=f"MCP server '{name}' not found")

    result = await manager.test_connection(name)

    return McpTestResponse(
        success=result.get("success", False),
        tools_count=result.get("tools_count"),
        tools=[
            McpToolResponse(name=t["name"], description=t["description"])
            for t in result.get("tools", [])
        ],
        error=result.get("error"),
    )


@router.get("/{name}/tools", response_model=list[McpToolResponse])
async def list_mcp_tools(
    name: str, admin: User = Depends(get_admin_user), db: Session = Depends(get_db)
):
    """List tools provided by an MCP server."""
    manager = get_mcp_manager()

    server = manager.get_server(db, name)
    if not server:
        raise HTTPException(status_code=404, detail=f"MCP server '{name}' not found")

    tools = await manager.get_all_tools(name)

    return [
        McpToolResponse(name=t.name, description=t.description or "") for t in tools
    ]


@router.post("/reload")
async def reload_mcp_servers(
    admin: User = Depends(get_admin_user), db: Session = Depends(get_db)
):
    """Reload all MCP servers from database."""
    manager = get_mcp_manager()
    await manager.reload(db)

    return {"message": "MCP servers reloaded"}
