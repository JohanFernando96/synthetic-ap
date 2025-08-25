from __future__ import annotations
from typing import List, Dict, Any, Optional
from datetime import date, timedelta
from pydantic import ValidationError
from openai import OpenAI
from ..config.settings import settings
from ..config.runtime_config import load_runtime_config
from ..catalogs.loader import Catalogs
from ..nlp.periods import resolve_period_au
from .schema import Plan, VendorPlan, DateRange


def _catalog_summary(cat: Catalogs, max_vendors: int) -> Dict[str, Any]:
    vi = {}
    for vid, codes in cat.vendor_items.items():
        vi[vid] = list(codes)[:20]  # cap
    vendors = [
        {"id": v.id, "name": v.name, "item_count": len(vi.get(v.id, []))}
        for v in cat.vendors
    ]
    return {
        "vendors": vendors[:50],  # cap to keep prompt small
        "vendor_items": {k: vi[k] for k in list(vi.keys())[:50]},
        "fiscal_year_start_month": settings.fiscal_year_start_month,  # AU=7
    }

def _australian_quarter_bounds(dt: date, quarter_spec: str) -> (date, date):
    q = quarter_spec.upper().strip()
    fy_start = settings.fiscal_year_start_month
    year = dt.year
    if q == "Q1":
        start = date(year, 7, 1);   end = date(year, 9, 30)
    elif q == "Q2":
        start = date(year, 10, 1);  end = date(year, 12, 31)
    elif q == "Q3":
        start = date(year+1, 1, 1); end = date(year+1, 3, 31)
    elif q == "Q4":
        start = date(year+1, 4, 1); end = date(year+1, 6, 30)
    else:
        raise ValueError("Invalid AU quarter")
    return start, end

