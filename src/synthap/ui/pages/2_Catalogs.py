"""Catalog browsing page."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from synthap.catalogs.loader import load_catalogs
from synthap.config.settings import settings


def _as_df(records: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(records)


def main() -> None:
    st.title("Catalogs")
    cat = load_catalogs(settings.data_dir)

    st.subheader("Vendors")
    st.dataframe(_as_df([v.model_dump() for v in cat.vendors]))

    st.subheader("Items")
    st.dataframe(_as_df([i.model_dump() for i in cat.items]))

    st.subheader("Vendor items")
    vi = [{"vendor_id": vid, "item_codes": ", ".join(codes)} for vid, codes in cat.vendor_items.items()]
    st.dataframe(_as_df(vi))


if __name__ == "__main__":  # pragma: no cover - streamlit entry point
    main()

