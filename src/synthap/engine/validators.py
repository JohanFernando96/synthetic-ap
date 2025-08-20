from typing import List
from ..catalogs.loader import Catalogs
from .generator import Invoice

def validate_invoices(cat: Catalogs, invoices: List[Invoice]) -> None:
    acct = {a.code for a in cat.accounts}
    tax = {t.code for t in cat.tax_codes}
    vendors = {v.xero_contact_id for v in cat.vendors}
    for idx, inv in enumerate(invoices):
        if inv.contact_id not in vendors:
            raise ValueError(f"Invoice {idx}: unknown contact_id {inv.contact_id}")
        if inv.currency != "AUD":
            raise ValueError(f"Invoice {idx}: currency must be AUD.")
        if inv.status != "AUTHORISED":
            raise ValueError(f"Invoice {idx}: status must be AUTHORISED (unpaid).")
        for j, ln in enumerate(inv.lines):
            if ln.account_code not in acct:
                raise ValueError(f"Invoice {idx} line {j}: invalid account {ln.account_code}")
            if ln.tax_type not in tax:
                raise ValueError(f"Invoice {idx} line {j}: invalid tax code {ln.tax_type}")
            calc = (ln.quantity * ln.unit_amount)
            if ln.line_amount != calc.quantize(ln.line_amount):
                raise ValueError(f"Invoice {idx} line {j}: line_amount mismatch.")
