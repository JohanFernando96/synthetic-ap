from __future__ import annotations

from pathlib import Path
import subprocess


def reset_all(base_dir: str) -> None:
    """Revert catalog and config YAMLs back to repository defaults.

    Parameters
    ----------
    base_dir:
        Base data directory containing ``catalogs`` and ``config``.
    """
    base = Path(base_dir)
    for sub in ("catalogs", "config"):
        path = base / sub
        if path.exists():
            # restore tracked files
            subprocess.run(["git", "checkout", "--", str(path)], check=True)
            # remove untracked files beneath the directory
            subprocess.run(["git", "clean", "-f", str(path)], check=True)
