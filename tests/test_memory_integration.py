"""Test memory integration."""

import sys
from pathlib import Path

# Add backend to path
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from src.database import SessionLocal
from src.memory_manager import get_memory_manager
from src.llm_manager import get_llm_manager
from src.utils.get_logger import get_logger

logger = get_logger("test-memory")


def test_memory_manager_init():
    """Test MemoryManager initialization."""
    logger.info("[Test] Testing MemoryManager initialization...")

    memory_manager = get_memory_manager()

    with SessionLocal() as db:
        memory_manager.init(db)

    logger.info("[Test] MemoryManager initialized successfully!")
    return memory_manager


def test_memory_tools_creation():
    """Test memory tools creation."""
    logger.info("[Test] Testing memory tools creation...")

    memory_manager = get_memory_manager()
    tools = memory_manager.create_tools()

    logger.info(f"[Test] Created {len(tools)} memory tools:")
    for tool in tools:
        logger.info(f"  - {tool.name}: {tool.description[:50]}...")

    assert len(tools) == 4, "Should create 4 memory tools"
    logger.info("[Test] Memory tools creation test passed!")


def test_embedding_config():
    """Test embedding config from database."""
    logger.info("[Test] Testing embedding config...")

    llm_manager = get_llm_manager()

    with SessionLocal() as db:
        config = llm_manager.get_active_config("embedding", db)

        if config:
            logger.info(f"[Test] Found active embedding config:")
            logger.info(f"  - Name: {config.name}")
            logger.info(f"  - Model: {config.model_name}")
            logger.info(f"  - Base URL: {config.base_url}")
            logger.info(f"  - Embedding Dims: {config.extra_params.get('embedding_dims')}")
        else:
            logger.warning("[Test] No active embedding config found in database")
            logger.warning("[Test] Please run: python scripts/init_embedding_config.py")


def main():
    """Run all tests."""
    logger.info("[Test] Starting memory integration tests...")
    logger.info("=" * 60)

    try:
        # Test 1: Initialize MemoryManager
        memory_manager = test_memory_manager_init()
        logger.info("")

        # Test 2: Create memory tools
        test_memory_tools_creation()
        logger.info("")

        # Test 3: Check embedding config
        test_embedding_config()
        logger.info("")

        logger.info("=" * 60)
        logger.info("[Test] All tests passed! ✅")
        logger.info("")
        logger.info("[Test] Next steps:")
        logger.info("  1. Initialize embedding config: python scripts/init_embedding_config.py")
        logger.info("  2. Start the server: uv run python main.py")
        logger.info("  3. Test memory in conversation with the agent")

    except Exception as e:
        logger.exception(f"[Test] Test failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
