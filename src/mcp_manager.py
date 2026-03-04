"""MCP server connection and tool management."""

import os
import subprocess
import sys
import uuid
from typing import Any

from langchain_core.tools import BaseTool
from sqlalchemy.orm import Session

from src.database import McpServer, SessionLocal
from src.utils.get_logger import get_logger

logger = get_logger("mcp-manager")


class McpToolAdapter:
    """Adapter for MCP server tools."""

    def __init__(self, server_config: McpServer):
        self.config = server_config
        self._tools: list[BaseTool] = []
        self._process: subprocess.Popen | None = None
        self._connected = False
        self._connection: dict[str, Any] | None = None

    async def connect(self) -> bool:
        """Connect to MCP server and load tools."""
        try:
            if self.config.transport == "stdio":
                return await self._connect_stdio()
            elif self.config.transport in ("http", "sse"):
                return await self._connect_http()
            else:
                logger.error(
                    f"[McpToolAdapter] Unknown transport: {self.config.transport}"
                )
                return False
        except Exception as e:
            logger.exception(f"[McpToolAdapter] Failed to connect: {e}")
            return False

    async def _connect_stdio(self) -> bool:
        """Connect via stdio transport."""
        if not self.config.command:
            logger.error(
                f"[McpToolAdapter] No command for stdio transport: {self.config.name}"
            )
            return False

        env = dict(self.config.env or {})

        if sys.platform == "win32":
            for key in [
                "PROGRAMFILES",
                "ProgramData",
                "PROGRAMFILES(X86)",
                "ProgramW6432",
            ]:
                if key in os.environ and key not in env:
                    env[key] = os.environ[key]

        self._connection = {
            "transport": "stdio",
            "command": self.config.command,
            "args": self.config.args or [],
            "env": env,
        }
        self._connected = True
        logger.info(f"[McpToolAdapter] Connected to {self.config.name} via stdio")
        return True

    async def _connect_http(self) -> bool:
        """Connect via HTTP/SSE transport."""
        if not self.config.url:
            logger.error(
                f"[McpToolAdapter] No URL for HTTP transport: {self.config.name}"
            )
            return False

        transport = "sse" if self.config.transport == "sse" else "streamable_http"
        self._connection = {
            "transport": transport,
            "url": self.config.url,
            "headers": self.config.headers or {},
        }
        self._connected = True
        logger.info(
            f"[McpToolAdapter] Connected to {self.config.name} via {self.config.transport}"
        )
        return True

    async def disconnect(self) -> None:
        """Disconnect from MCP server."""
        if self._process:
            self._process.terminate()
            self._process = None
        self._connected = False
        self._connection = None
        self._tools = []
        logger.info(f"[McpToolAdapter] Disconnected from {self.config.name}")

    async def load_tools(self) -> list[BaseTool]:
        """Load tools from MCP server."""
        if not self._connected:
            await self.connect()

        if not self._connected or not self._connection:
            return []

        self._tools = await self._fetch_tools()
        return self._tools

    async def _fetch_tools(self) -> list[BaseTool]:
        """Fetch tools from MCP server using langchain-mcp-adapters."""
        try:
            from langchain_mcp_adapters.tools import load_mcp_tools

            tools = await load_mcp_tools(
                None,
                connection=self._connection,
                server_name=self.config.name,
            )

            renamed_tools = []
            for tool in tools:
                tool.name = f"{self.config.name}.{tool.name}"
                renamed_tools.append(tool)

            logger.info(
                f"[McpToolAdapter] Loaded {len(renamed_tools)} tools from {self.config.name}"
            )
            return renamed_tools

        except ImportError:
            logger.warning("[McpToolAdapter] langchain-mcp-adapters not installed")
            return []
        except Exception as e:
            logger.exception(f"[McpToolAdapter] Failed to fetch tools: {e}")
            return []

    def get_tools(self) -> list[BaseTool]:
        """Get cached tools."""
        return self._tools

    @property
    def is_connected(self) -> bool:
        return self._connected


