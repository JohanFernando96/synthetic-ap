from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import sys
from pathlib import Path
import types

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

fake_pydantic = types.ModuleType("pydantic")

class BaseModel:
    def __init__(self, **data):
        for k, v in data.items():
            setattr(self, k, v)


def field_validator(*args, **kwargs):
    def decorator(fn):
        return fn
    return decorator


def Field(default=None, **kwargs):
    return default


fake_pydantic.BaseModel = BaseModel
fake_pydantic.field_validator = field_validator
fake_pydantic.Field = Field
sys.modules["pydantic"] = fake_pydantic

from synthap.engine.generator import generate_from_plan


@dataclass
class Vendor:
    id: str
    name: str
    xero_contact_id: str
    xero_account_number: str | None
    is_supplier: bool
    payment_terms: dict


@dataclass
class Item:
    id: str
    code: str
    name: str
    unit_price: float
    account_code: str
    tax_code: str
    price_variance_pct: float = 0.1


@dataclass
class Catalogs:
    vendors: list
    items: list
    accounts: list
    tax_codes: list
    vendor_items: dict


@dataclass
class DateRange:
    start: date
    end: date


@dataclass
class VendorPlan:
    vendor_id: str
    count: int
    min_lines_per_invoice: int = 1
    max_lines_per_invoice: int = 3


@dataclass
class Plan:
    total_count: int
    date_range: DateRange
    vendor_mix: list
    allow_price_variation: bool | None = None
    price_variation_pct: float | None = None
    business_days_only: bool = True
    status: str | None = None
    currency: str | None = None


def test_force_no_tax_sets_all_lines_to_exempt():
    vendor = Vendor(
        id="VEND-BUILDRIGHT",
        name="BuildRight Cement",
        xero_contact_id="contact-1",
        xero_account_number=None,
        is_supplier=True,
        payment_terms={"type": "DAYSAFTERBILLDATE", "days": 30},
    )
    item = Item(
        id="item-1",
        code="BR-ITEM",
        name="Concrete",
        unit_price=100.0,
        account_code="400",
        tax_code="INPUT",
    )
    cat = Catalogs(
        vendors=[vendor],
        items=[item],
        accounts=[],
        tax_codes=[],
        vendor_items={"VEND-BUILDRIGHT": ["BR-ITEM"]},
    )

    plan = Plan(
        total_count=1,
        date_range=DateRange(start=date(2023, 1, 1), end=date(2023, 1, 31)),
        vendor_mix=[VendorPlan(vendor_id="VEND-BUILDRIGHT", count=1, min_lines_per_invoice=1, max_lines_per_invoice=1)],
        currency="AUD",
        status="AUTHORISED",
        business_days_only=True,
    )
    invs = generate_from_plan(cat=cat, plan=plan, run_id="TEST", seed=1, force_no_tax=True)
    assert len(invs) == 1
    assert all(ln.tax_type == "EXEMPTEXPENSES" for ln in invs[0].lines)
