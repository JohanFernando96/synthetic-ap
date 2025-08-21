from dataclasses import dataclass
from decimal import Decimal
from datetime import date

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from synthap.xero.mapper import map_invoice

@dataclass
class FakeLine:
    description: str
    quantity: Decimal
    unit_amount: Decimal
    account_code: str
    tax_type: str
    line_amount: Decimal
    item_code: str

@dataclass
class FakeInvoice:
    vendor_id: str
    contact_id: str
    contact_account_number: str | None
    date: date
    due_date: date
    currency: str
    status: str
    reference: str
    invoice_number: str
    lines: list[FakeLine]


def test_map_invoice_uses_invoice_number():
    inv = FakeInvoice(
        vendor_id="VEND-TEST",
        contact_id="123",
        contact_account_number=None,
        date=date(2023, 1, 2),
        due_date=date(2023, 1, 30),
        currency="AUD",
        status="AUTHORISED",
        reference="REF-123",
        invoice_number="INV-202301-0001",
        lines=[
            FakeLine(
                description="Item",
                quantity=Decimal("1"),
                unit_amount=Decimal("10"),
                account_code="400",
                tax_type="INPUT",
                line_amount=Decimal("10"),
                item_code="CODE",
            )
        ],
    )
    mapped = map_invoice(inv)
    assert mapped["InvoiceNumber"] == "INV-202301-0001"
