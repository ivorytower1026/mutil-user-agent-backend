from datetime import datetime
import logging
import uuid
import os

from src.utils.get_root_path import get_project_root


def get_logger(name="deepagent_stream", thread_id=None):
    """
    获取logger
    """

    if thread_id is None:
        thread_id = f"{uuid.uuid4().hex[:8]}"

    project_root = get_project_root()
    log_dir = os.path.join(project_root, "logs")
    os.makedirs(log_dir, exist_ok=True)

    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    # 防止重复添加 handler
    if not logger.handlers:
        log_path = os.path.join(
            log_dir,
            f"{name}_{datetime.now().strftime('%Y-%m-%d—%H-%M-%S')}_{thread_id}.log"
        )

        handler = logging.FileHandler(log_path, encoding="utf-8")
        formatter = logging.Formatter(
            "%(asctime)s | %(levelname)s | %(message)s"
        )
        handler.setFormatter(formatter)

        logger.addHandler(handler)

    return logger
