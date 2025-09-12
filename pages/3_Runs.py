"""Run explorer page."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import pandas as pd
import streamlit as st

from synthap.config.settings import settings

def runs_dir() -> Path:
    """Get the runs directory path."""
    p = Path(settings.runs_dir)
    p.mkdir(parents=True, exist_ok=True)
    return p

def latest_run_id() -> Optional[str]:
    """Get the latest run ID."""
    candidates = [p.name for p in runs_dir().iterdir() if p.is_dir()]
    return sorted(candidates)[-1] if candidates else None

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
        
        # Add a seed information section
        if "seed_used" in report:
            seed = report["seed_used"]
            seed_hex = report.get("seed_hex", f"{seed:08x}")
            
            st.info(f"""
**Seed Information**
- Decimal: {seed}
- Hex: {seed_hex}

*You can use this seed with 'Custom Seed' option in Generator for reproducible results.*
            """)
            
        flat = pd.json_normalize(report)
        st.dataframe(flat, use_container_width=True)

    inv_path = base / "invoices.parquet"
    line_path = base / "invoice_lines.parquet"
    if inv_path.exists():
        st.subheader("Invoices")
        st.dataframe(pd.read_parquet(inv_path), use_container_width=True)
    if line_path.exists():
        st.subheader("Invoice lines")
        st.dataframe(pd.read_parquet(line_path), use_container_width=True)


if __name__ == "__main__":  # pragma: no cover - streamlit entry point
    main()