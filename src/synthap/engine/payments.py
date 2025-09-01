from __future__ import annotations

from datetime import date, datetime, timedelta
import random
from typing import List, Dict, Any, Optional


def generate_payments(
    invoice_records: List[Dict[str, Any]],
    account_code: str | None = None,
    payment_date: Optional[date] = None,
    pay_on_due_date: bool = False,
    allow_overdue: bool = False,
    overdue_count: int = 0,
) -> List[Dict[str, Any]]:
    """Create Xero payment payloads for the provided invoices.

    ``invoice_records`` should already be filtered to only the invoices
    that should be paid.
    """
    if not invoice_records:
        return []
    if account_code is None:
        account_code = "101"

    payments: List[Dict[str, Any]] = []
    overdue_idx: set[int] = set()
    if overdue_count > 0:
        overdue_idx = set(random.sample(range(len(invoice_records)), min(overdue_count, len(invoice_records))))
    for i, rec in enumerate(invoice_records):
        inv_id = rec.get("InvoiceID")
        amount = rec.get("AmountDue") or rec.get("Total")
        if not inv_id or amount is None:
            continue

        if payment_date is not None:
            pay_date = payment_date
        else:
            date_str = rec.get("DateString")
            due_str = rec.get("DueDateString")
            try:
                inv_date = datetime.fromisoformat(date_str).date() if date_str else date.today()
            except Exception:
                inv_date = date.today()
            try:
                due_date = datetime.fromisoformat(due_str).date() if due_str else inv_date
            except Exception:
                due_date = inv_date
            if pay_on_due_date:
                pay_date = due_date
            else:
                if allow_overdue or i in overdue_idx:
                    start = due_date + timedelta(days=1)
                    end = due_date + timedelta(days=30)
                    delta = (end - start).days
                    offset = random.randint(0, delta) if delta > 0 else 0
                    pay_date = start + timedelta(days=offset)
                else:
                    end = due_date - timedelta(days=1)
                    if end < inv_date:
                        end = inv_date
                    delta = (end - inv_date).days
                    offset = random.randint(0, delta) if delta > 0 else 0
                    pay_date = inv_date + timedelta(days=offset)
        payments.append(
            {
                "Invoice": {"InvoiceID": inv_id, "LineItems": []},
                "Account": {"Code": account_code},
                "Date": pay_date.isoformat(),
                "Amount": amount,
            }
        )
    return payments


def select_invoices_to_pay(
    all_refs: list[str],
    pay_count: Optional[int],
    pay_all: bool,
    pay_when_unspecified: bool,
    rng: random.Random,
) -> list[str]:
    """Determine which invoice references should be paid.

    If ``pay_all`` is True, all invoices are selected. When ``pay_count`` is
    provided, that exact number of invoices is sampled. If no payment directive
    is supplied (``pay_count`` is ``None`` and ``pay_all`` is False), invoices
    are only paid when ``pay_when_unspecified`` is True, in which case a random
    subset is chosen. Otherwise, no invoices are marked for payment.
    """

    if not all_refs:
        return []

    if pay_all:
        return list(all_refs)

    if pay_count is None:
        if not pay_when_unspecified:
            return []
        pay_count = rng.randint(1, len(all_refs))

    pay_count = max(0, min(pay_count, len(all_refs)))
    if pay_count == 0:
        return []

    return rng.sample(all_refs, pay_count)
