from __future__ import annotations

import asyncio
import json
import random
import secrets
from datetime import date
from pathlib import Path
from typing import Optional

import pandas as pd
import typer
from slugify import slugify
from tenacity import RetryError

from .catalogs.loader import load_catalogs
from .config.runtime_config import load_runtime_config
from .config.settings import settings
from .data.storage import to_rows, write_parquet

# AI planner + generator
from .engine.generator import generate_from_plan
from .engine.payments import generate_payments, select_invoices_to_pay

# Validation, storage, mapping, reports
from .engine.validators import validate_invoices
from .nlp.parser import parse_nlp_to_query
from .reports.report import write_json

# Xero (OAuth + client)
from .xero.client import post_invoices, post_payments, resolve_tenant_id, debug_token
from .xero.mapper import map_invoice
from .xero.oauth import TokenStore, check_scopes, build_authorize_url

from .paths import latest_run_id
from .logs import log_error, log_xero

app = typer.Typer(add_completion=False)


@app.command("xero-status")
def xero_status():
    tok = TokenStore.load()
    if not tok:
        typer.echo("No token found. Run `auth-init` and consent.")
        raise typer.Exit(code=1)

    async def _show():
        try:
            t, _ = await resolve_tenant_id(tok)
            typer.echo(f"Resolved tenantId: {t}")
            
            # Add debug info
            if 'tenant_id' in tok:
                typer.echo(f"Token has tenant_id: {tok['tenant_id']}")
            if 'access_token' in tok:
                typer.echo(f"Token has access_token: {tok['access_token'][:10]}...")
            if 'refresh_token' in tok:
                typer.echo(f"Token has refresh_token: {tok['refresh_token'][:10]}...")
                
            # Check scopes
            scope_status = check_scopes()
            typer.echo("\nXero API Scope Status:")
            for scope, has_scope in scope_status.items():
                status = "✓" if has_scope else "✗"
                typer.echo(f"{status} {scope}")
                
        except Exception as e:
            typer.echo(f"Failed to resolve tenantId: {e}")

    asyncio.run(_show())


@app.command("auth-init")
def auth_init():
    from .xero.auth_server import run_server as auth_server_run

    typer.echo("Starting local OAuth callback server...")
    typer.echo("Visit http://localhost:5050/ to see the authorize URL.")
    auth_server_run()


@app.command("xero-reauth")
def xero_reauth():
    """Force Xero reauthorization by clearing the token."""
    TokenStore.clear()
    typer.echo("Xero token cleared. Run 'auth-init' to reauthorize.")
    typer.echo(f"Authorization URL: {build_authorize_url()}")


