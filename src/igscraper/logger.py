import logging
import sys
import time
from pathlib import Path

# Suppress verbose logs from selenium-wire and its dependencies
# These are set at module level to reduce noise from third-party libraries
# They run before config is loaded, but only affect specific noisy loggers
logging.getLogger('seleniumwire').setLevel(logging.WARNING)
logging.getLogger('seleniumwire.server').setLevel(logging.WARNING)
logging.getLogger('seleniumwire.storage').setLevel(logging.WARNING)
logging.getLogger('h2').setLevel(logging.WARNING)  # h2 is a dependency of selenium-wire
logging.getLogger('hpack').setLevel(logging.WARNING)  # hpack is a dependency of h2

def configure_root_logger(config: dict) -> None:
    """
    Configure the root logger with handlers and formatting, using values from a dict.

    Expected dict structure:
    {
        "logging": {
            "level": "INFO",
            "log_format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            "date_format": "%Y-%m-%d %H:%M:%S",
            "log_dir": "logs"
        }
    }
    """
    root = logging.getLogger()

    logging_cfg = config.get("logging", {})

    level_str = logging_cfg.get("level", "INFO").upper()
    level = getattr(logging, level_str, logging.INFO)
    root.setLevel(level)

    if not root.handlers:
        formatter = logging.Formatter(
            fmt=logging_cfg.get("log_format", "%(asctime)s - %(name)s - %(levelname)s - %(message)s"),
            datefmt=logging_cfg.get("date_format", "%Y-%m-%d %H:%M:%S"),
        )

        # Console handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        root.addHandler(console_handler)

        # File handler
        log_dir = Path(logging_cfg.get("log_dir", Path.cwd()))
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / f"scraper_log_{int(time.time())}.log"

        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)

        root.info(f"Logging to file: {log_file}")


def get_logger(name: str = "igscraper") -> logging.Logger:
    """
    Get a named logger that inherits root settings from config.toml [logging] section.
    
    The root logger is configured by configure_root_logger() which reads from config.toml.
    This function returns a child logger that inherits the root logger's level, handlers,
    and formatters as configured.
    
    Args:
        name: Logger name (typically __name__ of the calling module)
        
    Returns:
        A logger instance that respects config.toml [logging] settings
    """
    # Silence noisy third-party libraries (these are library-specific, not app-level)
    # These settings are independent of config.toml and only affect external library noise
    logging.getLogger("selenium").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.ERROR)
    logging.getLogger("webdriver_manager").setLevel(logging.ERROR)
    logging.getLogger("WDM").setLevel(logging.ERROR)

    return logging.getLogger(name)
