"""Insert generated invoices into Xero."""

from __future__ import annotations
import asyncio
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

import pandas as pd
import streamlit as st

from synthap import runs_dir
from synthap.config.runtime_config import load_runtime_config
from synthap.config.settings import settings
from synthap.engine.payments import generate_payments
from synthap.logs import log_xero, log_error, log_system, read_logs
from synthap.xero.client import post_invoices, post_payments
from synthap.xero.oauth import TokenStore


def _available_runs() -> list[str]:
    """Get all available runs, sorted by name (most recent first)."""
    return sorted([p.name for p in runs_dir().iterdir() if p.is_dir()], reverse=True)


def _load_json(path: Path) -> dict | None:
    """Load JSON file if it exists."""
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def is_authenticated() -> bool:
    """Check if the user is authenticated with Xero."""
    token = TokenStore.load()
    return token is not None and 'tenant_id' in token


async def insert_to_xero(run_id: str) -> Dict[str, Any]:
    """Insert invoices from the specified run into Xero."""
    base = runs_dir() / run_id
    inv_path = base / "invoices.parquet"
    line_path = base / "invoice_lines.parquet"
    
    if not inv_path.exists() or not line_path.exists():
        raise ValueError(f"Missing invoice data files in {base}")
        
    # Load the invoice data
    inv_df = pd.read_parquet(inv_path)
    line_df = pd.read_parquet(line_path)
    cfg = load_runtime_config(settings.data_dir)
    
    # Create the payload for Xero
    payloads = []
    for ref, lines in line_df.groupby("reference"):
        head = inv_df[inv_df["reference"] == ref].iloc[0]
        line_items = []
        for _, ln in lines.iterrows():
            line_items.append({
                "Description": ln["description"],
                "Quantity": float(ln["quantity"]),
                "UnitAmount": float(ln["unit_amount"]),
                "AccountCode": str(ln["account_code"]),
                "TaxType": str(ln["tax_type"]),
                "LineAmount": float(ln["line_amount"]),
            })
        payloads.append({
            "Type": "ACCPAY",
            "Contact": {"ContactID": head["contact_id"]},
            "CurrencyCode": head["currency"],
            "LineItems": line_items,
            "Date": head["date"],
            "DueDate": head["due_date"],
            "Reference": ref,
            "InvoiceNumber": head.get("invoice_number", ref),
            "Status": head["status"],
        })
    
    # Insert invoices in batches
    batch_size = 50
    total_ok, total_fail = 0, 0
    invoice_records = []
    xero_log = []
    
    log_system(f"Starting insertion of {len(payloads)} invoices from run {run_id}")
    
    # Insert invoices
    for i in range(0, len(payloads), batch_size):
        batch = payloads[i : i + batch_size]
        try:
            resp = await post_invoices(batch)
            xero_log.append({"action": "post_invoices", "request": batch, "response": resp})
            batch_invoices = resp.get("Invoices", [])
            total_ok += len(batch_invoices)
            for inv in batch_invoices:
                ref = inv.get("Reference")
                if ref is not None:
                    match = inv_df[inv_df["reference"] == ref]
                    if not match.empty:
                        inv["Vendor"] = match.iloc[0].get("vendor_id")
                invoice_records.append(inv)
            log_xero(f"Successfully inserted batch {i//batch_size} with {len(batch_invoices)} invoices")
        except Exception as e:
            total_fail += len(batch)
            err = str(e)
            xero_log.append({"action": "post_invoices", "request": batch, "error": err})
            log_xero(f"Batch {i//batch_size} failed: {err}", "ERROR")
            log_error(f"Failed to insert invoice batch: {err}", exception=e)
    
    # Save invoice records for payment reference
    inv_report_path = base / "invoice_report.json"
    with open(inv_report_path, "w") as f:
        json.dump({"run_id": run_id, "invoices": invoice_records}, f, indent=2)
    
    # Process payments if any
    payment_records = []
    to_pay_path = base / "to_pay.json"
    if to_pay_path.exists():
        try:
            to_pay_data = json.loads(to_pay_path.read_text())
            to_pay_refs = to_pay_data.get("references", [])
            records_to_pay = [r for r in invoice_records if r.get("Reference") in to_pay_refs]
            
            payments = generate_payments(
                records_to_pay,
                account_code=settings.xero_payment_account_code,
                pay_on_due_date=cfg.payments.pay_on_due_date,
                allow_overdue=cfg.payments.allow_overdue,
            )
            
            if payments:
                try:
                    resp = await post_payments(payments)
                    xero_log.append({"action": "post_payments", "request": payments, "response": resp})
                    payment_records = resp.get("Payments", [])
                    log_xero(f"Successfully paid {len(payment_records)} invoices")
                except Exception as e:
                    err = str(e)
                    xero_log.append({"action": "post_payments", "request": payments, "error": err})
                    log_xero(f"Payment processing failed: {err}", "ERROR")
                    log_error(f"Failed to process payments: {err}", exception=e)
            else:
                log_xero(f"No payments generated for run {run_id}")
        except Exception as e:
            log_error(f"Error processing payments file: {str(e)}", exception=e)
    
    # Save reports
    report = {
        "run_id": run_id,
        "inserted_success": total_ok,
        "inserted_failed": total_fail,
        "payments_made": len(payment_records),
        "timestamp": datetime.now().isoformat(),
    }
    
    report_path = base / "insertion_report.json"
    payment_report_path = base / "payment_report.json"
    xero_log_path = base / "xero_log.json"
    
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)
    with open(payment_report_path, "w") as f:
        json.dump({"run_id": run_id, "payments": payment_records}, f, indent=2)
    with open(xero_log_path, "w") as f:
        json.dump({"run_id": run_id, "events": xero_log}, f, indent=2)
    
    log_system(f"Completed Xero insertion for run {run_id}: {total_ok} successful, {total_fail} failed")
    return report


