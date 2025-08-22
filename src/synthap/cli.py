from __future__ import annotations

import asyncio
import secrets
import json
from pathlib import Path
from datetime import date
from typing import Optional

import pandas as pd
import typer
from slugify import slugify
from tenacity import RetryError

from .config.settings import settings
from .config.runtime_config import load_runtime_config
from .catalogs.loader import load_catalogs

# AI planner + generator
from .ai.planner import plan_from_query
from .ai.schema import Plan as AIPlan
from .engine.generator import generate_from_plan

# Validation, storage, mapping, reports
from .engine.validators import validate_invoices
from .data.storage import to_rows, write_parquet
from .reports.report import write_json
from .xero.mapper import map_invoice
from .nlp.parser import parse_nlp_to_query

# Xero (OAuth + client)
from .xero.auth_server import run_server as auth_server_run
from .xero.client import post_invoices, resolve_tenant_id, post_payments
from .engine.payments import generate_payments
from .xero.oauth import TokenStore, refresh_token_if_needed

app = typer.Typer(add_completion=False)


def runs_dir() -> Path:
    p = Path(settings.runs_dir)
    p.mkdir(parents=True, exist_ok=True)
    return p


def latest_run_id() -> Optional[str]:
    candidates = [p.name for p in runs_dir().iterdir() if p.is_dir()]
    return sorted(candidates)[-1] if candidates else None


@app.command("xero-status")
def xero_status():
    tok = TokenStore.load()
    if not tok:
        typer.echo("No token found. Run `auth-init` and consent.")
        raise typer.Exit(code=1)

    async def _show():
        try:
            t = await resolve_tenant_id(tok)
            typer.echo(f"Resolved tenantId: {t}")
        except Exception as e:
            typer.echo(f"Failed to resolve tenantId: {e}")

    asyncio.run(_show())


@app.command("auth-init")
def auth_init():
    typer.echo("Starting local OAuth callback server...")
    typer.echo("Visit http://localhost:5050/ to see the authorize URL.")
    auth_server_run()


@app.command("generate")
def generate(
    query: str = typer.Option(..., "--query", "-q", help="NLP request"),
    seed: Optional[int] = typer.Option(
        None,
        "--seed",
        "-s",
        help="Random seed (omit to auto-generate for AI-guided variety)",
    ),
    allow_price_variation: Optional[bool] = typer.Option(
        None,
        "--allow-price-variation/--no-price-variation",
        help="Override price variation toggle from config/AI plan",
    ),
    price_variation_pct: Optional[float] = typer.Option(
        None,
        "--price-variance-pct",
        help="Override price variance percentage (e.g., 0.05 for ±5%)",
    ),
):
    """
    AI Plan -> sanitize -> generate -> validate -> stage (no Xero insert).
    Produces:
      - runs/<run_id>/{invoices.parquet, invoice_lines.parquet}
      - runs/<run_id>/plan.json (AI plan)
      - runs/<run_id>/xero_invoices.json (POST-ready)
      - runs/<run_id>/xero_invoices_with_meta.json (if enabled)
      - runs/<run_id>/generation_report.json
    """
    cat = load_catalogs(settings.data_dir)
    cfg = load_runtime_config(settings.data_dir)

    if seed is None:
        seed = secrets.randbits(32)

    # 1) AI plan (with built-in guardrails + AU fiscal periods)
    plan: AIPlan = plan_from_query(query, cat, today=date.today())
    parsed_query = parse_nlp_to_query(query, today=date.today())

    # Apply CLI overrides (final say)
    if allow_price_variation is not None:
        plan.allow_price_variation = allow_price_variation
    if price_variation_pct is not None:
        plan.price_variation_pct = float(price_variation_pct)

    # Hard guardrails for Stage-1 scope
    plan.status = "AUTHORISED"
    plan.currency = "AUD"

    run_id = slugify(f"{date.today().isoformat()}-{seed}")[:24]

    # 2) Generate from plan
    invoices = generate_from_plan(
        cat=cat,
        plan=plan,
        run_id=run_id,
        seed=seed,
        force_no_tax=cfg.force_no_tax,
    )

    # 3) Validate business rules
    validate_invoices(cat, invoices)

    # 4) Stage artifacts + plan.json
    inv_df, line_df = to_rows(invoices)
    base = runs_dir() / run_id
    base.mkdir(parents=True, exist_ok=True)

    write_parquet(inv_df, base / "invoices.parquet")
    write_parquet(line_df, base / "invoice_lines.parquet")

    write_json(plan.model_dump(mode="json"), base / "plan.json")

    xero_payload = {"Invoices": [map_invoice(inv) for inv in invoices]}
    write_json(xero_payload, base / "xero_invoices.json")

    if cfg.artifacts.include_meta_json:
        meta = []
        for inv in invoices:
            meta.append(
                {
                    "__meta": {
                        "vendor_id": inv.vendor_id,
                        "contact_id": inv.contact_id,
                        "contact_account_number": inv.contact_account_number,
                    },
                    "xero": map_invoice(inv),
                }
            )
        write_json({"Invoices": meta}, base / "xero_invoices_with_meta.json")

    gen_report = {
        "run_id": run_id,
        "query": query,
        "seed_used": seed,
        "count": len(invoices),
        "date_range": {
            "start": plan.date_range.start.isoformat(),
            "end": plan.date_range.end.isoformat(),
        },
        "artifacts": {
            "invoices_parquet": str((base / "invoices.parquet").as_posix()),
            "invoice_lines_parquet": str((base / "invoice_lines.parquet").as_posix()),
            "plan_json": str((base / "plan.json").as_posix()),
            "xero_invoices_json": str((base / "xero_invoices.json").as_posix()),
            "xero_invoices_with_meta_json": str(
                (base / "xero_invoices_with_meta.json").as_posix()
            ),
        },
        "config_used": {
            "allow_price_variation": plan.allow_price_variation,
            "price_variation_pct": plan.price_variation_pct,
            "currency": plan.currency,
            "status": plan.status,
            "business_days_only": plan.business_days_only,
        },
        "payment_instructions": {
            "count": parsed_query.pay_count,
            "all": parsed_query.pay_all,
        },
    }
    write_json(gen_report, base / "generation_report.json")

    typer.echo(f"Generated & staged {len(invoices)} invoices at {base}")
    typer.echo(f"Plan: {base / 'plan.json'}")


