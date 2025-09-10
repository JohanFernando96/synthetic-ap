"""Dashboard entry point for the Streamlit UI."""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from synthap.catalogs.loader import load_catalogs

from synthap.cli import runs_dir
from synthap.config.settings import settings


def main() -> None:
    """Render the overview dashboard."""
    st.set_page_config(page_title="Synthetic AP", layout="wide")

    if st.session_state.pop("refresh_dashboard", False):
        st.experimental_rerun()

    st.title("Dashboard")

    cat = load_catalogs(settings.data_dir)
    vendor_count = len(cat.vendors)
    item_count = len(cat.items)
    run_count = len([p for p in runs_dir().iterdir() if p.is_dir()])
    last_seed = st.session_state.get("last_seed", "—")

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Vendors", vendor_count)
    m2.metric("Items", item_count)
    m3.metric("Runs", run_count)
    m4.metric("Last seed", last_seed)

    st.subheader("Connections")
    token_file = settings.token_file or ".xero_token.json"
    backend_ok = True  # catalogs loaded successfully
    openai_ok = bool(settings.openai_api_key)
    xero_ok = Path(token_file).exists()

    c1, c2, c3 = st.columns(3)
    c1.metric("Backend", "OK" if backend_ok else "Unavailable")
    c2.metric("OpenAI", "OK" if openai_ok else "Missing API key")
    c3.metric("Xero", "OK" if xero_ok else "No token")


if __name__ == "__main__":  # pragma: no cover - streamlit entry point
    main()
