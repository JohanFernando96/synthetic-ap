from __future__ import annotations
from typing import Dict, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from ..engine.generator import Invoice, InvoiceLine

def map_invoice(inv: "Invoice") -> Dict[str, Any]:
    return {
        "Type": "ACCPAY",
        "InvoiceNumber": inv.invoice_number,
        "Contact": {"ContactID": inv.contact_id},
        "CurrencyCode": inv.currency,
        "Date": inv.date.isoformat(),
        "DueDate": inv.due_date.isoformat(),
        "Status": inv.status,  # AUTHORISED
        "Reference": inv.reference,
        "LineItems": [
            {
                "Description": ln.description,
                "Quantity": float(ln.quantity),
                "UnitAmount": float(ln.unit_amount),
                "AccountCode": ln.account_code,
                "TaxType": ln.tax_type,
                "LineAmount": float(ln.line_amount),
            } for ln in inv.lines
        ],
    }
