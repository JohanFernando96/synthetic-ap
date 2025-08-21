from __future__ import annotations
from typing import Dict, Any
from ..engine.generator import Invoice, InvoiceLine

def map_invoice(inv: Invoice) -> Dict[str, Any]:
    return {
        "Type": "ACCPAY",
        # Use a custom invoice number if provided; otherwise fall back to the
        # reference we generate for each invoice. This keeps `generate` working
        # even when the Invoice model doesn't include an explicit
        # `invoice_number` field.
        "InvoiceNumber": getattr(inv, "invoice_number", inv.reference),
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
