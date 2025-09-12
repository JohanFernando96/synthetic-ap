"""Logs viewing page."""

from __future__ import annotations

import pandas as pd
import streamlit as st
from datetime import datetime, timedelta

from synthap.logs import read_logs, logs_dir


def format_log_entries(logs, colorize=True):
    """Format log entries for display with optional colorization."""
    if not logs:
        return pd.DataFrame()
    
    df = pd.DataFrame(logs)
    
    # Add a column for styling
    if colorize:
        # Add color coding based on log level
        def color_level(level):
            if level == "ERROR":
                return "background-color: #ffcccc"
            elif level == "WARNING":
                return "background-color: #fff2cc"
            elif level == "INFO":
                return "background-color: #e6f3ff"
            elif level == "DEBUG":
                return "background-color: #e6ffe6"
            return ""
        
        # Apply the styling
        styled_df = df.style.apply(
            lambda row: [color_level(row["level"]) if col == "level" else "" for col in df.columns], 
            axis=1
        )
        return styled_df
    
    return df


def render_log_tab(log_type: str):
    """Render a tab for a specific log type with filtering options."""
    # Get the current date for default time ranges
    today = datetime.now()
    yesterday = today - timedelta(days=1)
    last_week = today - timedelta(days=7)
    
    # Add filtering options
    st.subheader(f"{log_type.capitalize()} Logs")
    
    col1, col2 = st.columns(2)
    
    with col1:
        search_text = st.text_input(f"Search in {log_type} logs", key=f"search_{log_type}")
    
    with col2:
        level_filter = st.selectbox(
            "Filter by level", 
            ["All", "INFO", "WARNING", "ERROR", "DEBUG"],
            key=f"level_{log_type}"
        )
    
    # Date range filter
    col1, col2 = st.columns(2)
    with col1:
        time_range = st.selectbox(
            "Time range",
            ["Last hour", "Last 24 hours", "Last 7 days", "Last 30 days", "All time"],
            key=f"time_{log_type}"
        )
    
    with col2:
        max_entries = st.number_input(
            "Max entries", 
            min_value=10, 
            max_value=10000, 
            value=100,
            key=f"max_{log_type}"
        )
    
    # Convert level filter
    level_to_filter = None if level_filter == "All" else level_filter
    
    # Get logs with filters
    logs = read_logs(
        log_type=log_type.lower(), 
        max_lines=max_entries,
        search_text=search_text if search_text else None,
        level_filter=level_to_filter
    )
    
    # Display log entries
    if logs:
        log_df = format_log_entries(logs)
        st.dataframe(
            log_df,
            use_container_width=True,
            hide_index=True,
        )
        
        # Add export option
        if st.button(f"Export {log_type} Logs", key=f"export_{log_type}"):
            csv_data = pd.DataFrame(logs).to_csv(index=False)
            st.download_button(
                label=f"Download {log_type} Logs as CSV",
                data=csv_data,
                file_name=f"{log_type.lower()}_logs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                mime="text/csv",
                key=f"download_{log_type}"
            )
    else:
        st.info(f"No {log_type.lower()} logs found or matching your filters.")
    
    # Add button to clear logs
    if st.button(f"Clear {log_type} Logs", key=f"clear_{log_type}"):
        try:
            log_file = logs_dir() / f"{log_type.lower()}.log"
            if log_file.exists():
                with open(log_file, "w") as f:
                    f.write("")
                st.success(f"{log_type} logs cleared successfully!")
                st.rerun()
        except Exception as e:
            st.error(f"Failed to clear logs: {str(e)}")


def main() -> None:
    """Render the logs page."""
    st.set_page_config(page_title="Logs", layout="wide")
    st.title("Logs")
    
    # Create tabs for different log types
    xero_tab, system_tab, error_tab = st.tabs([
        "Xero Logs",
        "System Logs",
        "Error Logs",
    ])
    
    with xero_tab:
        render_log_tab("xero")
    
    with system_tab:
        render_log_tab("system")
    
    with error_tab:
        render_log_tab("error")


if __name__ == "__main__":  # pragma: no cover - streamlit entry point
    main()