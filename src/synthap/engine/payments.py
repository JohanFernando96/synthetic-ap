from __future__ import annotations

from datetime import date
import random
from typing import List, Dict, Any, Optional


def generate_payments(
    invoice_records: List[Dict[str, Any]],
    pay_count: Optional[int] = None,
    pay_all: bool = False,
    account_code: str | None = None,
    payment_date: Optional[date] = None,
    rng: Optional[random.Random] = None,
) -> List[Dict[str, Any]]:
    """Create Xero payment payloads for a subset of invoices.

    If ``pay_all`` is True all invoices will be paid. Otherwise a subset
    determined by ``pay_count`` (or a random count if None) is selected.
    """
    if not invoice_records:
        return []
    if rng is None:
        rng = random.Random()
    if account_code is None:
        account_code = "001"
    if payment_date is None:
        payment_date = date.today()

    records = invoice_records
    if not pay_all:
        if pay_count is None:
            # pick at least one invoice when paying a random subset

            pay_count = rng.randint(1, len(records))
        pay_count = max(0, min(pay_count, len(records)))
        records = rng.sample(records, pay_count) if pay_count else []

    payments: List[Dict[str, Any]] = []
    for rec in records:
        inv_id = rec.get("InvoiceID")
        amount = rec.get("AmountDue") or rec.get("Total")
        if not inv_id or amount is None:
            continue
        payments.append(
            {
                "Invoice": {"InvoiceID": inv_id, "LineItems": []},
                "Account": {"Code": account_code},
                "Date": payment_date.isoformat(),
                "Amount": amount,
            }
        )
    return payments
