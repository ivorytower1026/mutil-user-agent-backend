import asyncio
from asyncio import WindowsSelectorEventLoopPolicy
from contextlib import asynccontextmanager

from src.config import settings

asyncio.set_event_loop_policy(WindowsSelectorEventLoopPolicy())

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api.server import router as api_router, agent_manager
from api.auth import router as auth_router
from api.webdav import router as webdav_router
from api.files import router as files_router, upload_manager
from api.admin import router as admin_router
from api.mcp import router as mcp_router
from api.agent_config import router as agent_config_router
from src.database import create_tables
from src.agent_skills.skill_validator import get_validation_orchestrator
from src.docker_sandbox import DockerSandboxBackend


async def _cleanup_idle_containers_task():
    """Background task to clean up idle containers."""
    while True:
        await asyncio.sleep(60)
        try:
            cleaned = DockerSandboxBackend.cleanup_idle_containers()
            if cleaned > 0:
                print(f"[CleanupTask] Cleaned up {cleaned} idle containers")
        except Exception as e:
            print(f"[CleanupTask] Error: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_tables()
    await agent_manager.init()

    orchestrator = get_validation_orchestrator()
    resumed_count = await orchestrator.resume_all_pending()
    if resumed_count > 0:
        print(f"[Startup] Resumed {resumed_count} pending validations")

    cleaned = upload_manager.cleanup_stale()
    if cleaned > 0:
        print(f"[Startup] Cleaned up {cleaned} stale upload sessions")

    cleanup_task = asyncio.create_task(_cleanup_idle_containers_task())
    print("[Startup] Container cleanup task started")

    try:
        yield
    finally:
        cleanup_task.cancel()
        await agent_manager.close()
        print("[Shutdown] Agent manager closed")


app = FastAPI(
    title="Multi-tenant AI Agent Platform",
    description="Backend service for AI coding agents",
    version="0.1.9",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include auth router (no authentication required)
app.include_router(auth_router, prefix="/api/auth")

# Include API router (authentication required)
app.include_router(api_router, prefix="/api")

# Include WebDAV router
app.include_router(webdav_router, prefix="/dav", tags=["webdav"])

# Include files router for chunk upload
app.include_router(files_router, prefix="/api")

# Include admin router for skill management
app.include_router(admin_router, prefix="/api/admin", tags=["admin"])

# Include MCP router for MCP server management
app.include_router(mcp_router, prefix="/api/admin/mcp", tags=["mcp"])

# Include agent config router for agent configuration management
app.include_router(agent_config_router, prefix="/api/admin/agents", tags=["agents"])


@app.get("/")
async def root():
    return {
        "message": "Multi-tenant AI Agent Platform",
        "version": "0.2.0",
        "endpoints": {
            "register": "POST /api/auth/register",
            "login": "POST /api/auth/login",
            "create_session": "POST /api/sessions",
            "chat": "POST /api/chat/{thread_id}",
            "resume": "POST /api/resume/{thread_id}",
            "webdav": "/dav/{path} (PROPFIND/GET/PUT/MKCOL/DELETE/MOVE)",
            "chunk_upload": "/api/files/init-upload, /api/files/upload-chunk, /api/files/complete-upload",
            "admin_skills": "/api/admin/skills (GET, POST /upload, GET/POST/DELETE /{skill_id})",
            "admin_skills_simple": "/api/admin/skills/simple (GET, POST /upload, DELETE /{name})",
            "admin_mcp": "/api/admin/mcp (GET, POST, GET/PUT/DELETE /{name})",
            "admin_agents": "/api/admin/agents (GET, PUT /main, POST/GET/PUT/DELETE /subagents/{name})",
        },
    }


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=settings.PORT, reload=True)
