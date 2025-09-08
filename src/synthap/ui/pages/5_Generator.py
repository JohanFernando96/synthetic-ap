"""Invoice generation page."""

from __future__ import annotations

import random
import secrets
from datetime import date

import streamlit as st
from slugify import slugify

from dataclasses import asdict

from synthap.ai.planner import clamp_plan_to_today, plan_from_query
from synthap.catalogs.loader import load_catalogs
from synthap.cli import runs_dir
from synthap.config.runtime_config import load_runtime_config
from synthap.config.settings import settings
from synthap.data.storage import to_rows, write_parquet
from synthap.engine.generator import generate_from_plan
from synthap.engine.payments import select_invoices_to_pay
from synthap.engine.validators import validate_invoices
from synthap.nlp.parser import parse_nlp_to_query
from synthap.reports.report import write_json


def _vendor_options(cat):
    return [v.name for v in cat.vendors]


def _vendor_name_to_id(cat, names):
    by_name = {v.name: v.id for v in cat.vendors}
    return [by_name[n] for n in names if n in by_name]


def main() -> None:
    st.title("Generate invoices")

    cat = load_catalogs(settings.data_dir)

    query = st.text_area("NLP query", height=100)

    parsed = None
    error = None
    if query.strip():
        try:
            parsed = parse_nlp_to_query(query, today=date.today(), catalogs=cat)
        except Exception as e:  # pragma: no cover - UI feedback
            error = str(e)

    if parsed:
        st.subheader("Detected fields")
        st.json(asdict(parsed))
    elif error:
        st.error(error)

    vendors = st.multiselect("Vendors", _vendor_options(cat))
    max_lines = st.number_input("Max line items per invoice", min_value=1, value=5)
    no_tax = st.checkbox("Generate without tax")
    clamp_dates = st.checkbox("Limit dates to today", value=True)
    pay_count = st.number_input("Invoices to mark for payment", min_value=0, value=0)
    pay_on_due = st.checkbox("Pay exactly on due date")
    allow_overdue = st.checkbox("Allow overdue payments")
    pay_before_due = st.checkbox("Pay before due date")

    can_generate = parsed is not None
    submitted = st.button("Generate", disabled=not can_generate)

    if not submitted:
        return

    cfg = load_runtime_config(settings.data_dir)
    plan = plan_from_query(query, cat, today=date.today())
    if clamp_dates:
        clamp_plan_to_today(plan, date.today())

    if vendors:
        ids = _vendor_name_to_id(cat, vendors)
        plan.vendor_mix = [vp for vp in plan.vendor_mix if vp.vendor_id in ids]

    for vp in plan.vendor_mix:
        available = len(cat.vendor_items.get(vp.vendor_id, [])) or len(cat.items)
        vp.max_lines_per_invoice = min(int(max_lines), available)
        if vp.min_lines_per_invoice > vp.max_lines_per_invoice:
            vp.min_lines_per_invoice = vp.max_lines_per_invoice

    plan.normalize_counts()

    seed = secrets.randbits(32)
    run_id = slugify(f"{date.today().isoformat()}-{seed}")[:24]

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
    pay_refs = select_invoices_to_pay(
        all_refs,
        int(pay_count) if pay_count else None,
        False,
        cfg.payments.pay_when_unspecified,
        rng,
    )
    write_json({"run_id": run_id, "references": pay_refs}, base / "to_pay.json")

    report = {
        "run_id": run_id,
        "query": query,
        "seed_used": seed,
        "count": len(invoices),
        "payment_instructions": {
            "count": int(pay_count) if pay_count else None,
            "pay_on_due_date": bool(pay_on_due),
            "allow_overdue": bool(allow_overdue),
            "pay_before_due": bool(pay_before_due),
            "references": pay_refs,
        },
    }
    write_json(report, base / "generation_report.json")

    st.success(f"Generated run {run_id}")

    # Clear any cached data so other pages load fresh data and rerun the script
    st.cache_data.clear()
    st.experimental_rerun()


if __name__ == "__main__":  # pragma: no cover - streamlit entry point
    main()

