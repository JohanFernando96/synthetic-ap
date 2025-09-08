"""Insert staged invoices into Xero."""
from __future__ import annotations

import asyncio
import json

import pandas as pd
import streamlit as st
from tenacity import RetryError

from synthap.cli import latest_run_id, runs_dir
from synthap.config.runtime_config import load_runtime_config
from synthap.config.settings import settings
from synthap.engine.payments import generate_payments
from synthap.reports.report import write_json
from synthap.xero.client import post_invoices, post_payments, resolve_tenant_id
from synthap.xero.oauth import TokenStore


def _runs_with_seeds() -> list[tuple[str, int | None]]:
    runs: list[tuple[str, int | None]] = []
    for p in runs_dir().iterdir():
        if not p.is_dir():
            continue
        seed = None
        report = p / "generation_report.json"
        if report.exists():
            try:
                with open(report, encoding="utf-8") as f:
                    seed = json.load(f).get("seed_used")
            except Exception:
                pass
        runs.append((p.name, seed))
    return sorted(runs)

async def _insert_async(
    run_id: str,
    conn_msg: st.delta_generator.DeltaGenerator,
    inv_msg: st.delta_generator.DeltaGenerator,
    pay_msg: st.delta_generator.DeltaGenerator,
) -> None:
    base = runs_dir() / run_id
    inv_path = base / "invoices.parquet"
    line_path = base / "invoice_lines.parquet"
    if not inv_path.exists() or not line_path.exists():
        inv_msg.error("Missing parquet files. Generate invoices first.")
        return

    inv_df = pd.read_parquet(inv_path)
    line_df = pd.read_parquet(line_path)
    cfg = load_runtime_config(settings.data_dir)

    conn_msg.info("Connecting to Xero...")
    tok = TokenStore.load()
    try:
        await resolve_tenant_id(tok)
        conn_msg.success("Connected to Xero")
    except Exception as e:  # pragma: no cover - UI feedback
        conn_msg.error(f"Connection failed: {e}")
        return

    payloads: list[dict] = []
    for ref, lines in line_df.groupby("reference"):
        head = inv_df[inv_df["reference"] == ref].iloc[0]
        line_items = []
        for _, ln in lines.iterrows():
            line_items.append(
                {
                    "Description": ln["description"],
                    "Quantity": float(ln["quantity"]),
                    "UnitAmount": float(ln["unit_amount"]),
                    "AccountCode": str(ln["account_code"]),
                    "TaxType": str(ln["tax_type"]),
                    "LineAmount": float(ln["line_amount"]),
                }
            )
        payloads.append(
            {
                "Type": "ACCPAY",
                "Contact": {"ContactID": head["contact_id"]},
                "CurrencyCode": head["currency"],
                "LineItems": line_items,
                "Date": head["date"],
                "DueDate": head["due_date"],
                "Reference": ref,
                "InvoiceNumber": head.get("invoice_number", ref),
                "Status": head["status"],
            }
        )

    batch_size = 50
    total_ok = total_fail = 0
    invoice_records: list[dict[str, object]] = []
    xero_log: list[dict[str, object]] = []
    for i in range(0, len(payloads), batch_size):
        batch = payloads[i : i + batch_size]
        inv_msg.info(f"Posting invoices batch {i // batch_size + 1}...")
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
        except RetryError as e:  # pragma: no cover - network feedback
            total_fail += len(batch)
            err = str(e.last_attempt.exception())
            xero_log.append({"action": "post_invoices", "request": batch, "error": err})
            inv_msg.error(f"Batch {i // batch_size} failed: {err}")
        except Exception as e:  # pragma: no cover - network feedback
            total_fail += len(batch)
            err = str(e)
            xero_log.append({"action": "post_invoices", "request": batch, "error": err})
            inv_msg.error(f"Batch {i // batch_size} failed: {err}")

    inv_report_path = base / "invoice_report.json"
    write_json({"run_id": run_id, "invoices": invoice_records}, inv_report_path)

    try:
        invoice_records = json.loads(inv_report_path.read_text()).get("invoices", [])
    except Exception:  # pragma: no cover - disk read
        invoice_records = []

    to_pay_refs: list[str] = []
    to_pay_path = base / "to_pay.json"
    if to_pay_path.exists():
        try:
            to_pay_refs = json.loads(to_pay_path.read_text()).get("references", [])
        except Exception:  # pragma: no cover - disk read
            pass

    records_to_pay = [r for r in invoice_records if r.get("Reference") in to_pay_refs]
    payments = generate_payments(
        records_to_pay,
        account_code=settings.xero_payment_account_code,
        pay_on_due_date=cfg.payments.pay_on_due_date,
        allow_overdue=cfg.payments.allow_overdue,
        overdue_count=cfg.payments.overdue_count,
    )

    payment_records: list[dict[str, object]] = []
    if payments:
        pay_msg.info("Posting payments...")
        try:
            resp = await post_payments(payments)
            xero_log.append({"action": "post_payments", "request": payments, "response": resp})
            payment_records = resp.get("Payments", [])
            pay_msg.success(f"Paid {len(payment_records)} invoices.")
        except RetryError as e:  # pragma: no cover - network feedback
            err = str(e.last_attempt.exception())
            xero_log.append({"action": "post_payments", "request": payments, "error": err})
            pay_msg.error(f"Payment batch failed: {err}")
        except Exception as e:  # pragma: no cover - network feedback
            err = str(e)
            xero_log.append({"action": "post_payments", "request": payments, "error": err})
            pay_msg.error(f"Payment batch failed: {err}")
    else:
        pay_msg.info("No payments generated.")

    report = {
        "run_id": run_id,
        "inserted_success": total_ok,
        "inserted_failed": total_fail,
        "payments_made": len(payment_records),
    }
    write_json(report, base / "insertion_report.json")
    write_json({"run_id": run_id, "payments": payment_records}, base / "payment_report.json")
    write_json({"run_id": run_id, "events": xero_log}, base / "xero_log.json")
    inv_msg.success(f"Inserted: {total_ok}, Failed: {total_fail}. Report saved.")


def main() -> None:
    st.title("Insert into Xero")
    runs = _runs_with_seeds()
    if not runs:
        st.info("No runs available. Generate invoices first.")
        return

    labels = [f"{rid} (seed {seed})" if seed is not None else rid for rid, seed in runs]
    latest = latest_run_id()
    index = next((i for i, (rid, _) in enumerate(runs) if rid == latest), 0)
    choice = st.selectbox("Run", labels, index=index)
    run_id = runs[labels.index(choice)][0]

    if st.button("Insert"):
        conn_msg = st.empty()
        inv_msg = st.empty()
        pay_msg = st.empty()
        asyncio.run(_insert_async(run_id, conn_msg, inv_msg, pay_msg))


if __name__ == "__main__":  # pragma: no cover - streamlit entry point
    main()