class McpManager:
    """Manager for MCP server connections and tools."""

    _instance: "McpManager | None" = None
    _adapters: dict[str, McpToolAdapter] = {}
    _tools_cache: dict[str, list[BaseTool]] = {}
    _initialized = False

    def __new__(cls) -> "McpManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    async def init(self) -> None:
        """Initialize MCP manager and load enabled servers."""
        if self._initialized:
            return

        with SessionLocal() as db:
            servers = db.query(McpServer).filter(McpServer.enabled == True).all()

            for server in servers:
                try:
                    adapter = McpToolAdapter(server)
                    await adapter.connect()
                    self._adapters[server.name] = adapter
                    logger.info(f"[McpManager] Loaded MCP server: {server.name}")
                except Exception as e:
                    logger.error(
                        f"[McpManager] Failed to load server {server.name}: {e}"
                    )

        self._initialized = True
        logger.info(f"[McpManager] Initialized with {len(self._adapters)} servers")

    async def add_server(self, db: Session, config: dict, user_id: str) -> McpServer:
        """Add a new MCP server."""
        server = McpServer(
            id=str(uuid.uuid4()),
            name=config["name"],
            transport=config["transport"],
            command=config.get("command"),
            args=config.get("args", []),
            url=config.get("url"),
            env=config.get("env", {}),
            headers=config.get("headers", {}),
            enabled=config.get("enabled", True),
            created_by=user_id,
        )

        db.add(server)
        db.commit()
        db.refresh(server)

        if server.enabled:
            adapter = McpToolAdapter(server)
            await adapter.connect()
            self._adapters[server.name] = adapter

        logger.info(f"[McpManager] Added MCP server: {server.name}")
        return server

    async def remove_server(self, db: Session, name: str) -> bool:
        """Remove an MCP server."""
        server = db.query(McpServer).filter(McpServer.name == name).first()
        if not server:
            return False

        if name in self._adapters:
            await self._adapters[name].disconnect()
            del self._adapters[name]

        if name in self._tools_cache:
            del self._tools_cache[name]

        db.delete(server)
        db.commit()

        logger.info(f"[McpManager] Removed MCP server: {name}")
        return True

    async def update_server(
        self, db: Session, name: str, config: dict
    ) -> McpServer | None:
        """Update an MCP server configuration."""
        server = db.query(McpServer).filter(McpServer.name == name).first()
        if not server:
            return None

        if name in self._adapters:
            await self._adapters[name].disconnect()
            del self._adapters[name]

        server.transport = config.get("transport", server.transport)
        server.command = config.get("command", server.command)
        server.args = config.get("args", server.args)
        server.url = config.get("url", server.url)
        server.env = config.get("env", server.env)
        server.headers = config.get("headers", server.headers)
        server.enabled = config.get("enabled", server.enabled)

        db.commit()
        db.refresh(server)

        if server.enabled:
            adapter = McpToolAdapter(server)
            await adapter.connect()
            self._adapters[server.name] = adapter

        logger.info(f"[McpManager] Updated MCP server: {name}")
        return server

    async def get_tools(self, mcp_tool_names: list[str]) -> list[BaseTool]:
        """Get tools by their full names (mcp_name.tool_name)."""
        tools: list[BaseTool] = []

        for full_name in mcp_tool_names:
            parts = full_name.split(".", 1)
            if len(parts) != 2:
                logger.warning(f"[McpManager] Invalid tool name format: {full_name}")
                continue

            server_name, tool_name = parts

            if server_name not in self._adapters:
                logger.warning(f"[McpManager] Server not found: {server_name}")
                continue

            adapter = self._adapters[server_name]
            adapter_tools = adapter.get_tools()

            for tool in adapter_tools:
                if tool.name == full_name:
                    tools.append(tool)
                    break

        return tools

    async def get_all_tools(self, server_name: str) -> list[BaseTool]:
        """Get all tools from a specific server."""
        if server_name not in self._adapters:
            return []

        adapter = self._adapters[server_name]
        return await adapter.load_tools()

    async def test_connection(self, name: str) -> dict:
        """Test connection to an MCP server."""
        if name not in self._adapters:
            return {
                "success": False,
                "error": f"Server {name} not found",
            }

        adapter = self._adapters[name]

        try:
            tools = await adapter.load_tools()
            return {
                "success": True,
                "tools_count": len(tools),
                "tools": [
                    {"name": t.name, "description": t.description} for t in tools
                ],
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
            }

    def list_servers(self, db: Session) -> list[McpServer]:
        """List all MCP servers."""
        return db.query(McpServer).all()

    def get_server(self, db: Session, name: str) -> McpServer | None:
        """Get an MCP server by name."""
        return db.query(McpServer).filter(McpServer.name == name).first()

    async def reload(self, db: Session) -> None:
        """Reload all MCP servers from database."""
        for adapter in self._adapters.values():
            await adapter.disconnect()

        self._adapters.clear()
        self._tools_cache.clear()
        self._initialized = False

        await self.init()
        logger.info("[McpManager] Reloaded all servers")


def get_mcp_manager() -> McpManager:
    """Get the MCP manager singleton."""
    return McpManager()
