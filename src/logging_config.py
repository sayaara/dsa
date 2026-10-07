# -*- coding: utf-8 -*-
"""
===================================
Logging configuration module - shared logging system initialisation
===================================

Responsibilities:
1. Provide the shared log format and configuration constants
2. Support three-tier output: console plus regular and debug files
3. Lower the log level of third-party libraries automatically
"""

import logging
import os
import sys
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import List, Optional, Tuple


LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(pathname)s:%(lineno)d | %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
_ALLOWED_LOG_LEVELS = {
    'DEBUG': logging.DEBUG,
    'INFO': logging.INFO,
    'WARNING': logging.WARNING,
    'ERROR': logging.ERROR,
    'CRITICAL': logging.CRITICAL,
}
_DEFAULT_LITELLM_LOG_LEVEL = 'WARNING'


class RelativePathFormatter(logging.Formatter):
    """Custom formatter that prints relative paths instead of absolute ones"""

    def __init__(self, fmt=None, datefmt=None, relative_to=None):
        super().__init__(fmt, datefmt)
        self.relative_to = Path(relative_to) if relative_to else Path.cwd()

    def format(self, record):
        # Convert the absolute path into a relative one
        try:
            record.pathname = str(Path(record.pathname).relative_to(self.relative_to))
        except ValueError:
            # Leave it as-is when it cannot be made relative
            pass
        return super().format(record)


# Third-party libraries whose log level is lowered by default
DEFAULT_QUIET_LOGGERS = [
    'urllib3',
    'sqlalchemy',
    'google',
    'httpx',
]

LITELLM_LOGGERS = [
    'LiteLLM',
    'LiteLLM Router',
    'LiteLLM Proxy',
    'litellm',
]


def _resolve_litellm_log_level(raw_level: Optional[str] = None) -> Tuple[int, Optional[str]]:
    """Resolve LiteLLM logger level from env, returning invalid raw value if any."""
    if raw_level is None:
        raw_level = os.getenv('LITELLM_LOG_LEVEL', '')

    normalized = (raw_level or '').strip().upper()
    if not normalized:
        normalized = _DEFAULT_LITELLM_LOG_LEVEL

    level = _ALLOWED_LOG_LEVELS.get(normalized)
    if level is None:
        return _ALLOWED_LOG_LEVELS[_DEFAULT_LITELLM_LOG_LEVEL], raw_level
    return level, None


def setup_logging(
    log_prefix: str = "app",
    log_dir: str = "./logs",
    console_level: Optional[int] = None,
    debug: bool = False,
    extra_quiet_loggers: Optional[List[str]] = None,
) -> None:
    """
    Shared logging system initialisation

    Configures three tiers of log output:
    1. Console: level taken from the debug argument or console_level
    2. Regular log file: INFO level, 10MB rotation, 5 backups kept
    3. Debug log file: DEBUG level, 50MB rotation, 3 backups kept

    Args:
        log_prefix: log file name prefix (e.g. "api_server" -> api_server_20240101.log)
        log_dir: log file directory, defaults to ./logs
        console_level: console log level (optional; takes precedence over debug)
        debug: whether to enable debug mode (console output at DEBUG level)
        extra_quiet_loggers: extra third-party libraries whose log level should be lowered
    """
    # Resolve the console log level
    if console_level is not None:
        level = console_level
    else:
        level = logging.DEBUG if debug else logging.INFO

    # Create the log directory
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    # Log file paths (one file per day)
    today_str = datetime.now().strftime('%Y%m%d')
    log_file = log_path / f"{log_prefix}_{today_str}.log"
    debug_log_file = log_path / f"{log_prefix}_debug_{today_str}.log"

    # Configure the root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)  # root logger at DEBUG; the handlers decide what is emitted

    # Clear existing handlers so none are added twice
    if root_logger.handlers:
        root_logger.handlers.clear()
    # Create the relative-path formatter (relative to the project root)
    project_root = Path.cwd()
    rel_formatter = RelativePathFormatter(
        LOG_FORMAT, LOG_DATE_FORMAT, relative_to=project_root
    )
    # Handler 1: console output
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(rel_formatter)
    root_logger.addHandler(console_handler)

    # Handler 2: regular log file (INFO level, 10MB rotation)
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=5,
        encoding='utf-8'
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(rel_formatter)
    root_logger.addHandler(file_handler)

    # Handler 3: debug log file (DEBUG level, every detail included)
    debug_handler = RotatingFileHandler(
        debug_log_file,
        maxBytes=50 * 1024 * 1024,  # 50MB
        backupCount=3,
        encoding='utf-8'
    )
    debug_handler.setLevel(logging.DEBUG)
    debug_handler.setFormatter(rel_formatter)
    root_logger.addHandler(debug_handler)

    # Lower the log level of third-party libraries
    quiet_loggers = DEFAULT_QUIET_LOGGERS.copy()
    if extra_quiet_loggers:
        quiet_loggers.extend(extra_quiet_loggers)

    for logger_name in quiet_loggers:
        logging.getLogger(logger_name).setLevel(logging.WARNING)

    litellm_level, invalid_litellm_level = _resolve_litellm_log_level()
    for logger_name in LITELLM_LOGGERS:
        logging.getLogger(logger_name).setLevel(litellm_level)

    # Report that initialisation finished (using relative paths)
    try:
        rel_log_path = log_path.resolve().relative_to(project_root)
    except ValueError:
        rel_log_path = log_path

    try:
        rel_log_file = log_file.resolve().relative_to(project_root)
    except ValueError:
        rel_log_file = log_file

    try:
        rel_debug_log_file = debug_log_file.resolve().relative_to(project_root)
    except ValueError:
        rel_debug_log_file = debug_log_file

    logging.info(f"Logging initialized, log directory: {rel_log_path}")
    logging.info(f"Regular log: {rel_log_file}")
    logging.info(f"Debug log: {rel_debug_log_file}")
    if invalid_litellm_level is not None:
        logging.warning(
            "LITELLM_LOG_LEVEL=%r is invalid, falling back to %s; allowed values: %s",
            invalid_litellm_level,
            _DEFAULT_LITELLM_LOG_LEVEL,
            ", ".join(_ALLOWED_LOG_LEVELS),
        )
