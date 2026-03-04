"""Agent configuration manager for loading and caching agent configs."""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from src.database import AgentConfigModel
from src.utils.get_logger import get_logger

logger = get_logger("agent-config-manager")

DEFAULT_MAIN_CONFIG = {
    "name": "main",
    "is_main": True,
    "description": "Main agent configuration",
    "system_prompt": """
用户的工作目录在/workspace中，若无明确要求，请在/workspace目录【及子目录】下执行操作,
当你不明确用户需求时，可以调用提问工具向用户提问(可以同时提多个问题)，这个提问工具最多调用两次
优先尝试使用已有的skill完成任务
""",
    "mcp_servers": [],
    "skills": [],
    "subagents": [],
    "model": None,
}


class AgentConfig:
    """Agent configuration wrapper."""

    def __init__(
        self, model: AgentConfigModel | None = None, default: dict | None = None
    ):
        if model:
            self.id = model.id
            self.name = model.name
            self.is_main = model.is_main
            self.description = model.description
            self.system_prompt = model.system_prompt
            self.mcp_servers = model.mcp_servers or []
            self.skills = model.skills or []
            self.subagents = model.subagents or []
            self.model = model.model
            self.updated_at = model.updated_at
        elif default:
            self.id = default.get("id", "default")
            self.name = default["name"]
            self.is_main = default.get("is_main", False)
            self.description = default.get("description")
            self.system_prompt = default.get("system_prompt")
            self.mcp_servers = default.get("mcp_servers", [])
            self.skills = default.get("skills", [])
            self.subagents = default.get("subagents", [])
            self.model = default.get("model")
            self.updated_at = None
        else:
            raise ValueError("Either model or default must be provided")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "is_main": self.is_main,
            "description": self.description,
            "system_prompt": self.system_prompt,
            "mcp_servers": self.mcp_servers,
            "skills": self.skills,
            "subagents": self.subagents,
            "model": self.model,
        }


