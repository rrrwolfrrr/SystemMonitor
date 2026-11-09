"""Centralized diagnostic logging for SystemMonitor."""

import logging
import os
from logging.handlers import RotatingFileHandler

DEFAULT_MAX_BYTES = 10 * 1024 * 1024
DEFAULT_BACKUP_COUNT = 5


def configure_logging(log_file: str, debug: bool = False) -> logging.Logger:
    """Configure application-wide rotating logs and return the root logger."""
    log_path = os.path.abspath(log_file)
    log_dir = os.path.dirname(log_path)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)

    root = logging.getLogger()
    if getattr(root, "_system_monitor_logging_configured", False):
        return root
    root.setLevel(logging.DEBUG)
    logging.getLogger("websockets").setLevel(logging.WARNING)

    formatter = logging.Formatter(
        "%(asctime)s.%(msecs)03d | %(levelname)-8s | "
        "%(name)s | %(module)s:%(lineno)d | %(threadName)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handlers = [
        RotatingFileHandler(
            log_path,
            maxBytes=DEFAULT_MAX_BYTES,
            backupCount=DEFAULT_BACKUP_COUNT,
            encoding="utf-8",
        ),
        logging.StreamHandler(),
    ]

    handlers[0].setLevel(logging.DEBUG)
    handlers[1].setLevel(logging.DEBUG if debug else logging.INFO)
    for handler in handlers:
        handler.setFormatter(formatter)
        root.addHandler(handler)

    root._system_monitor_logging_configured = True
    logging.captureWarnings(True)
    logging.getLogger(__name__).debug(
        "Расширенное логирование настроено: file=%s debug=%s",
        log_path,
        debug,
    )
    return root


def get_log_path(log_file: str) -> str:
    """Return the absolute path used by the configured log file."""
    return os.path.abspath(log_file)