def _sanitize_plan(cat: Catalogs, plan: Plan, cfg) -> Plan:
    plan.status = "AUTHORISED"
    plan.currency = "AUD"

    # clamp AI knobs to config defaults if None
    if plan.allow_price_variation is None:
        plan.allow_price_variation = cfg.generator.allow_price_variation
    if plan.price_variation_pct is None:
        plan.price_variation_pct = cfg.generator.price_variation_pct
    if plan.business_days_only is None:
        plan.business_days_only = cfg.generator.business_days_only

    # fix vendor ids; if invalid, drop them
    valid_vendor_ids = {v.id for v in cat.vendors}
    filtered = [vp for vp in plan.vendor_mix if vp.vendor_id in valid_vendor_ids]
    if not filtered:
        # if AI picked none or unknowns, fallback: spread across top vendors
        take = min(cfg.ai.max_vendors, len(cat.vendors))
        per = max(1, plan.total_count // max(1, take))
        filtered = [VendorPlan(vendor_id=cat.vendors[i].id, count=per) for i in range(take)]
        # adjust first one to hit the exact total
        s = sum(v.count for v in filtered)
        if s != plan.total_count:
            filtered[0].count += plan.total_count - s
    plan.vendor_mix = filtered
    plan.normalize_counts()

    items_by_vendor = cat.vendor_items
    for vp in plan.vendor_mix:
        item_count = len(items_by_vendor.get(vp.vendor_id, []))
        if item_count == 0:
            vp.min_lines_per_invoice = min(vp.min_lines_per_invoice, 2)
            vp.max_lines_per_invoice = min(vp.max_lines_per_invoice, 3)
        else:
            vp.max_lines_per_invoice = max(
                1, min(vp.max_lines_per_invoice, max(1, item_count))
            )
            vp.min_lines_per_invoice = max(1, min(vp.min_lines_per_invoice, vp.max_lines_per_invoice))

    return plan

def plan_from_query(query: str, cat: Catalogs, today: date) -> Plan:
    cfg = load_runtime_config(settings.data_dir)
    base_range = resolve_period_au(query, today=today)
    total_fallback = 10

    if not cfg.ai.enabled:
        from ..nlp.parser import parse_nlp_to_query
        pq = parse_nlp_to_query(query, today=today, catalogs=cat, use_llm=True)
        start, end = pq.date_range.start, pq.date_range.end
        total = pq.total_count or total_fallback
        # spread across up to max_vendors
        take = min(cfg.ai.max_vendors, len(cat.vendors))
        per = max(1, total // max(1, take))
        mix = [VendorPlan(vendor_id=cat.vendors[i].id, count=per) for i in range(take)]
        s = sum(v.count for v in mix)
        if s != total: mix[0].count += (total - s)
        return Plan(
            rationale="non-AI fallback",
            total_count=total,
            date_range=DateRange(start=start, end=end),
            vendor_mix=mix,
            allow_price_variation=cfg.generator.allow_price_variation,
            price_variation_pct=cfg.generator.price_variation_pct,
            business_days_only=cfg.generator.business_days_only,
            status="AUTHORISED",
            currency="AUD",
        )

    oai = OpenAI(api_key=settings.openai_api_key)
    cat_summary = _catalog_summary(cat, max_vendors=getattr(cfg.ai, 'max_vendors', 6))

    system = (
        "You are an AP data planner for synthetic unpaid supplier bills. "
        "Task: read a natural-language request and output ONE JSON object with fields "
        "total_count, date_range {start,end}, and vendor_mix[]. "
        "Constraints:\n"
        "- UNPAID ONLY (Status must be AUTHORISED).\n"
        "- Currency AUD.\n"
        "- Use the Australian fiscal year (starts July 1). Quarters: Q1=Jul-Sep, Q2=Oct-Dec, Q3=Jan-Mar, Q4=Apr-Jun.\n"
        "- Only use vendors that exist in catalogs; do not invent vendors or items.\n"
        "- Prefer vendors that can support requested line counts (min/max) based on how many items they sell.\n"
        "- Avoid anomalies/messy data; realistic, business-day issue dates.\n"
        "- If the user asks outside scope (paid, anomalies), ignore and keep unpaid clean data."
    )

    user = {
        "query": query,
        "today": today.isoformat(),
        "fallback_date_range": {"start": base_range.start.isoformat(), "end": base_range.end.isoformat()},
        "catalog_summary": cat_summary,
        "defaults": {
            "business_days_only": bool(cfg.generator.business_days_only),
            "allow_price_variation": bool(cfg.generator.allow_price_variation),
            "price_variation_pct": float(cfg.generator.price_variation_pct),
            "currency": "AUD",
            "status": "AUTHORISED",
            "max_vendors": int(cfg.ai.max_vendors),
        },
        "output_schema": {
            "total_count": "int > 0",
            "date_range": {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"},
            "vendor_mix": [
                {"vendor_id": "vendor.id from catalogs", "count": "int >=0", "min_lines_per_invoice": ">=1", "max_lines_per_invoice": ">=min"}
            ],
            "allow_price_variation": "bool?",
            "price_variation_pct": "float?",
            "business_days_only": "bool?",
            "status": "string? must be AUTHORISED",
            "currency": "string? must be AUD"
        }
    }

    resp = oai.chat.completions.create(
        model=cfg.ai.model,
        temperature=float(cfg.ai.temperature),
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": str(user)}
        ],
    )

    raw = resp.choices[0].message.content
    import json
    try:
        as_dict = json.loads(raw)
        plan = Plan.model_validate(as_dict)
    except Exception as e:
        # Hard fallback on any JSON/validation error
        from ..nlp.parser import parse_nlp_to_query
        pq = parse_nlp_to_query(query, today=today, catalogs=cat, use_llm=True)
        start, end = pq.date_range.start, pq.date_range.end
        total = pq.total_count or total_fallback
        take = min(cfg.ai.max_vendors, len(cat.vendors))
        per = max(1, total // max(1, take))
        mix = [VendorPlan(vendor_id=cat.vendors[i].id, count=per) for i in range(take)]
        s = sum(v.count for v in mix)
        if s != total: mix[0].count += (total - s)
        plan = Plan(
            rationale=f"fallback due to AI error: {e}",
            total_count=total,
            date_range=DateRange(start=start, end=end),
            vendor_mix=mix,
        )

    return _sanitize_plan(cat, plan, cfg)
