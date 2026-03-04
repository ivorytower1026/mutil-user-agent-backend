#!/usr/bin/env python3
"""Initialize Embedding configuration in database."""

import sys
from pathlib import Path

# Add backend to path
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from src.database import SessionLocal
from src.llm_manager import get_llm_manager
from src.utils.get_logger import get_logger

logger = get_logger("init-embedding-config")


def init_embedding_config():
    """Initialize default embedding configuration."""
    llm_manager = get_llm_manager()

    with SessionLocal() as db:
        # Check if embedding config already exists
        existing_configs = llm_manager.list_configs(db, role="embedding")

        if existing_configs:
            logger.info("[Init] Embedding config already exists:")
            for config in existing_configs:
                status = "active" if config.is_active else "inactive"
                logger.info(f"  - {config.name} ({status})")
            return

        # Create default embedding config
        logger.info("[Init] Creating default embedding config...")

        config = llm_manager.create_config(
            db=db,
            name="qwen3-embedding-0.6b",
            provider="openai",
            base_url="http://192.168.110.44:8008/v1",
            api_key="dummy-key",
            model_name="Qwen3-Embedding-0.6B",
            role="embedding",
            display_name="Qwen3 Embedding 0.6B",
            description="Embedding模型用于向量化文本",
            temperature=0,
            max_tokens=512,
            extra_params={"embedding_dims": 1024},
            activate=True,
        )

        logger.info(f"[Init] Created embedding config: {config.id}")
        logger.info(f"[Init] Name: {config.name}")
        logger.info(f"[Init] Model: {config.model_name}")
        logger.info(f"[Init] Base URL: {config.base_url}")
        logger.info(f"[Init] Embedding Dims: {config.extra_params.get('embedding_dims')}")
        logger.info("[Init] Embedding config initialized successfully!")


if __name__ == "__main__":
    try:
        init_embedding_config()
    except Exception as e:
        logger.exception(f"[Init] Failed to initialize embedding config: {e}")
        sys.exit(1)
