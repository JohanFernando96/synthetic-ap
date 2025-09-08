"""Instructions for using the Synthetic AP Streamlit frontend."""
from __future__ import annotations

import streamlit as st


def main() -> None:
    st.title("How to Use Synthetic AP")
    st.markdown(
        """
        ## Overview
        The Streamlit dashboard helps you explore catalogs, adjust runtime configuration,
        generate synthetic invoices and inspect previous runs.

        ## Getting Started
        1. Configure the application via the **Config** page.
        2. Browse vendors and items under **Catalogs**.
        3. Use **Catalog Generator** to create new catalog entries with the LLM.
        4. Plan invoice generation on **Generator** and review results under **Runs**.

        ## Tips
        - Use the *Reset data* button on the Config page to restore default YAML files.
        - Ensure your environment variables (Xero and OpenAI keys) are set before generating invoices.
        - When in doubt, consult the project README for detailed command‑line usage.
        """
    )


if __name__ == "__main__":  # pragma: no cover - streamlit entry point
    main()
