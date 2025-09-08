"""Configuration viewer page."""

from __future__ import annotations

import yaml
import streamlit as st

from synthap.config.runtime_config import _defaults_path, _runtime_path
from synthap.config.settings import settings


def _load(path) -> dict:
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def main() -> None:
    st.title("Configuration")
    defaults = _load(_defaults_path(settings.data_dir))
    runtime = _load(_runtime_path(settings.data_dir))

    st.subheader("Service defaults")
    st.json(defaults)

    st.subheader("Runtime configuration")
    st.json(runtime)


if __name__ == "__main__":  # pragma: no cover - streamlit entry point
    main()

