from dataclasses import dataclass
from datetime import date
import sys
from pathlib import Path
import types

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

# Minimal pydantic stub so ai.schema imports succeed
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


def _basic_catalog() -> Catalogs:
    vendor = Vendor(
        id="VEND-ACME",
        name="ACME & Sons Co.",
        xero_contact_id="c1",
        xero_account_number=None,
        is_supplier=True,
        payment_terms={"type": "DAYSAFTERBILLDATE", "days": 30},
    )
    item = Item(
        id="item-1",
        code="IT1",
        name="Widget",
        unit_price=10.0,
        account_code="400",
        tax_code="NONE",
    )
    return Catalogs(
        vendors=[vendor],
        items=[item],
        accounts=[],
        tax_codes=[],
        vendor_items={"VEND-ACME": ["IT1"]},
    )


def test_reference_slug_trimmed():
    cat = _basic_catalog()
    plan = Plan(
        total_count=1,
        date_range=DateRange(start=date(2024, 3, 1), end=date(2024, 3, 3)),
        vendor_mix=[VendorPlan(vendor_id="VEND-ACME", count=1)],
        currency="USD",
    )
    invs = generate_from_plan(cat=cat, plan=plan, run_id="RUN123456", seed=1)
    ref = invs[0].reference
    assert "--" not in ref  # slug truncation shouldn't leave double dashes
    assert "ACME-SONS" in ref


def test_business_days_only_controls_weekends():
    cat = _basic_catalog()
    plan_bd = Plan(
        total_count=3,
        date_range=DateRange(start=date(2024, 3, 1), end=date(2024, 3, 3)),
        vendor_mix=[VendorPlan(vendor_id="VEND-ACME", count=3, min_lines_per_invoice=1, max_lines_per_invoice=1)],
        business_days_only=True,
    )
    invs_bd = generate_from_plan(cat, plan_bd, run_id="BD", seed=0)
    assert all(inv.date.weekday() < 5 for inv in invs_bd)

    plan_all = Plan(
        total_count=3,
        date_range=DateRange(start=date(2024, 3, 1), end=date(2024, 3, 3)),
        vendor_mix=[VendorPlan(vendor_id="VEND-ACME", count=3, min_lines_per_invoice=1, max_lines_per_invoice=1)],
        business_days_only=False,
    )
    invs_all = generate_from_plan(cat, plan_all, run_id="AL", seed=0)
    assert any(inv.date.weekday() >= 5 for inv in invs_all)


def test_item_selection_unique_and_repeat():
    vendor = _basic_catalog().vendors[0]
    items = [
        Item(id="i1", code="IT1", name="A", unit_price=1, account_code="400", tax_code="NONE"),
        Item(id="i2", code="IT2", name="B", unit_price=1, account_code="400", tax_code="NONE"),
        Item(id="i3", code="IT3", name="C", unit_price=1, account_code="400", tax_code="NONE"),
    ]
    cat_many = Catalogs(
        vendors=[vendor],
        items=items,
        accounts=[],
        tax_codes=[],
        vendor_items={"VEND-ACME": [it.code for it in items]},
    )
    plan = Plan(
        total_count=1,
        date_range=DateRange(start=date(2024, 3, 1), end=date(2024, 3, 1)),
        vendor_mix=[VendorPlan(vendor_id="VEND-ACME", count=1, min_lines_per_invoice=2, max_lines_per_invoice=2)],
    )
    invs = generate_from_plan(cat_many, plan, run_id="R1", seed=0)
    codes = [ln.item_code for ln in invs[0].lines]
    assert len(codes) == len(set(codes))

    cat_one = Catalogs(
        vendors=[vendor],
        items=[items[0]],
        accounts=[],
        tax_codes=[],
        vendor_items={"VEND-ACME": [items[0].code]},
    )
    invs2 = generate_from_plan(cat_one, plan, run_id="R2", seed=0)
    codes2 = [ln.item_code for ln in invs2[0].lines]
    assert len(set(codes2)) < len(codes2)
