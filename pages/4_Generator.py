# Update the Generator page with additional options
"""Invoice generation page."""

from __future__ import annotations
from pathlib import Path
from typing import Optional

from synthap.config.settings import settings

import random
import secrets
from datetime import date, datetime
from typing import Optional

import streamlit as st
from slugify import slugify

from synthap.ai.planner import plan_from_query
from synthap.catalogs.loader import load_catalogs
from synthap import runs_dir
from synthap.config.runtime_config import load_runtime_config
from synthap.config.settings import settings
from synthap.data.storage import to_rows, write_parquet
from synthap.engine.generator import generate_from_plan
from synthap.engine.payments import select_invoices_to_pay
from synthap.engine.validators import validate_invoices
from synthap.nlp.parser import parse_nlp_to_query, QueryScopeError
from synthap.reports.report import write_json

def latest_run_id() -> Optional[str]:
    """Get the latest run ID."""
    candidates = [p.name for p in runs_dir().iterdir() if p.is_dir()]
    return sorted(candidates)[-1] if candidates else None


def _vendor_options(cat):
    return [v.name for v in cat.vendors]


def _vendor_name_to_id(cat, names):
    by_name = {v.name: v.id for v in cat.vendors}
    return [by_name[n] for n in names if n in by_name]


def validate_query(query: str, cat) -> tuple[bool, Optional[str]]:
    """Validate the NLP query and return (is_valid, error_message)."""
    if not query:
        return False, "Please enter a query"
    
    try:
        parsed = parse_nlp_to_query(query, date.today(), cat)
        missing = []
        if not parsed.date_range:
            missing.append("date range")
        if parsed.total_count <= 0:
            missing.append("valid invoice count")
        
        if missing:
            return False, f"Query missing: {', '.join(missing)}"
        return True, None
    except QueryScopeError as e:
        return False, str(e)
    except ValueError as e:
        return False, f"Invalid query: {str(e)}"
    except Exception:
        return False, "Unable to parse query"


def extract_nlp_payment_count(query_text, cat):
    """Extract payment count from NLP query."""
    if not query_text:
        return None
    try:
        parsed = parse_nlp_to_query(query_text, date.today(), cat)
        return parsed.pay_count
    except Exception:
        return None


