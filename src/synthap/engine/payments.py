from __future__ import annotations

from datetime import date
from typing import List, Dict, Any, Optional


def generate_payments(
    invoice_records: List[Dict[str, Any]],
    account_code: str | None = None,
    payment_date: Optional[date] = None,
) -> List[Dict[str, Any]]:
    """Create Xero payment payloads for the provided invoices.

    ``invoice_records`` should already be filtered to only the invoices
    that should be paid.
    """
    if not invoice_records:
        return []
    if account_code is None:
        account_code = "001"
    if payment_date is None:
        payment_date = date.today()

    payments: List[Dict[str, Any]] = []
    for rec in invoice_records:
        inv_id = rec.get("InvoiceID")
        amount = rec.get("AmountDue") or rec.get("Total")
        if not inv_id or amount is None:
            continue
        payments.append(
            {
                "Invoice": {"InvoiceID": inv_id},
                "Account": {"Code": account_code},
                "Date": payment_date.isoformat(),
                "Amount": amount,
            }
        )
    return payments
