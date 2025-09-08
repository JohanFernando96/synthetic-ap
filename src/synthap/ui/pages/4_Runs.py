"""Run explorer page."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

from synthap.cli import runs_dir


def _available_runs() -> list[str]:
    return sorted([p.name for p in runs_dir().iterdir() if p.is_dir()])


def _load_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def main() -> None:
    st.title("Generated Runs")
    run_ids = _available_runs()
    if not run_ids:
        st.info("No runs available. Generate invoices first.")
        return

    selected = st.selectbox("Run", run_ids)
    base = runs_dir() / selected

    st.write(f"Run directory: {base}")

    report = _load_json(base / "generation_report.json")
    if report:
        st.subheader("Generation report")
        st.json(report)

    inv_path = base / "invoices.parquet"
    line_path = base / "invoice_lines.parquet"
    if inv_path.exists():
        st.subheader("Invoices")
        st.dataframe(pd.read_parquet(inv_path))
    if line_path.exists():
        st.subheader("Invoice lines")
        st.dataframe(pd.read_parquet(line_path))


if __name__ == "__main__":  # pragma: no cover - streamlit entry point
    main()

