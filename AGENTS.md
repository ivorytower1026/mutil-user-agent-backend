# Agent Guidelines for Multi-tenant AI Agent Platform

## Build and Test Commands

### Environment Setup
```bash
# Install dependencies
uv sync

# Start development server (auto-reload on file changes)
uv run python main.py

# Run all tests with automatic server management
run_tests.bat

# Run tests manually
uv run python tests/test_v0_1_1.py
uv run python tests/test_mvp.py
```

### Running Single Tests
To run a single test function:
1. Edit the test file and comment out other test functions
2. Or create a new test script that imports and runs the specific function
3. Run with: `uv run python tests/test_v0_1_1.py`

Tests automatically start the FastAPI server on port 8002 and shut it down when complete.

## Project Architecture

- **FastAPI**: Web framework with async support
- **LangGraph 1.0+**: Agent orchestration framework
- **DeepAgents 0.3.12+**: Agent toolkit with HITL (Human-in-the-Loop)
- **PostgreSQL**: Persistent storage with LangGraph checkpoints
- **Docker**: Sandboxed code execution environment

### Directory Structure
```
backend/
├── main.py              # FastAPI app entry point
├── pyproject.toml       # Dependencies and config
├── src/                 # Core business logic
│   ├── config.py        # Settings and LLM configuration
│   ├── agent_manager.py # Agent lifecycle management
│   ├── docker_sandbox.py # Docker container management
│   ├── auth.py          # JWT authentication
│   ├── database.py      # SQLAlchemy models
│   └── utils/           # Utilities (langfuse, etc.)
├── api/                 # API layer
│   ├── server.py        # Route handlers
│   ├── auth.py          # Auth endpoints
│   └── models.py        # Pydantic schemas
└── tests/               # Integration tests
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
- **Classes**: PascalCase (e.g., `AgentManager`, `Settings`)
- **Constants**: UPPER_SNAKE_CASE (e.g., `SECRET_KEY`, `ALGORITHM`)
- **Private methods**: leading underscore (e.g., `_format_event`, `_get_thread_id`)

### Async/Await Patterns
- All API endpoints use `async def`
- Database operations use async patterns where possible
- Streaming responses use `AsyncGenerator[str, None]`
- Always use `async for` with agent streaming

### Error Handling
- API errors: Raise `HTTPException` with appropriate status codes
  - 401: Unauthorized (invalid token)
  - 403: Forbidden (wrong user/thread)
  - 400: Bad request (invalid input)
  - 404: Not found (thread doesn't exist)
- Agent errors: Catch `Exception`, log with traceback, return SSE error event
- Always include `finally` blocks for cleanup (e.g., sending "done" SSE event)

### Docstrings
- Use Google-style or simple descriptive docstrings
- Include Args and Returns for public methods
- Keep docstrings concise and focused on user-facing behavior

### Configuration
- All config in `src/config.py` using Pydantic Settings
- Load from environment variables via `.env` file
- Use `@field_validator` for type conversions (e.g., string to int)
- LLM instance is global: `llm` from `src.config`

### Database
- Use SQLAlchemy ORM with declarative base
- Models in `src/database.py`
- Use `SessionLocal` sessionmaker with context manager (`get_db()`)
- Create tables on startup via `create_tables()`

### Authentication
- JWT tokens with 24-hour expiration
- Password hashing with argon2 (via passlib)
- Token extraction via `OAuth2PasswordBearer`
- User ID extracted from JWT payload (`sub` field)
- Thread permission: verify `thread_id.startswith(f"{user_id}-")`

### Streaming and SSE
- Use `StreamingResponse` with `AsyncGenerator` for agent responses
- Format SSE events as: `data: {json}\n\n`
- Event types: `content`, `tool_start`, `tool_end`, `interrupt`, `error`, `done`
- Always send final "done" event in finally block
- Handle UTF-8 properly with `ensure_ascii=False` in json.dumps

### Docker Sandbox
- Each thread gets isolated container
- Workspace mounted at `/workspace` inside container
- Shared dir mounted at `/shared` (read-only)
- Container created on first use, reused for thread lifetime
- Python 3.13-slim image by default

### Testing
- Integration tests using `requests` library
- Tests follow pattern: setup → action → assert
- Print progress with `[N/total] Test name...`
- Use `assert` statements with helpful messages
- Return values from test functions for chaining

### Environment Variables
Required in `.env`:
- `ZHIPUAI_API_KEY`: LLM API key
- `ZHIPUAI_API_BASE`: LLM endpoint URL
- `DATABASE_URL`: PostgreSQL connection string
- `SECRET_KEY`: JWT signing key

Optional (with defaults in code):
- `WORKSPACE_ROOT`: `./workspaces`
- `SHARED_DIR`: `./shared`
- `DOCKER_IMAGE`: `python:3.13-slim`
- `ACCESS_TOKEN_EXPIRE_HOURS`: `24`

### Language and Comments
- Code comments in English
- Docstrings can be bilingual (English/Chinese) for clarity
- Use `# DEBUG:` or `[DEBUG]` for temporary debugging logs
- Print statements prefixed with context: `[AgentManager]`, `[ERROR]`, etc.

### LangGraph Integration
- Use `PostgresSaver` with connection pool for persistence
- Interrupt on sensitive operations: `execute`, `write_file`
- Thread ID in `configurable.thread_id`
- System prompt: guide agent to work in `/workspace` directory
- Callbacks: attach Langfuse handler for observability
