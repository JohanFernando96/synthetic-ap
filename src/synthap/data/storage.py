from pathlib import Path
import pandas as pd
from typing import List
from ..engine.generator import Invoice

def to_rows(invoices: List[Invoice]) -> tuple[pd.DataFrame, pd.DataFrame]:
    inv_rows, line_rows = [], []
    for inv in invoices:
        inv_rows.append({
            "vendor_id": inv.vendor_id,
            "contact_id": inv.contact_id,
            "date": inv.date.isoformat(),
            "due_date": inv.due_date.isoformat(),
            "currency": inv.currency,
            "status": inv.status,
            "reference": inv.reference,
            "invoice_number": inv.invoice_number,
        })
        for ln in inv.lines:
            line_rows.append({
                "reference": inv.reference,
                "description": ln.description,
                "quantity": float(ln.quantity),
                "unit_amount": float(ln.unit_amount),
                "account_code": ln.account_code,
                "tax_type": ln.tax_type,
                "line_amount": float(ln.line_amount),
                "item_code": ln.item_code,
            })
    return pd.DataFrame(inv_rows), pd.DataFrame(line_rows)

def write_parquet(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)
