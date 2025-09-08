"""Dashboard page for the Streamlit UI."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from synthap.cli import latest_run_id
from synthap.config.settings import settings
from synthap.xero.oauth import TokenStore


@st.cache_data
def _status_table() -> pd.DataFrame:
    """Collect basic connectivity diagnostics."""

    data_dir_ok = Path(settings.data_dir).exists() if settings.data_dir else False
    openai_ok = bool(settings.openai_api_key)
    xero_ok = TokenStore.load() is not None

    return pd.DataFrame(
        [
            {"service": "Data directory", "connected": data_dir_ok},
            {"service": "OpenAI", "connected": openai_ok},
            {"service": "Xero token", "connected": xero_ok},
        ]
    )


@st.cache_data
def _last_seed() -> str | None:
    run_id = latest_run_id()
    if not run_id:
        return None
    try:
        return run_id.split("-")[-1]
    except Exception:  # pragma: no cover - defensive
        return None


def main() -> None:
    st.title("Dashboard")

    seed = _last_seed()
    if seed:
        st.metric("Last generated seed", seed)
    else:
        st.info("No generation runs found.")

    st.subheader("Connectivity")
    st.table(_status_table())


if __name__ == "__main__":  # pragma: no cover - streamlit entry point
    main()

