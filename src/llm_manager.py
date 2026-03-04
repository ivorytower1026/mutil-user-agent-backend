"""LLM Manager for dynamic LLM configuration."""

import uuid
import threading
from typing import Optional

from langchain_openai import ChatOpenAI
from sqlalchemy.orm import Session

from src.config import get_fallback_big_llm, get_fallback_flash_llm
from src.database import LlmConfig
from src.utils.get_logger import get_logger

logger = get_logger("llm-manager")


class LLMManager:
    """Dynamic LLM configuration manager with caching and fallback support."""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._cache: dict[str, ChatOpenAI] = {}
                    cls._instance._cache_lock = threading.Lock()
        return cls._instance

    def get_big_llm(self, db: Session) -> ChatOpenAI:
        """Get big LLM instance (main model)."""
        return self._get_llm_by_role("big", db)

    def get_flash_llm(self, db: Session) -> ChatOpenAI:
        """Get flash LLM instance (fast model)."""
        return self._get_llm_by_role("flash", db)

    def _get_llm_by_role(self, role: str, db: Session) -> ChatOpenAI:
        """Get LLM instance by role with caching."""
        with self._cache_lock:
            if role in self._cache:
                return self._cache[role]

        try:
            config = (
                db.query(LlmConfig)
                .filter(LlmConfig.role == role, LlmConfig.is_active == True)
                .first()
            )

            if config:
                llm = self._create_llm(config)
                with self._cache_lock:
                    self._cache[role] = llm
                logger.info(
                    f"[LLMManager] Using DB config for role={role}: {config.name}"
                )
                return llm
        except Exception as e:
            logger.warning(f"[LLMManager] Failed to get DB config: {e}")

        fallback_llm = self._get_fallback_llm(role)
        logger.info(f"[LLMManager] Using fallback for role={role}")
        return fallback_llm

    def _create_llm(self, config: LlmConfig) -> ChatOpenAI:
        """Create LLM instance from config."""
        kwargs = {
            "model": config.model_name,
            "base_url": config.base_url,
            "api_key": config.api_key,
            "temperature": config.temperature,
        }

        if config.max_tokens:
            kwargs["max_tokens"] = config.max_tokens

        if config.extra_params:
            for key, value in config.extra_params.items():
                if key not in kwargs:
                    kwargs[key] = value

        return ChatOpenAI(**kwargs)

    def _get_fallback_llm(self, role: str) -> ChatOpenAI:
        """Get fallback LLM from environment variables."""
        if role == "big":
            return get_fallback_big_llm()
        return get_fallback_flash_llm()

    def invalidate_cache(self, role: str | None = None):
        """Invalidate cache when config changes."""
        with self._cache_lock:
            if role:
                self._cache.pop(role, None)
                logger.info(f"[LLMManager] Cache invalidated for role={role}")
            else:
                self._cache.clear()
                logger.info("[LLMManager] All cache invalidated")

    def get_active_config(self, role: str, db: Session) -> Optional[LlmConfig]:
        """Get active config for a role."""
        return (
            db.query(LlmConfig)
            .filter(LlmConfig.role == role, LlmConfig.is_active == True)
            .first()
        )

    def activate_config(self, config_id: str, db: Session) -> Optional[LlmConfig]:
        """Activate a config and deactivate others with same role."""
        config = db.query(LlmConfig).filter(LlmConfig.id == config_id).first()
        if not config:
            return None

        db.query(LlmConfig).filter(
            LlmConfig.role == config.role, LlmConfig.is_active == True
        ).update({"is_active": False})

        config.is_active = True
        db.commit()

        self.invalidate_cache(config.role)

        logger.info(
            f"[LLMManager] Activated config: {config.name} for role={config.role}"
        )
        return config

    def create_config(
        self,
        db: Session,
        name: str,
        provider: str,
        base_url: str,
        api_key: str,
        model_name: str,
        role: str,
        display_name: str | None = None,
        description: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        extra_params: dict | None = None,
        created_by: str | None = None,
        activate: bool = False,
    ) -> LlmConfig:
        """Create a new LLM config."""
        config = LlmConfig(
            id=str(uuid.uuid4()),
            name=name,
            display_name=display_name,
            description=description,
            provider=provider,
            base_url=base_url,
            api_key=api_key,
            model_name=model_name,
            temperature=temperature,
            max_tokens=max_tokens,
            extra_params=extra_params or {},
            role=role,
            is_active=activate,
            created_by=created_by,
        )

        if activate:
            db.query(LlmConfig).filter(
                LlmConfig.role == role, LlmConfig.is_active == True
            ).update({"is_active": False})

        db.add(config)
        db.commit()
        db.refresh(config)

        if activate:
            self.invalidate_cache(role)

        logger.info(f"[LLMManager] Created config: {name} for role={role}")
        return config

    def update_config(
        self,
        db: Session,
        config_id: str,
        display_name: str | None = None,
        description: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
        model_name: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        extra_params: dict | None = None,
    ) -> Optional[LlmConfig]:
        """Update an existing LLM config."""
        config = db.query(LlmConfig).filter(LlmConfig.id == config_id).first()
        if not config:
            return None

        if display_name is not None:
            config.display_name = display_name
        if description is not None:
            config.description = description
        if base_url is not None:
            config.base_url = base_url
        if api_key is not None:
            config.api_key = api_key
        if model_name is not None:
            config.model_name = model_name
        if temperature is not None:
            config.temperature = temperature
        if max_tokens is not None:
            config.max_tokens = max_tokens
        if extra_params is not None:
            config.extra_params = extra_params

        db.commit()
        db.refresh(config)

        if config.is_active:
            self.invalidate_cache(config.role)

        logger.info(f"[LLMManager] Updated config: {config.name}")
        return config

    def delete_config(self, db: Session, config_id: str) -> bool:
        """Delete an LLM config."""
        config = db.query(LlmConfig).filter(LlmConfig.id == config_id).first()
        if not config:
            return False

        role = config.role
        was_active = config.is_active

        db.delete(config)
        db.commit()

        if was_active:
            self.invalidate_cache(role)

        logger.info(f"[LLMManager] Deleted config: {config.name}")
        return True

    def list_configs(
        self, db: Session, role: str | None = None, provider: str | None = None
    ) -> list[LlmConfig]:
        """List all LLM configs with optional filters."""
        query = db.query(LlmConfig)

        if role:
            query = query.filter(LlmConfig.role == role)
        if provider:
            query = query.filter(LlmConfig.provider == provider)

        return query.order_by(LlmConfig.created_at.desc()).all()

    async def test_connection(
        self, base_url: str, api_key: str, model_name: str, timeout: int = 10
    ) -> dict:
        """Test LLM connection."""
        import time

        try:
            llm = ChatOpenAI(
                model=model_name,
                base_url=base_url,
                api_key=api_key,
                temperature=0,
                max_tokens=10,
                request_timeout=timeout,
            )

            start_time = time.time()
            response = await llm.ainvoke("Hi")
            elapsed_ms = int((time.time() - start_time) * 1000)

            return {
                "success": True,
                "message": "Connection successful",
                "response_time_ms": elapsed_ms,
                "response_preview": str(response.content)[:100] if response else None,
            }
        except Exception as e:
            return {"success": False, "message": str(e), "response_time_ms": None}

    async def test_embedding_connection(
        self, base_url: str, api_key: str, model_name: str, timeout: int = 10
    ) -> dict:
        """Test embedding model connection.

        Args:
            base_url: API base URL
            api_key: API key
            model_name: Embedding model name
            timeout: Request timeout in seconds

        Returns:
            Test result with vector dimension info
        """
        import time
        from langchain_openai import OpenAIEmbeddings

        try:
            embeddings = OpenAIEmbeddings(
                model=model_name,
                openai_api_base=base_url,
                openai_api_key=api_key,
            )

            start_time = time.time()
            # Test embedding a simple text
            result = await embeddings.aembed_query("test connection")
            elapsed_ms = int((time.time() - start_time) * 1000)

            return {
                "success": True,
                "message": "Embedding connection successful",
                "response_time_ms": elapsed_ms,
                "vector_dim": len(result),
                "vector_preview": result[:5],  # First 5 dimensions as preview
            }
        except Exception as e:
            return {"success": False, "message": str(e), "response_time_ms": None}


_llm_manager: LLMManager | None = None


def get_llm_manager() -> LLMManager:
    """Get LLM manager singleton."""
    global _llm_manager
    if _llm_manager is None:
        _llm_manager = LLMManager()
    return _llm_manager
