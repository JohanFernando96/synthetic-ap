"""Initialize package-wide logging configuration."""

from __future__ import annotations

import logging
from pathlib import Path

from .config.settings import settings


def _configure_logging() -> None:
    log_dir = Path(getattr(settings, "logs_dir", "logs"))
    log_dir.mkdir(parents=True, exist_ok=True)

    system_handler = logging.FileHandler(log_dir / "system.log")
    system_handler.setLevel(logging.INFO)
    error_handler = logging.FileHandler(log_dir / "error.log")
    error_handler.setLevel(logging.ERROR)

    fmt = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    system_handler.setFormatter(fmt)
    error_handler.setFormatter(fmt)

    root = logging.getLogger()
    if not root.handlers:
        root.setLevel(logging.INFO)
        root.addHandler(system_handler)
        root.addHandler(error_handler)


_configure_logging()
