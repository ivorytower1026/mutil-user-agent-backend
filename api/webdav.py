"""WebDAV API routes."""
from fastapi import APIRouter, Request, Depends, Header
from fastapi.responses import Response

from src.webdav import WebDAVHandler
from src.auth import get_current_user
from src.config import settings

router = APIRouter()
webdav = WebDAVHandler(settings.WORKSPACE_ROOT)


@router.api_route(
    "/{path:path}",
    methods=["PROPFIND", "GET", "PUT", "MKCOL", "DELETE", "MOVE"],
    include_in_schema=False
)
async def webdav_handler(
    request: Request,
    path: str,
    user_id: str = Depends(get_current_user),
    depth: int = Header(default=1, alias="Depth"),
    destination: str | None = Header(default=None, alias="Destination"),
    if_match: str | None = Header(default=None, alias="If-Match"),
):
    """Handle WebDAV requests.
    
    Supports: PROPFIND, GET, PUT, MKCOL, DELETE, MOVE
    
    Args:
        request: FastAPI request object
        path: Relative path within user's workspace
        user_id: Authenticated user ID
        depth: PROPFIND depth (0 or 1)
        destination: MOVE destination path
        if_match: ETag for conflict detection (PUT)
    """
    if request.method == "PROPFIND":
        return await webdav.propfind(user_id, path, depth)
    
    elif request.method == "GET":
        return await webdav.get(user_id, path)
    
    elif request.method == "PUT":
        body = await request.body()
        return await webdav.put(user_id, path, body, if_match)
    
    elif request.method == "MKCOL":
        return await webdav.mkcol(user_id, path)
    
    elif request.method == "DELETE":
        return await webdav.delete(user_id, path)
    
    elif request.method == "MOVE":
        if not destination:
            from fastapi import HTTPException
            raise HTTPException(status_code=400, detail="Destination header required")
        dst_path = destination.split("/dav/")[-1] if "/dav/" in destination else destination
        dst_path = dst_path.lstrip(f"{user_id}/")
        return await webdav.move(user_id, path, dst_path)
    
    return Response(status_code=405)
