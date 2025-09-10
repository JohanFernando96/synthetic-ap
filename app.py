"""Dashboard page for the Streamlit UI."""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from synthap.catalogs.loader import load_catalogs
from synthap.cli import latest_run_id, runs_dir
from synthap.config.settings import settings
from synthap.xero.oauth import TokenStore


def _status() -> list[tuple[str, bool]]:
    """Collect basic connectivity diagnostics."""

    backend_ok = Path(settings.data_dir).exists() if settings.data_dir else False
    openai_ok = bool(settings.openai_api_key)
    xero_ok = TokenStore.load() is not None

    return [
        ("Backend", backend_ok),
        ("OpenAI", openai_ok),
        ("Xero", xero_ok),
    ]


def _last_seed() -> str | None:
    run_id = latest_run_id()
    if not run_id:
        return None
    try:
        return run_id.split("-")[-1]
    except Exception:  # pragma: no cover - defensive
        return None


def main() -> None:
    st.set_page_config(page_title="Synthetic AP", layout="wide")

    if st.session_state.pop("refresh_dashboard", False):
        st.experimental_rerun()

    st.title("Dashboard")

    seed = st.session_state.pop("last_seed", None) or _last_seed()
    try:
        cat = load_catalogs(settings.data_dir)
        vendor_count = len(cat.vendors)
        item_count = len(cat.items)
    except Exception:
        vendor_count = 0
        item_count = 0

    try:
        run_count = len([p for p in runs_dir().iterdir() if p.is_dir()])
    except Exception:
        run_count = 0

    st.subheader("Overview")
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Vendors", vendor_count)
    col2.metric("Items", item_count)
    col3.metric("Runs", run_count)
    col4.metric("Last seed", seed or "-")

    st.divider()
    st.subheader("Connections")
    status_cols = st.columns(3)
    for col, (service, ok) in zip(status_cols, _status()):
        col.metric(service, "✅" if ok else "❌")


if __name__ == "__main__":  # pragma: no cover - streamlit entry point
    main()

