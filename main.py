import sys
import asyncio

if sys.platform == "win32":
    asyncio.set_event_loop_policy(
        asyncio.WindowsSelectorEventLoopPolicy()
    )
from contextlib import asynccontextmanager

from src.config import settings

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api.server import router as api_router, agent_manager
from api.auth import router as auth_router
from api.webdav import router as webdav_router
from api.files import router as files_router, upload_manager
from api.admin import router as admin_router
from api.workspace import router as workspace_router
from src.database import create_tables
from src.agent_skills.skill_validator import get_validation_orchestrator

@asynccontextmanager
async def lifespan(app: FastAPI):
    create_tables()
    await agent_manager.init()
    
    cleaned = upload_manager.cleanup_stale()
    if cleaned > 0:
        print(f"[Startup] Cleaned up {cleaned} stale upload sessions")
    
    try:
        yield
    finally:
        await agent_manager.close()
        print("[Shutdown] Agent manager closed")

app = FastAPI(
    title="Multi-tenant AI Agent Platform",
    description="Backend service for AI coding agents",
    version="0.1.9",
    lifespan=lifespan
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

# Include workspace router for file sync
app.include_router(workspace_router)


@app.get("/")
async def root():
    return {
        "message": "Multi-tenant AI Agent Platform",
        "version": "0.1.9",
        "endpoints": {
            "register": "POST /api/auth/register",
            "login": "POST /api/auth/login",
            "create_session": "POST /api/sessions",
            "chat": "POST /api/chat/{thread_id}",
            "resume": "POST /api/resume/{thread_id}",
            "webdav": "/dav/{path} (PROPFIND/GET/PUT/MKCOL/DELETE/MOVE)",
            "chunk_upload": "/api/files/init-upload, /api/files/upload-chunk, /api/files/complete-upload",
            "admin_skills": "/api/admin/skills (GET, POST /upload, GET/POST/DELETE /{skill_id})"
        }
    }


if __name__ == "__main__":
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=settings.PORT,
        reload=False
    )
