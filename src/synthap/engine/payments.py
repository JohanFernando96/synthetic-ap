from __future__ import annotations

from datetime import date, datetime, timedelta
import random
from typing import List, Dict, Any, Optional


def generate_payments(
    invoice_records: List[Dict[str, Any]],
    account_code: str | None = None,
    payment_date: Optional[date] = None,
    pay_on_due_date: bool = False,
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
    for rec in invoice_records:
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