def show_xero_logs(limit: int = 10):
    """Show recent Xero logs."""
    logs = read_logs("xero", max_lines=limit)
    if logs:
        log_df = pd.DataFrame(logs)
        st.dataframe(
            log_df,
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("No Xero logs found.")


def main() -> None:
    """Render the Insert to Xero page."""
    st.set_page_config(page_title="Insert to Xero", layout="wide")
    st.title("Insert to Xero")
    
    # Check authentication
    if not is_authenticated():
        st.error("❌ Not connected to Xero. Please connect first.")
        st.info("Go to the main dashboard and click 'Connect to Xero' to authenticate.")
        return
    
    # Get available runs
    runs = _available_runs()
    if not runs:
        st.info("No runs available. Generate invoices first.")
        return
    
    # Get the latest run ID
    latest_run = runs[0] if runs else None
    
    # Layout
    col1, col2 = st.columns([3, 1])
    
    with col1:
        st.subheader("Select Run")
        selected_run = st.selectbox(
            "Select a run to insert into Xero",
            runs,
            index=0,
            format_func=lambda x: f"{x} {'(Latest)' if x == latest_run else ''}"
        )
        
        run_path = runs_dir() / selected_run
        
        # Check if already inserted
        insertion_report = _load_json(run_path / "insertion_report.json")
        if insertion_report:
            st.info(f"⚠️ This run has already been inserted into Xero. Reinsertion may create duplicates.")
            st.json(insertion_report)
        
        # Show run details
        report = _load_json(run_path / "generation_report.json")
        if report:
            st.subheader("Run Details")
            st.markdown(f"**Query:** {report.get('query', 'N/A')}")
            st.markdown(f"**Invoice Count:** {report.get('count', 0)}")
            
            date_range = report.get('date_range', {})
            start = date_range.get('start', 'N/A')
            end = date_range.get('end', 'N/A')
            st.markdown(f"**Date Range:** {start} to {end}")
            
            # Check to_pay.json to show payment info
            to_pay = _load_json(run_path / "to_pay.json")
            if to_pay:
                pay_count = len(to_pay.get('references', []))
                st.markdown(f"**Invoices Marked for Payment:** {pay_count}")
    
    with col2:
        st.subheader("Insert Options")
        
        insert_button = st.button("Insert into Xero", type="primary", use_container_width=True)
        st.caption("This will insert all invoices from the selected run into Xero.")
        
        # Xero status
        tenant_id = TokenStore.load().get("tenant_id") if TokenStore.load() else None
        st.info(f"Connected to Xero organization: {tenant_id}")
    
    # Process insertion
    if insert_button:
        with st.status("Processing Xero insertion...") as status:
            # Insert into Xero
            st.write("Connecting to Xero...")
            
            try:
                # Check connection
                if not is_authenticated():
                    st.error("❌ Not connected to Xero. Please connect first.")
                    status.update(label="Failed: Not connected to Xero", state="error")
                    return
                
                st.write("✅ Connected to Xero")
                
                # Insert invoices
                st.write("Inserting invoices...")
                result = asyncio.run(insert_to_xero(selected_run))
                
                st.write(f"✅ Inserted {result['inserted_success']} invoices")
                
                # Process payments
                if result['payments_made'] > 0:
                    st.write(f"✅ Processed {result['payments_made']} payments")
                
                # Show summary
                status.update(label=f"Completed: {result['inserted_success']} invoices inserted, {result['payments_made']} payments made", state="complete")
                
                # Add to insertion history
                if "insertion_history" not in st.session_state:
                    st.session_state.insertion_history = []
                
                st.session_state.insertion_history.append({
                    "timestamp": datetime.now().isoformat(),
                    "run_id": selected_run,
                    "invoices": result["inserted_success"],
                    "payments": result["payments_made"],
                    "failed": result["inserted_failed"]
                })
                
            except Exception as e:
                st.error(f"❌ Error: {str(e)}")
                log_error(f"Error in Xero insertion UI: {str(e)}", exception=e)
                status.update(label=f"Failed: {str(e)}", state="error")
    
    # Display insertion history
    st.subheader("Insertion History")
    if "insertion_history" in st.session_state and st.session_state.insertion_history:
        history_df = pd.DataFrame(st.session_state.insertion_history)
        st.dataframe(history_df, use_container_width=True, hide_index=True)
    else:
        st.info("No insertion history yet.")
    
    # Show recent Xero logs
    st.subheader("Recent Xero Logs")
    show_xero_logs(20)


if __name__ == "__main__":  # pragma: no cover - streamlit entry point
    main()