@app.command("insert")
def insert(
    run_id: Optional[str] = typer.Option(None, "--run-id", "-r", help="Run ID to insert; defaults to latest staged"),
    reference: Optional[str] = typer.Option(None, "--reference", "-ref", help="Insert only the invoice with this Reference"),
    limit: Optional[int] = typer.Option(None, "--limit", "-l", help="Insert only the first N invoices"),
):
    """
    Inserts the staged invoices for a run into Xero, in batches of 50.
    Requires OAuth token (see `auth-init`). Writes insertion_report.json.
    """
    if run_id is None:
        run_id = latest_run_id()
        if not run_id:
            typer.echo("No staged runs found. Run `generate` first.")
            raise typer.Exit(code=1)

    base = runs_dir() / run_id
    inv_path = base / "invoices.parquet"
    line_path = base / "invoice_lines.parquet"
    if not inv_path.exists() or not line_path.exists():
        typer.echo(f"Missing parquet files in {base}.")
        raise typer.Exit(code=1)

    inv_df = pd.read_parquet(inv_path)
    line_df = pd.read_parquet(line_path)

    payloads = []
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
    # Optional: filter selection
    if reference:
        payloads = [p for p in payloads if p.get("Reference") == reference]
    if limit is not None:
        payloads = payloads[: int(limit)]


    async def _insert():
        batch_size = 50
        total_ok, total_fail = 0, 0
        invoice_records = []
        for i in range(0, len(payloads), batch_size):
            batch = payloads[i : i + batch_size]
            try:
                resp = await post_invoices(batch)
                batch_invoices = resp.get("Invoices", [])
                total_ok += len(batch_invoices)
                for inv in batch_invoices:
                    ref = inv.get("Reference")
                    if ref is not None:
                        match = inv_df[inv_df["reference"] == ref]
                        if not match.empty:
                            inv["Vendor"] = match.iloc[0].get("vendor_id")
                    invoice_records.append(inv)
            except RetryError as e:
                total_fail += len(batch)
                typer.echo(
                    f"Batch {i//batch_size} failed: {e.last_attempt.exception()}"
                )
            except Exception as e:
                total_fail += len(batch)
                typer.echo(f"Batch {i//batch_size} failed: {e}")
        # Persist invoice data before attempting payments so a subsequent
        # payment run can read the file directly.
        inv_report_path = base / "invoice_report.json"
        write_json({"run_id": run_id, "invoices": invoice_records}, inv_report_path)

        # Load pay instructions from generation report
        pay_count = None
        pay_all = False
        gen_report_path = base / "generation_report.json"
        if gen_report_path.exists():
            try:
                pay_info = json.loads(gen_report_path.read_text()).get(
                    "payment_instructions", {}
                )
                pay_count = pay_info.get("count")
                pay_all = bool(pay_info.get("all"))
            except Exception:
                pass
        # Use the saved invoice report as the source of invoice IDs
        try:
            saved_records = json.loads(inv_report_path.read_text()).get("invoices", [])
        except Exception:
            saved_records = []

        payments = generate_payments(
            saved_records,
            pay_count=pay_count,
            pay_all=pay_all,
            account_code=settings.xero_payment_account_code,
        )
        payment_records = []
        if payments:
            try:
                resp = await post_payments(payments)
                payment_records = resp.get("Payments", [])
                typer.echo(f"[{run_id}] Paid {len(payment_records)} invoices.")
            except RetryError as e:
                typer.echo(f"Payment batch failed: {e.last_attempt.exception()}")
            except Exception as e:
                typer.echo(f"Payment batch failed: {e}")
        else:
            typer.echo(f"[{run_id}] No payments generated.")
        report = {
            "run_id": run_id,
            "inserted_success": total_ok,
            "inserted_failed": total_fail,
            "payments_made": len(payment_records),
        }
        write_json(report, base / "insertion_report.json")
        write_json({"run_id": run_id, "payments": payment_records}, base / "payment_report.json")
        typer.echo(f"[{run_id}] Inserted: {total_ok}, Failed: {total_fail}. Report saved.")

    asyncio.run(_insert())


if __name__ == "__main__":
    app()
