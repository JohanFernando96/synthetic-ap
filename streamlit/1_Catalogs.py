"""Catalog browsing page."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from synthap.catalogs.loader import load_catalogs
from synthap.config.settings import settings


def _as_df(records: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(records)


def main() -> None:
    st.set_page_config(page_title="Catalogs", layout="wide")

    if st.session_state.pop("refresh_catalog", False):
        st.rerun()

    st.title("Catalogs")

    cat = load_catalogs(settings.data_dir)

    vendors_tab, items_tab, mapping_tab = st.tabs([
        "Vendors",
        "Items",
        "Vendor items",
    ])

    with vendors_tab:
        st.dataframe(
            _as_df([v.model_dump() for v in cat.vendors]),
            use_container_width=True,
            hide_index=True,
        )

    with items_tab:
        st.dataframe(
            _as_df([i.model_dump() for i in cat.items]),
            use_container_width=True,
            hide_index=True,
        )

    with mapping_tab:
        vi = [
            {"vendor_id": vid, "item_codes": ", ".join(codes)}
            for vid, codes in cat.vendor_items.items()
        ]
        st.dataframe(
            _as_df(vi),
            use_container_width=True,
            hide_index=True,
        )


if __name__ == "__main__":  # pragma: no cover - streamlit entry point
    main()
