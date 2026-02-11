import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api.server import router as api_router
from api.auth import router as auth_router
from src.database import create_tables

app = FastAPI(
    title="Multi-tenant AI Agent Platform",
    description="Backend service for AI coding agents",
    version="0.1.1"
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


@app.on_event("startup")
async def startup_event():
    """Create database tables on startup."""
    create_tables()


@app.get("/")
async def root():
    return {
        "message": "Multi-tenant AI Agent Platform",
        "version": "0.1.1",
        "endpoints": {
            "register": "POST /api/auth/register",
            "login": "POST /api/auth/login",
            "create_session": "POST /api/sessions",
            "chat": "POST /api/chat/{thread_id}",
            "resume": "POST /api/resume/{thread_id}"
        }
    }


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8002,
        reload=True
    )
