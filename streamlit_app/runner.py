from __future__ import annotations

import sys
from pathlib import Path

import streamlit.web.cli as stcli


def main() -> None:
    """Launch the Streamlit dashboard."""
    script = Path(__file__).with_name("Dashboard.py")
    sys.argv = ["streamlit", "run", str(script)]
    stcli.main()
