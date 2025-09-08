"""Entry point for the Streamlit front end."""

import streamlit as st


def main() -> None:
    """Render the landing page.

    Streamlit automatically discovers additional pages placed in the
    ``pages`` directory that sits alongside this module.  The landing page is
    intentionally minimal and directs the user to the sidebar where page
    navigation lives.
    """

    st.set_page_config(page_title="Synthetic AP", layout="wide")
    st.title("Synthetic AP")
    st.write("Use the sidebar to navigate between application sections.")
    st.page_link("pages/0_Instructions", label="Setup instructions")


if __name__ == "__main__":  # pragma: no cover - streamlit entry point
    main()

