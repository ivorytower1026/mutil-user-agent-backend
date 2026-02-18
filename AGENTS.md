# Agent Guidelines for Multi-tenant AI Agent Platform

## Build and Test Commands

### Environment Setup
```bash
# Install dependencies
uv sync

# Start development server (auto-reload on file changes)
uv run python main.py

# Or use uvicorn directly
uv run uvicorn main:app --host 0.0.0.0 --port 8002 --reload
```

### Running Tests
```bash
# Run v0.1.9 Skill Admin API tests (24 test cases)
uv run python -m tests.skill_admin.run_all

# Run legacy tests (requires server running on settings.PORT)
uv run python tests/test_v0_1_1.py
uv run python tests/test_mvp.py
uv run python tests/test_v0_1_5_webdav.py

# Run single test function: edit the test file to comment out other tests
# Or create a new script that imports and runs the specific function
```

Tests automatically wait for server on `settings.PORT` and clean up when done.

## Project Architecture

- **FastAPI**: Web framework with async support
- **LangGraph 1.0+**: Agent orchestration framework
- **DeepAgents 0.3.12+**: Agent toolkit with HITL (Human-in-the-Loop)
- **PostgreSQL**: Persistent storage with LangGraph checkpoints
- **Docker**: Sandboxed code execution environment

### Directory Structure
```
backend/
├── main.py              # FastAPI app entry point, lifespan setup
├── pyproject.toml       # Dependencies (uv package manager)
├── src/                 # Core business logic
│   ├── config.py        # Settings and LLM instances (big_llm, flash_llm)
│   ├── agent_manager.py # Agent lifecycle, streaming, SSE formatting
│   ├── docker_sandbox.py # Docker container management, Windows path handling
│   ├── auth.py          # JWT authentication, password hashing (argon2)
│   ├── database.py      # SQLAlchemy models (User, Thread, Skill, ImageVersion)
│   ├── webdav.py        # WebDAV handler implementation
│   ├── chunk_upload.py  # Large file chunked upload manager
│   ├── skill_manager.py # Skill CRUD, validation workflow (v0.1.9)
│   ├── skill_validator.py # Validation orchestrator with DeepAgents (v0.1.9)
│   ├── skill_image_manager.py # Image backend with docker save/load (v0.1.9)
│   ├── skill_metrics.py # Metrics collector and scoring (v0.1.9)
│   ├── skill_command_history.py # Command history tracking (v0.1.9)
│   └── utils/           # Utilities (langfuse, get_root_path)
├── api/                 # API layer
│   ├── server.py        # Agent route handlers (/api/*)
│   ├── auth.py          # Auth endpoints (/api/auth/*)
│   ├── admin.py         # Skill admin endpoints (/api/admin/*) (v0.1.9)
│   ├── files.py         # Chunk upload endpoints (/api/files/*)
│   ├── webdav.py        # WebDAV routes (/dav/*)
│   └── models.py        # Pydantic request/response schemas
└── tests/               # Integration tests
    ├── skill_admin/     # v0.1.9 Skill Admin API tests (24 cases)
    │   ├── conftest.py  # Shared fixtures
    │   ├── run_all.py   # Main test runner
    │   └── test_*.py    # Test modules
    └── test_*.py        # Legacy tests
```

## Code Style Guidelines

### Import Order
1. Standard library imports
2. Third-party imports
3. Local imports (from src.*, api.*)

### Type Hints
- Use type hints for all function signatures
- Use `str | None` syntax for optional types (Python 3.13)
- Use `AsyncIterator[str]` for streaming generators
- Use `RunnableConfig` from langchain for LangGraph configs

### Naming Conventions
- **Functions/Variables**: snake_case (e.g., `get_current_user`, `thread_id`)
- **Classes**: PascalCase (e.g., `AgentManager`, `DockerSandboxBackend`)
- **Constants**: UPPER_SNAKE_CASE (e.g., `SECRET_KEY`, `ALGORITHM`)
- **Private methods**: leading underscore (e.g., `_format_event`, `_get_thread_id`)
- **Pydantic models**: PascalCase with descriptive suffixes (e.g., `ChatRequest`, `ThreadStatus`)