class AgentConfigManager:
    """Manager for agent configurations."""

    _instance: "AgentConfigManager | None" = None
    _configs: dict[str, AgentConfig] = {}
    _last_reload: datetime | None = None

    def __new__(cls) -> "AgentConfigManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def load_configs(self, db: Session) -> dict[str, AgentConfig]:
        """Load all agent configurations from database."""
        configs = db.query(AgentConfigModel).all()

        self._configs.clear()

        main_config = None
        subagent_configs = []

        for config in configs:
            agent_config = AgentConfig(model=config)
            self._configs[config.name] = agent_config

            if config.is_main:
                main_config = agent_config
            else:
                subagent_configs.append(agent_config)

        if not main_config:
            main_config = AgentConfig(default=DEFAULT_MAIN_CONFIG)
            self._configs["main"] = main_config

        self._last_reload = datetime.now(UTC)

        logger.info(f"[AgentConfigManager] Loaded {len(self._configs)} configs")
        return self._configs

    def get_main_config(self, db: Session | None = None) -> AgentConfig:
        """Get main agent configuration."""
        if "main" not in self._configs:
            if db:
                self.load_configs(db)
            else:
                return AgentConfig(default=DEFAULT_MAIN_CONFIG)

        return self._configs.get("main", AgentConfig(default=DEFAULT_MAIN_CONFIG))

    def get_subagent_configs(self, db: Session | None = None) -> list[AgentConfig]:
        """Get all subagent configurations."""
        if not self._configs and db:
            self.load_configs(db)

        return [c for c in self._configs.values() if not c.is_main]

    def get_config(self, name: str, db: Session | None = None) -> AgentConfig | None:
        """Get a specific agent configuration by name."""
        if not self._configs and db:
            self.load_configs(db)

        return self._configs.get(name)

    def update_main_config(self, db: Session, config_data: dict) -> AgentConfig:
        """Update main agent configuration."""
        config = (
            db.query(AgentConfigModel).filter(AgentConfigModel.is_main == True).first()
        )

        if not config:
            config = AgentConfigModel(
                id=str(uuid.uuid4()),
                name="main",
                is_main=True,
                system_prompt=config_data.get(
                    "system_prompt", DEFAULT_MAIN_CONFIG["system_prompt"]
                ),
                mcp_servers=config_data.get("mcp_servers", []),
                skills=config_data.get("skills", []),
                subagents=config_data.get("subagents", []),
                model=config_data.get("model"),
            )
            db.add(config)
        else:
            if "system_prompt" in config_data:
                config.system_prompt = config_data["system_prompt"]
            if "mcp_servers" in config_data:
                config.mcp_servers = config_data["mcp_servers"]
            if "skills" in config_data:
                config.skills = config_data["skills"]
            if "subagents" in config_data:
                config.subagents = config_data["subagents"]
            if "model" in config_data:
                config.model = config_data["model"]

        db.commit()
        db.refresh(config)

        self._configs["main"] = AgentConfig(model=config)
        logger.info("[AgentConfigManager] Updated main config")

        return self._configs["main"]

    def create_subagent(self, db: Session, config_data: dict) -> AgentConfig:
        """Create a new subagent configuration."""
        name = config_data["name"]

        existing = (
            db.query(AgentConfigModel).filter(AgentConfigModel.name == name).first()
        )
        if existing:
            raise ValueError(f"Subagent with name '{name}' already exists")

        config = AgentConfigModel(
            id=str(uuid.uuid4()),
            name=name,
            is_main=False,
            description=config_data.get("description"),
            system_prompt=config_data.get("system_prompt"),
            mcp_servers=config_data.get("mcp_servers", []),
            skills=config_data.get("skills", []),
            subagents=[],
            model=config_data.get("model"),
        )

        db.add(config)
        db.commit()
        db.refresh(config)

        agent_config = AgentConfig(model=config)
        self._configs[name] = agent_config

        logger.info(f"[AgentConfigManager] Created subagent: {name}")
        return agent_config

    def update_subagent(self, db: Session, name: str, config_data: dict) -> AgentConfig:
        """Update a subagent configuration."""
        config = (
            db.query(AgentConfigModel)
            .filter(AgentConfigModel.name == name, AgentConfigModel.is_main == False)
            .first()
        )

        if not config:
            raise ValueError(f"Subagent '{name}' not found")

        if "description" in config_data:
            config.description = config_data["description"]
        if "system_prompt" in config_data:
            config.system_prompt = config_data["system_prompt"]
        if "mcp_servers" in config_data:
            config.mcp_servers = config_data["mcp_servers"]
        if "skills" in config_data:
            config.skills = config_data["skills"]
        if "model" in config_data:
            config.model = config_data["model"]

        db.commit()
        db.refresh(config)

        self._configs[name] = AgentConfig(model=config)
        logger.info(f"[AgentConfigManager] Updated subagent: {name}")

        return self._configs[name]

    def delete_subagent(self, db: Session, name: str) -> bool:
        """Delete a subagent configuration."""
        config = (
            db.query(AgentConfigModel)
            .filter(AgentConfigModel.name == name, AgentConfigModel.is_main == False)
            .first()
        )

        if not config:
            return False

        db.delete(config)
        db.commit()

        if name in self._configs:
            del self._configs[name]

        main_config = self._configs.get("main")
        if main_config and name in main_config.subagents:
            main_config.subagents.remove(name)
            self.update_main_config(db, {"subagents": main_config.subagents})

        logger.info(f"[AgentConfigManager] Deleted subagent: {name}")
        return True

    def reload_if_needed(self, db: Session) -> bool:
        """Check if configs need reload and reload if necessary."""
        if not self._configs:
            self.load_configs(db)
            return True

        config = db.query(AgentConfigModel).first()
        if config and config.updated_at:
            if self._last_reload is None or config.updated_at > self._last_reload:
                self.load_configs(db)
                return True

        return False

    def get_all_configs(self, db: Session) -> dict[str, Any]:
        """Get all configurations in a structured format."""
        if not self._configs:
            self.load_configs(db)

        main_config = self.get_main_config(db)
        subagent_configs = self.get_subagent_configs(db)

        return {
            "main": main_config.to_dict(),
            "subagents": [c.to_dict() for c in subagent_configs],
        }


def get_agent_config_manager() -> AgentConfigManager:
    """Get the agent config manager singleton."""
    return AgentConfigManager()
