"""Configuration viewer page."""

from __future__ import annotations

import pandas as pd
import yaml
import streamlit as st

from synthap.config.runtime_config import (
    RuntimeConfig,
    _defaults_path,
    _runtime_path,
    save_runtime_config,
)
from synthap.config.settings import settings


def _load(path) -> dict:
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _flatten(d: dict, prefix: str = "") -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for k, v in d.items():
        key = f"{prefix}{k}" if not prefix else f"{prefix}.{k}"
        if isinstance(v, dict):
            rows.extend(_flatten(v, key))
        else:
            rows.append({"key": key, "value": v})
    return rows


def _unflatten(rows: list[dict[str, object]]) -> dict:
    out: dict[str, object] = {}
    for row in rows:
        parts = str(row.get("key", "")).split(".")
        cur = out
        for part in parts[:-1]:
            cur = cur.setdefault(part, {})
        cur[parts[-1]] = row.get("value")
    return out


def main() -> None:
    st.title("Configuration")
    defaults = _load(_defaults_path(settings.data_dir))
    runtime_raw = _load(_runtime_path(settings.data_dir))

    st.subheader("Service defaults")
    st.dataframe(pd.DataFrame(_flatten(defaults)))

    st.subheader("Runtime configuration")
    runtime_rows = _flatten(runtime_raw)
    edited = st.data_editor(pd.DataFrame(runtime_rows), num_rows="dynamic", use_container_width=True)

    col1, col2 = st.columns(2)
    with col1:
        if st.button("Save"):
            rows = edited.to_dict("records")
            cfg = RuntimeConfig(**_unflatten(rows))
            save_runtime_config(cfg)
            st.success("Configuration saved")
    with col2:
        if st.button("Revert to defaults"):
            _runtime_path(settings.data_dir).unlink(missing_ok=True)
            st.warning("Runtime configuration reset")


if __name__ == "__main__":  # pragma: no cover - streamlit entry point
    main()

