from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import List, Optional
from datetime import date, timedelta
import random
from slugify import slugify

from ..catalogs.loader import Catalogs, Vendor, Item
from .planner import business_days, calc_due_date
from ..ai.schema import Plan, VendorPlan

Money = Decimal

@dataclass
class InvoiceLine:
    description: str
    quantity: Decimal
    unit_amount: Money
    account_code: str
    tax_type: str
    line_amount: Money
    item_code: str

@dataclass
class Invoice:
    vendor_id: str
    contact_id: str
    contact_account_number: Optional[str]
    date: date
    due_date: date
    currency: str
    status: str
    reference: str
    lines: List[InvoiceLine]

def q2(v: float | Decimal) -> Money:
    return (Decimal(v).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

def _qty_for_item(code: str, rng: random.Random) -> int:
    cl = code.lower()
    if "lab" in cl or "hour" in cl: return rng.randint(1, 8)
    if any(x in cl for x in ["water", "fence", "scaf", "hire", "pump"]): return rng.randint(1, 40)
    return rng.randint(1, 12)

def _items_for_vendor(cat: Catalogs, vendor: Vendor) -> List[Item]:
    codes = cat.vendor_items.get(vendor.id, [])
    by_code = {i.code: i for i in cat.items}
    items = [by_code[c] for c in codes if c in by_code]
    return items if items else cat.items  # fallback

def _pick_lines(items: List[Item], vp: VendorPlan, rng: random.Random) -> List[Item]:
    n = rng.randint(vp.min_lines_per_invoice, vp.max_lines_per_invoice)
    # prefer unique items if enough available, otherwise allow repeats
    if len(items) >= n:
        return rng.sample(items, n)
    # not enough distinct items; allow repetition
    return [rng.choice(items) for _ in range(n)]

def generate_from_plan(
    cat: Catalogs,
    plan: Plan,
    run_id: str,
    seed: int,
) -> List[Invoice]:
    rng = random.Random(seed)

    # build date universe (business days or all days)
    if plan.business_days_only:
        days = business_days(plan.date_range.start, plan.date_range.end)
    else:
        days = [plan.date_range.start + timedelta(days=i)
                for i in range((plan.date_range.end - plan.date_range.start).days + 1)]
    if not days:
        raise ValueError("No days in period.")

    invoices: List[Invoice] = []
    vendors_by_id = {v.id: v for v in cat.vendors}
    items_by_vendor_cache: dict[str, List[Item]] = {}

    seq = 0
    for vp in plan.vendor_mix:
        if vp.count <= 0:
            continue
        vendor = vendors_by_id[vp.vendor_id]
        if vendor.id not in items_by_vendor_cache:
            items_by_vendor_cache[vendor.id] = _items_for_vendor(cat, vendor)
        vend_items = items_by_vendor_cache[vendor.id]

        for _ in range(vp.count):
            seq += 1
            issue = rng.choice(days)
            due = calc_due_date(issue, vendor)
            chosen_item_objs = _pick_lines(vend_items, vp, rng)

            lines: List[InvoiceLine] = []
            for it in chosen_item_objs:
                qty = _qty_for_item(it.code, rng)
                unit = q2(it.unit_price) if not plan.allow_price_variation else q2(
                    it.unit_price * (1 + (rng.random()*2-1) * float(plan.price_variation_pct or 0.0))
                )
                line_amt = q2(Decimal(qty) * unit)
                lines.append(InvoiceLine(
                    description=it.name,
                    quantity=Decimal(qty),
                    unit_amount=unit,
                    account_code=it.account_code,
                    tax_type=it.tax_code,
                    line_amount=line_amt,
                    item_code=it.code,
                ))

            ref_suffix = "".join(rng.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(4))
            reference = f"AP-{run_id[:6]}-{slugify(vendor.name)[:10].upper()}-{seq:04d}-{ref_suffix}"

            invoices.append(Invoice(
                vendor_id=vendor.id,
                contact_id=vendor.xero_contact_id,
                contact_account_number=getattr(vendor, "xero_account_number", None),
                date=issue,
                due_date=due,
                currency=plan.currency or "AUD",
                status=plan.status or "AUTHORISED",
                reference=reference,
                lines=lines,
            ))

    while len(invoices) < plan.total_count and plan.vendor_mix:
        vp = plan.vendor_mix[0]
        vendor = vendors_by_id[vp.vendor_id]
        vend_items = items_by_vendor_cache.get(vendor.id) or _items_for_vendor(cat, vendor)
        seq += 1
        issue = rng.choice(days)
        due = calc_due_date(issue, vendor)
        chosen_item_objs = _pick_lines(vend_items, vp, rng)
        lines = []
        for it in chosen_item_objs:
            qty = _qty_for_item(it.code, rng)
            unit = q2(it.unit_price)
            line_amt = q2(Decimal(qty) * unit)
            lines.append(InvoiceLine(it.name, Decimal(qty), unit, it.account_code, it.tax_code, line_amt, it.code))
        ref_suffix = "".join(rng.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(4))
        reference = f"AP-{run_id[:6]}-{slugify(vendor.name)[:10].upper()}-{seq:04d}-{ref_suffix}"
        invoices.append(Invoice(vendor.id, vendor.xero_contact_id, getattr(vendor, "xero_account_number", None),
                                issue, due, plan.currency or "AUD", plan.status or "AUTHORISED", reference, lines))
    return invoices