def main() -> None:
    st.title("Generate Invoices")
    
    cat = load_catalogs(settings.data_dir)
    cfg = load_runtime_config(settings.data_dir)

    # Example queries section
    st.subheader("Example Queries")
    examples = [
        "Generate 10 bills for last month with 2-4 line items and pay only 3",
        "Create 5 invoices for vendor BuildRight Cement for this quarter",
        "Generate 20 bills for Q3 2025 with at least 3 line items each",
        "Create 8 invoices for last week with 50% to be paid and 2 overdue",
        "Generate 15 bills for yesterday with tax codes and 3 line items each",
        "Create 12 invoices for current month with all paid before due date"
    ]
    for ex in examples:
        st.code(ex, language="text")

    # Main form
    with st.form("gen_form"):
        # NLP Query with live validation
        query = st.text_area(
            "Natural Language Query",
            height=100,
            placeholder="e.g., Generate 10 bills for last month and pay only 2",
            key="nlp_query"
        )
        
        # Extract NLP payment count for default value
        nlp_pay_count = extract_nlp_payment_count(query, cat)
        
        # Live query validation
        if query:
            is_valid, error = validate_query(query, cat)
            if not is_valid:
                st.warning(error)
            else:
                st.success("Valid query")

        # Advanced options section
        with st.expander("Advanced Options"):
            # Vendor and invoice options
            st.subheader("Vendor & Invoice Options")
            col_v1, col_v2 = st.columns(2)
            
            with col_v1:
                vendors = st.multiselect("Filter by Vendors (Optional)", _vendor_options(cat))
                business_days_only = st.checkbox(
                    "Business Days Only", 
                    value=cfg.generator.business_days_only,
                    help="If checked, invoices will only be dated on business days"
                )
            
            with col_v2:
                max_lines = st.number_input(
                    "Max Line Items per Invoice",
                    min_value=1,
                    value=5,
                    help="Maximum number of line items allowed per invoice"
                )
                min_lines = st.number_input(
                    "Min Line Items per Invoice",
                    min_value=1,
                    max_value=max_lines,
                    value=1,
                    help="Minimum number of line items per invoice"
                )
            
            # Price variation options
            st.subheader("Price Options")
            col_p1, col_p2 = st.columns(2)
            
            with col_p1:
                allow_price_variation = st.checkbox(
                    "Allow Price Variation",
                    value=cfg.generator.allow_price_variation,
                    help="If checked, item prices can vary within the specified percentage"
                )
                
            with col_p2:
                price_variation_pct = st.slider(
                    "Price Variation %",
                    min_value=0.0,
                    max_value=30.0,
                    value=float(cfg.generator.price_variation_pct or 10.0) * 100,
                    step=1.0,
                    format="%.0f%%",
                    disabled=not allow_price_variation,
                    help="Maximum percentage price can vary up or down"
                ) / 100.0
                
            # Tax options
            st.subheader("Tax Options")
            no_tax = st.checkbox(
                "Generate without Tax",
                value=cfg.force_no_tax,
                help="If checked, no tax will be applied to generated invoices"
            )
            
            # AI Description options
            if cfg.ai.enabled:
                st.subheader("AI Description Options")
                enable_ai_descriptions = st.checkbox(
                    "Generate AI Line Item Descriptions",
                    value=cfg.ai.line_item_description_enabled,
                    help="If checked, AI will generate natural language descriptions for line items"
                )
            
            # Currency and status options
            st.subheader("Invoice Details")
            col_c1, col_c2 = st.columns(2)
            
            with col_c1:
                currency = st.selectbox(
                    "Currency",
                    options=["AUD", "USD", "EUR", "GBP", "NZD"],
                    index=0,
                    help="Currency for the generated invoices"
                )
            
            with col_c2:
                status = st.selectbox(
                    "Invoice Status",
                    options=["AUTHORISED", "DRAFT", "SUBMITTED"],
                    index=0,
                    help="Status for the generated invoices"
                )

        # Payment options
        st.subheader("Payment Options")
        col1, col2 = st.columns(2)
        
        with col1:
            pay_count = st.number_input(
                "Invoices to Mark for Payment",
                min_value=0,
                value=nlp_pay_count if nlp_pay_count is not None else 0,
                help="Number of invoices that should be marked for payment"
            )
            
            overdue_count = st.number_input(
                "Number of Overdue Invoices",
                min_value=0,
                max_value=int(pay_count) if pay_count else None,
                value=0,
                help="Number of invoices that can be overdue"
            )

        with col2:
            pay_all = st.checkbox(
                "Pay All Invoices",
                help="If checked, all generated invoices will be marked for payment",
                key="pay_all_invoices"
            )

        # Payment timing options
        st.subheader("Payment Timing")
        col3, col4 = st.columns(2)
        
        with col3:
            pay_on_due = st.checkbox(
                "Pay Exactly on Due Date",
                help="If checked, payments will be made exactly on the due date"
            )
            
            pay_before_due = st.checkbox(
                "Pay Before Due Date",
                disabled=pay_on_due,
                help="If checked, payments will be made before the due date"
            )

        with col4:
            allow_overdue = st.checkbox(
                "Allow Overdue Payments",
                disabled=pay_on_due or pay_before_due or overdue_count == 0,
                help="If checked, some payments may be overdue"
            )
            
            max_days_overdue = st.slider(
                "Max Days Overdue",
                min_value=1,
                max_value=60,
                value=30,
                disabled=not allow_overdue,
                help="Maximum number of days a payment can be overdue"
            )

        # Time limit option
        limit_to_current = st.checkbox(
            "Do Not Generate Beyond Current Time",
            help="If checked, no data will be generated beyond the current date and time"
        )

        # Run options
        st.subheader("Run Options")
        col_r1, col_r2 = st.columns(2)
        
        with col_r1:
            use_custom_seed = st.checkbox(
                "Use Custom Seed",
                help="If checked, you can specify a custom random seed for reproducible results"
            )
            
        with col_r2:
            custom_seed = st.number_input(
                "Custom Seed",
                disabled=not use_custom_seed,
                help="Random seed value for reproducible results"
            )

        submitted = st.form_submit_button("Generate")

    if not submitted or not query:
        return

    # Validate form state
    if pay_on_due and pay_before_due:
        st.error("Choose either paying on the due date or before it, not both.")
        return
    if overdue_count > pay_count and not pay_all:
        st.error("Overdue invoices cannot exceed invoices to pay.")
        return
    if pay_all and pay_count > 0:
        st.warning("'Pay All Invoices' selected - ignoring specific payment count.")

    # Load config and parse query
    try:
        plan = plan_from_query(query, cat, today=date.today())
    except (QueryScopeError, ValueError) as e:
        st.error(f"Invalid query: {str(e)}")
        return


    # Apply time limit if enabled
    if limit_to_current:
        today = date.today()
        if plan.date_range.end > today:
            from synthap.nlp.periods import limit_to_current_date
            
            original_range = plan.date_range
            new_range = limit_to_current_date(original_range, today)
            
            # Check if the date range extends significantly into the future
            if (original_range.end - today).days > 0:
                st.error("Query requests data beyond current time, but time limit is enabled.")
                return
            
            # Otherwise make the adjustment and continue
            plan.date_range = new_range
            
            # If start is after end, set both to today
            if plan.date_range.start > plan.date_range.end:
                plan.date_range = DateRange(start=today, end=today)
                
            st.warning(f"Date range limited from {original_range.start}-{original_range.end} to {plan.date_range.start}-{plan.date_range.end}")
            
    # Apply form settings to plan
    if vendors:
        ids = _vendor_name_to_id(cat, vendors)
        plan.vendor_mix = [vp for vp in plan.vendor_mix if vp.vendor_id in ids]

    # Update plan with custom settings
    plan.business_days_only = business_days_only
    plan.allow_price_variation = allow_price_variation
    plan.price_variation_pct = price_variation_pct if allow_price_variation else None
    plan.currency = currency
    plan.status = status

    # Update vendor plans with line item settings
    for vp in plan.vendor_mix:
        available = len(cat.vendor_items.get(vp.vendor_id, [])) or len(cat.items)
        vp.max_lines_per_invoice = min(int(max_lines), available)
        vp.min_lines_per_invoice = min(int(min_lines), vp.max_lines_per_invoice)

    plan.normalize_counts()

    # Update config with form settings
    cfg.force_no_tax = no_tax
    if hasattr(cfg.ai, "line_item_description_enabled"):
        cfg.ai.line_item_description_enabled = enable_ai_descriptions if cfg.ai.enabled else False

    # Generate and save data
    seed = int(custom_seed) if use_custom_seed else secrets.randbits(32)
    # Create a more human-readable seed representation for the run ID
    seed_hex = f"{seed:08x}"  # Convert to 8-character hex format
    run_id = slugify(f"{date.today().isoformat()}-{seed_hex}")[:24]

    try:
        with st.spinner("Generating invoices..."):
            invoices = generate_from_plan(
                cat=cat,
                plan=plan,
                run_id=run_id,
                seed=seed,
                force_no_tax=no_tax,
                cfg=cfg,
            )
            validate_invoices(cat, invoices)

            inv_df, line_df = to_rows(invoices)
            base = runs_dir() / run_id
            base.mkdir(parents=True, exist_ok=True)
            write_parquet(inv_df, base / "invoices.parquet")
            write_parquet(line_df, base / "invoice_lines.parquet")

            all_refs = [inv.reference for inv in invoices]
            rng = random.Random(seed)
            
            # Determine which invoices to pay
            pay_refs = []
            if pay_all:
                pay_refs = all_refs
            else:
                # Use the payment count from NLP if it was detected
                final_pay_count = pay_count
                
                pay_refs = select_invoices_to_pay(
                    all_refs,
                    int(final_pay_count) if final_pay_count else None,
                    pay_all,
                    cfg.payments.pay_when_unspecified,
                    rng,
                )
            
            write_json({"run_id": run_id, "references": pay_refs}, base / "to_pay.json")

            report = {
                "run_id": run_id,
                "query": query,
                "seed_used": seed,
                "seed_hex": seed_hex,  # Add the hex format to the report
                "count": len(invoices),
                "payment_instructions": {
                    "count": int(pay_count) if pay_count and not pay_all else len(invoices) if pay_all else None,
                    "overdue_count": int(overdue_count) if overdue_count else None,
                    "pay_on_due_date": bool(pay_on_due),
                    "allow_overdue": bool(allow_overdue),
                    "pay_before_due": bool(pay_before_due),
                    "max_days_overdue": max_days_overdue if allow_overdue else None,
                    "references": pay_refs,
                },
                "generator_settings": {
                    "business_days_only": business_days_only,
                    "allow_price_variation": allow_price_variation,
                    "price_variation_pct": price_variation_pct if allow_price_variation else None,
                    "currency": currency,
                    "status": status,
                    "force_no_tax": no_tax,
                    "ai_descriptions": enable_ai_descriptions if cfg.ai.enabled else False,
                }
            }
            write_json(report, base / "generation_report.json")

            # Display success message with seed information for reproducibility
            st.success(f"""
Generated run {run_id}

Seed information:
- Decimal: {seed}
- Hex: {seed_hex}

You can use this seed with 'Custom Seed' option for reproducible results.
            """)

            # Update session state and redirect
            st.session_state["last_seed"] = str(seed)
            st.session_state["refresh_dashboard"] = True
            st.session_state["refresh_catalog"] = True

            switch_page = getattr(st, "switch_page", None)
            if switch_page:
                switch_page("app.py")
            else:  # pragma: no cover - fallback when switching pages unsupported
                st.info("Return to the dashboard to view results.")

    except Exception as e:
        st.error(f"Generation failed: {str(e)}")


if __name__ == "__main__":  # pragma: no cover - streamlit entry point
    main()