### Async/Await Patterns
- All API endpoints use `async def`
- Streaming responses use `AsyncGenerator[str, None]`
- Always use `async for` with agent streaming
- Use `asyncio.create_task()` for parallel execution (e.g., title generation)

### Error Handling
- API errors: Raise `HTTPException` with appropriate status codes
  - 401: Unauthorized (invalid token)
  - 403: Forbidden (wrong user/thread)
  - 400: Bad request (invalid input)
  - 404: Not found (thread/upload doesn't exist)
- Agent errors: Catch `Exception`, log with traceback, return SSE error event
- Always include `finally` blocks for cleanup (e.g., sending "done" SSE event)

### Docstrings
- Use simple descriptive docstrings at function start
- Include Args and Returns for public methods
- Keep docstrings concise and focused on behavior

### Configuration
- All config in `src/config.py` using Pydantic Settings
- Load from environment variables via `.env` file
- Use `@field_validator` for type conversions (e.g., string to int)
- LLM instances: `big_llm` (glm-5), `flash_llm` (qwen3-vl) from `src.config`

### Database
- Use SQLAlchemy ORM with declarative base
- Models in `src/database.py` (User, Thread)
- Use `SessionLocal` sessionmaker with `with` statement (context manager)
- Create tables on startup via `create_tables()`

### Authentication
- JWT tokens with configurable expiration (`ACCESS_TOKEN_EXPIRE_HOURS`)
- Password hashing with argon2 (via passlib)
- Token extraction via `OAuth2PasswordBearer`
- User ID extracted from JWT payload (`sub` field)
- Thread permission: verify `thread_id.startswith(f"{user_id}-")`

### Streaming and SSE
- Use `StreamingResponse` with `AsyncGenerator` for agent responses
- Format SSE events as: `event: {event_name}\ndata: {json}\n\n`
- Event names: `messages/partial`, `tool/start`, `tool/end`, `interrupt`, `error`, `end`, `title_updated`
- Always send final "end" event in finally block
- Handle UTF-8 properly with `ensure_ascii=False` in json.dumps

### Docker Sandbox
- Each user gets isolated workspace: `workspaces/{user_id}/`
- All threads of same user share workspace directory
- Container created on first execute(), reused for thread lifetime
- Mounts: `/workspace` (rw), `/shared` (ro), `/skills` (ro)
- Windows path conversion: `D:\path` -> `/d/path` via `_to_docker_path()`
- Python 3.13-slim image by default

### File Operations
- WebDAV: PROPFIND, GET, PUT, MKCOL, DELETE, MOVE at `/dav/{path}`
- Chunk upload: init -> upload chunks -> complete flow at `/api/files/*`
- Chunk size: 10MB, session expires after 24 hours

### Testing
- Integration tests using `requests` library
- Tests follow pattern: setup -> action -> assert
- Print progress with `[N/total] Test name...`
- Use `assert` statements with helpful messages
- Return values from test functions for chaining
- Wait for server startup with `wait_for_server()` helper

### Environment Variables
Required in `.env`:
- `ZHIPUAI_API_KEY`: LLM API key
- `ZHIPUAI_API_BASE`: LLM endpoint URL
- `DATABASE_URL`: PostgreSQL connection string
- `SECRET_KEY`: JWT signing key
- `IS_LANGFUSE`: Enable Langfuse monitoring (0/1)
- `LANGFUSE_SECRET_KEY`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_BASE_URL`
- `WORKSPACE_ROOT`, `SHARED_DIR`, `DOCKER_IMAGE`
- `PORT`: Server port
- `OPENAI_API_BASE_8001`, `OPENAI_API_BASE_8002`: VLLM endpoints
- `MODELSCOPE_SDK_TOKEN`, `MODELSCOPE_URL`: ModelScope config

### Language and Comments
- Code comments in English
- Print statements prefixed with context: `[AgentManager]`, `[DockerSandbox]`, `[ERROR]`
- Use `[DEBUG]` prefix for temporary debugging logs

### LangGraph Integration
- Use `AsyncPostgresSaver` with connection pool for persistence
- Interrupt on sensitive operations: `execute`, `write_file`
- Thread ID in `configurable.thread_id`
- System prompt: guide agent to work in `/workspace` directory
- Callbacks: attach Langfuse handler for observability
