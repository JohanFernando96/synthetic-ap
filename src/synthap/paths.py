"""Path utilities for the application."""

from __future__ import annotations
from pathlib import Path
from typing import Optional

from . import runs_dir

def latest_run_id() -> Optional[str]:
    """Get the latest run ID."""
    candidates = [p.name for p in runs_dir().iterdir() if p.is_dir()]
    return sorted(candidates)[-1] if candidates else None