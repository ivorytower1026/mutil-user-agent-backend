import logging
import os
from logging.handlers import TimedRotatingFileHandler

from src.utils.get_root_path import get_project_root

_root_logger_configured = False


def get_logger(name="app"):
    global _root_logger_configured

    logger = logging.getLogger(name)

    if logger.handlers:
        return logger

    if not _root_logger_configured:
        _configure_root_logger()
        _root_logger_configured = True

    logger.setLevel(logging.DEBUG)
    logger.propagate = True

    return logger


def _configure_root_logger():
    root_logger = logging.getLogger()

    if root_logger.handlers:
        return

    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    log_to_console = os.getenv("LOG_TO_CONSOLE", "0") == "1"
    log_backup_days = int(os.getenv("LOG_BACKUP_DAYS", "30"))

    root_logger.setLevel(getattr(logging, log_level, logging.INFO))

    project_root = get_project_root()
    log_dir = os.path.join(project_root, "logs")
    os.makedirs(log_dir, exist_ok=True)

    log_path = os.path.join(log_dir, "app.log")

    file_handler = TimedRotatingFileHandler(
        log_path,
        when="midnight",
        interval=1,
        backupCount=log_backup_days,
        encoding="utf-8",
    )
    file_handler.suffix = "%Y-%m-%d"
    file_handler.setLevel(getattr(logging, log_level, logging.INFO))
    file_formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)-20s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler.setFormatter(file_formatter)
    root_logger.addHandler(file_handler)

    if log_to_console:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(getattr(logging, log_level, logging.INFO))
        console_formatter = logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(name)-20s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        console_handler.setFormatter(console_formatter)
        root_logger.addHandler(console_handler)
