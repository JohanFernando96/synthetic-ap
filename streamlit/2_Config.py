"""Configuration editor page."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st
import yaml

from synthap.config.runtime_config import (
    RuntimeConfig,
    _defaults_path,
    load_runtime_config,
    save_runtime_config,
)
from synthap.config.settings import settings


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _flatten_dict(d: dict[str, Any], parent_key: str = "", sep: str = ".") -> dict[str, Any]:
    """Flatten nested dictionaries for tabular display."""
    items: dict[str, Any] = {}
    for k, v in d.items():
        new_key = f"{parent_key}{sep}{k}" if parent_key else k
        if isinstance(v, dict):
            items.update(_flatten_dict(v, new_key, sep=sep))
        else:
            items[new_key] = v
    return items


def _unflatten_dict(d: dict[str, Any], sep: str = ".") -> dict[str, Any]:
    """Inverse of :func:`_flatten_dict` for saving edited values."""
    out: dict[str, Any] = {}
    for flat_key, value in d.items():
        parts = flat_key.split(sep)
        cursor = out
        for part in parts[:-1]:
            cursor = cursor.setdefault(part, {})
        cursor[parts[-1]] = value
    return out


def main() -> None:
    st.title("Configuration")

    defaults_cfg = RuntimeConfig(**_load_yaml(_defaults_path(settings.data_dir)))
    cfg = load_runtime_config(settings.data_dir)

    left, right = st.columns(2)
    with left:
        st.subheader("Default configuration")
        defaults_df = pd.DataFrame(
            list(_flatten_dict(defaults_cfg.model_dump()).items()),
            columns=["Setting", "Value"],
        )
        st.table(defaults_df)

    with right:
        st.subheader("Runtime configuration")
        flat_cfg = _flatten_dict(cfg.model_dump())
        cfg_df = pd.DataFrame(list(flat_cfg.items()), columns=["Setting", "Value"])
        edited_df = st.data_editor(cfg_df, disabled=["Setting"], use_container_width=True)

        col_save, col_revert = st.columns(2)
        if col_save.button("Save"):
            updated = dict(zip(edited_df["Setting"], edited_df["Value"]))
            new_dict = _unflatten_dict(updated)
            new_cfg = RuntimeConfig(**new_dict)
            save_runtime_config(new_cfg)
            st.success("Configuration saved")

        if col_revert.button("Revert to defaults"):
            save_runtime_config(defaults_cfg)
            st.warning("Runtime configuration reset to defaults")
            st.rerun()


if __name__ == "__main__":  # pragma: no cover - streamlit entry point
    main()
