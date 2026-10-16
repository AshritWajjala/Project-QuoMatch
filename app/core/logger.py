import logging
import sys
from pathlib import Path
from logging.handlers import RotatingFileHandler

DEFAULT_FORMAT = "%(asctime)s [%(levelname)s] [%(name)s]: %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

def setup_logger(
    name: str = "app",
    log_file: str = "logs/app.log",
    level: int = logging.INFO,
    max_bytes: int = 10 * 1024 * 1024,  # 10 MB per file
    backup_count: int = 5,
) -> logging.Logger:
    """Configures and returns a centralized logger with console and rotating file output.
    
    Sub-modules should use:
        logger = logging.getLogger(__name__)
    As long as the root or top-level package logger ('app') is initialized,
    all child logs will automatically flow through these handlers.
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)

    # Avoid adding duplicate handlers on multiple imports/calls
    if not logger.handlers:
        formatter = logging.Formatter(DEFAULT_FORMAT, datefmt=DATE_FORMAT)

        # 1. Console Handler (stdout)
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

        # 2. Rotating File Handler
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        file_handler = RotatingFileHandler(
            log_path,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger