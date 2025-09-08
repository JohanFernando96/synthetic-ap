import json
from pathlib import Path

import streamlit as st

from synthap.cli import logs_dir, runs_dir


def _available_runs() -> list[str]:
    return sorted([p.name for p in runs_dir().iterdir() if p.is_dir()])

def _load_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _load_text(path: Path) -> str | None:
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")

def main() -> None:
    st.title("Logs")
    run_ids = _available_runs()
    if run_ids:
        selected = st.selectbox("Run", run_ids)
        base = runs_dir() / selected
        xero_log = _load_json(base / "xero_log.json")
        if xero_log:
            st.subheader("Xero log")
            st.json(xero_log)
        else:
            st.info("No xero_log.json for this run.")
    else:
        st.info("No runs available. Generate invoices first.")

    st.subheader("System logs")
    sys_text = _load_text(logs_dir() / "system.log")
    err_text = _load_text(logs_dir() / "error.log")
    if sys_text:
        st.expander("system.log").code(sys_text)
    if err_text:
        st.expander("error.log").code(err_text)
    if not sys_text and not err_text:
        st.info("No system logs found.")


if __name__ == "__main__":  # pragma: no cover - streamlit entry point
    main()
