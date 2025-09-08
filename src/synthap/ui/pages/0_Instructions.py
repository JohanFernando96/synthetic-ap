"""Instructions page for the Streamlit UI."""

from __future__ import annotations

import streamlit as st


def main() -> None:
    st.title("Instructions")
    st.markdown(
        """
        ### Setup
        - Install dependencies with `poetry install` or `pip install -e .`.
        - Provide required environment variables (e.g. `OPENAI_API_KEY`, Xero OAuth settings) via a `.env` file or your shell.
        - Authenticate with Xero using `poetry run python -m synthap.cli auth-init`.

        ### Generation
        Use the **Generate invoices** page to create invoice data from an NLP query. Runs are written under `runs/<run_id>/` for review.

        ### Insertion
        Post generated invoices to a Xero sandbox with:

        ```bash
        poetry run python -m synthap.cli insert --run-id <run_id>
        ```

        ### Caveats
        - Designed for demos and sandbox environments – avoid production data.
        - LLM features incur OpenAI API usage costs.
        - Review generated invoices before inserting them into Xero.
        """
    )


if __name__ == "__main__":  # pragma: no cover - streamlit entry point
    main()
