import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api.server import router

app = FastAPI(
    title="Multi-tenant AI Agent Platform",
    description="Backend service for AI coding agents",
    version="0.1.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api")


@app.get("/")
async def root():
    return {
        "message": "Multi-tenant AI Agent Platform",
        "version": "0.1.0",
        "endpoints": {
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
