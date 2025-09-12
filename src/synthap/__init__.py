"""Synthetic AP - Core package initialization."""

from __future__ import annotations
from pathlib import Path

from .config.settings import settings

def runs_dir() -> Path:
    """Get the runs directory path."""
    p = Path(settings.runs_dir)
    p.mkdir(parents=True, exist_ok=True)
    return p