"""Catalog generation page."""

from __future__ import annotations

import asyncio

import streamlit as st

from synthap.catalogs.generator import generate_catalogs
from synthap.config.settings import settings


def main() -> None:
    st.title("Generate catalogs")

    with st.form("cat_gen_form"):
        industry = st.text_input("Industry")
        contacts = st.number_input("Number of vendors", min_value=1, value=1)
        items = st.number_input("Items per vendor", min_value=1, value=1)
        submitted = st.form_submit_button("Generate")

    if submitted and industry:
        asyncio.run(
            generate_catalogs(industry, int(contacts), int(items), settings.data_dir)
        )
        st.success("Catalog data generated")


if __name__ == "__main__":  # pragma: no cover - streamlit entry point
    main()