@app.command("xero-debug")
def xero_debug():
    """Debug Xero authentication issues."""
    tok = TokenStore.load()
    if not tok:
        typer.echo("No token found. Run `auth-init` and consent.")
        raise typer.Exit(code=1)
    
    typer.echo("--- Token Information ---")
    typer.echo(f"Token file: {settings.token_file}")
    typer.echo(f"Token keys: {list(tok.keys())}")
    
    if 'tenant_id' in tok:
        typer.echo(f"Tenant ID: {tok['tenant_id']}")
    else:
        typer.echo("No tenant_id in token!")
        
    if 'access_token' in tok:
        typer.echo(f"Access token (first 10 chars): {tok['access_token'][:10]}...")
        typer.echo(f"Access token expiry: {tok.get('expires_at', 'unknown')}")
    else:
        typer.echo("No access_token in token!")
    
    # Check scopes
    typer.echo("\n--- Xero API Scope Status ---")
    scope_status = check_scopes()
    for scope, has_scope in scope_status.items():
        status = "✓" if has_scope else "✗"
        typer.echo(f"{status} {scope}")
    
    # Settings check
    typer.echo("\n--- Xero API Settings ---")
    typer.echo(f"Client ID: {settings.xero_client_id[:5]}..." if settings.xero_client_id else "No client ID!")
    typer.echo(f"Redirect URI: {settings.xero_redirect_uri}" if settings.xero_redirect_uri else "No redirect URI!")
    typer.echo(f"Scopes: {settings.xero_scopes}" if settings.xero_scopes else "No scopes configured!")
    
    # Print debug info and reauth instructions
    typer.echo("\n--- Instructions ---")
    typer.echo("If you're having authentication issues, try:")
    typer.echo("1. Run 'xero-reauth' to clear the token")
    typer.echo("2. Run 'auth-init' to get a new token")
    typer.echo("3. Check your app's scopes in the Xero developer portal")


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
    limit_to_current: bool = typer.Option(
        False,
        "--limit-to-current/--no-limit",
        help="Limit generation to current date (prevents future dates)",
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
    from .ai.planner import plan_from_query
    from .ai.schema import Plan as AIPlan, DateRange
    from .nlp.periods import limit_date_range

    cat = load_catalogs(settings.data_dir)
    cfg = load_runtime_config(settings.data_dir)
    today = date.today()

    if seed is None:
        seed = secrets.randbits(32)

    # 1) AI plan (with built-in guardrails + AU fiscal periods)
    plan: AIPlan = plan_from_query(query, cat, today=today)
    parsed_query = parse_nlp_to_query(query, today=today, catalogs=cat, use_llm=True)

    # Apply CLI overrides (final say)
    if allow_price_variation is not None:
        plan.allow_price_variation = allow_price_variation
    if price_variation_pct is not None:
        plan.price_variation_pct = float(price_variation_pct)

    # Apply time limit if enabled
    if limit_to_current:
        original_range = plan.date_range
        new_range = limit_date_range(original_range, today)
        if new_range != original_range:
            typer.echo(f"Date range limited from {original_range.start}-{original_range.end} to {new_range.start}-{new_range.end}")
            plan.date_range = DateRange(start=new_range.start, end=new_range.end)

    # Hard guardrails for Stage-1 scope
    plan.status = "AUTHORISED"
    plan.currency = "AUD"

    run_id = slugify(f"{today.isoformat()}-{seed}")[:24]

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
    # Determine which invoices should be paid in a later step and persist
    # the list of references so the insert phase can match on invoice IDs.
    all_refs = [inv.reference for inv in invoices]
    rng = random.Random(seed)
    to_pay_refs = select_invoices_to_pay(
        all_refs,
        parsed_query.pay_count,
        parsed_query.pay_all,
        cfg.payments.pay_when_unspecified,
        rng,
    )
    write_json({"run_id": run_id, "references": to_pay_refs}, base / "to_pay.json")

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
            "to_pay_json": str((base / "to_pay.json").as_posix()),
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
            "references": to_pay_refs,
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
    cfg = load_runtime_config(settings.data_dir)

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
        xero_log: list[dict[str, object]] = []

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
            except RetryError as e:
                total_fail += len(batch)
                err = str(e.last_attempt.exception())
                xero_log.append({"action": "post_invoices", "request": batch, "error": err})
                typer.echo(f"Batch {i//batch_size} failed: {err}")
            except Exception as e:
                total_fail += len(batch)
                err = str(e)
                xero_log.append({"action": "post_invoices", "request": batch, "error": err})
                typer.echo(f"Batch {i//batch_size} failed: {err}")

        # Persist invoice data so payment runs can match references to IDs.
        inv_report_path = base / "invoice_report.json"
        write_json({"run_id": run_id, "invoices": invoice_records}, inv_report_path)

        # Reload invoices from report to ensure IDs are read from disk.
        try:
            invoice_records = json.loads(inv_report_path.read_text()).get("invoices", [])
        except Exception:
            invoice_records = []

        # Load list of references that should be paid
        to_pay_refs: list[str] = []
        to_pay_path = base / "to_pay.json"
        if to_pay_path.exists():
            try:
                to_pay_refs = json.loads(to_pay_path.read_text()).get("references", [])
            except Exception:
                pass

        records_to_pay = [r for r in invoice_records if r.get("Reference") in to_pay_refs]

        payments = generate_payments(
            records_to_pay,
            account_code=settings.xero_payment_account_code,
            pay_on_due_date=cfg.payments.pay_on_due_date,
            allow_overdue=cfg.payments.allow_overdue,
        )

        payment_records = []
        if payments:
            try:
                resp = await post_payments(payments)
                xero_log.append({"action": "post_payments", "request": payments, "response": resp})
                payment_records = resp.get("Payments", [])
                typer.echo(f"[{run_id}] Paid {len(payment_records)} invoices.")
            except RetryError as e:
                err = str(e.last_attempt.exception())
                xero_log.append({"action": "post_payments", "request": payments, "error": err})
                typer.echo(f"Payment batch failed: {err}")
            except Exception as e:
                err = str(e)
                xero_log.append({"action": "post_payments", "request": payments, "error": err})
                typer.echo(f"Payment batch failed: {err}")
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
        write_json({"run_id": run_id, "events": xero_log}, base / "xero_log.json")
        typer.echo(f"[{run_id}] Inserted: {total_ok}, Failed: {total_fail}. Report saved.")

    asyncio.run(_insert())


@app.command("generate-synthetic-data")
def generate_synthetic_data(
    industry: str = typer.Option(..., "--industry", "-i", help="Industry for synthetic contacts"),
    num_contacts: int = typer.Option(5, "--num-contacts", "-n", help="Number of contacts to generate"),
    items_per_vendor: int = typer.Option(2, "--items-per-vendor", "-ipv", help="Number of items per vendor"),
    override_existing: bool = typer.Option(False, "--override-existing", help="Override existing data instead of appending"),
):
    """
    Generate synthetic contacts and items for Australian businesses.
    Updates catalog YAML files with new data.
    """
    from .ai.schema import SyntheticContactRequest
    from .ai.synthgen import preview_synthetic_data, apply_synthetic_data
    from .catalogs.manager import backup_catalogs
    
    # Create a backup before generation
    backup_reason = f"before_{industry.lower()}_data_generation"
    backup_path = backup_catalogs(reason=backup_reason)
    typer.echo(f"Created backup at: {backup_path}")
    
    request = SyntheticContactRequest(
        industry=industry,
        num_contacts=num_contacts,
        items_per_vendor=items_per_vendor
    )
    
    typer.echo(f"Generating {num_contacts} synthetic contacts for {industry} industry with {items_per_vendor} items per vendor...")
    
    async def _run():
        try:
            # First preview the data
            typer.echo("Generating preview data...")
            preview_data = await preview_synthetic_data(request)
            
            typer.echo(f"Preview generated with {len(preview_data['contacts'])} contacts and {len(preview_data['items'])} items.")
            
            # Confirm application
            typer.echo("Applying changes and updating Xero...")
            result = await apply_synthetic_data(preview_data, override_existing=override_existing)
            
            if result.get("success"):
                typer.echo("✓ Successfully generated synthetic data:")
                for step in result.get("steps", []):
                    status = "✓" if step.get("status") == "complete" else "✗"
                    typer.echo(f"{status} {step.get('name')}")
                    
                typer.echo(f"Contacts created: {result.get('contacts_created', 0)}")
                typer.echo(f"Items created: {result.get('items_created', 0)}")
                typer.echo(f"Vendor-item relationships created: {result.get('vendor_items_created', 0)}")
            else:
                typer.echo("✗ Data generation failed")
                if "error" in result:
                    typer.echo(f"Error: {result['error']}")
                typer.echo("Process Steps:")
                for step in result.get("steps", []):
                    status = "✓" if step.get("status") == "complete" else "✗"
                    typer.echo(f"{status} {step.get('name')}")
                    if step.get("status") == "error" and "error" in step:
                        typer.echo(f"  Error: {step['error']}")
                
        except Exception as e:
            typer.echo(f"Error generating synthetic data: {str(e)}")
            raise
    
    asyncio.run(_run())


def runs_dir() -> Path:
    """Resolved run directory path."""
    return Path(settings.runs_dir)


if __name__ == "__main__":
    app()

    