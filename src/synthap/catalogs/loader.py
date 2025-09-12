from pathlib import Path
import yaml
from pydantic import BaseModel, field_validator
from typing import List, Dict, Any, Optional

class Vendor(BaseModel):
    id: str
    name: str
    xero_contact_id: str | None = None  # Make it optional with None as default
    xero_account_number: str | None = None
    is_supplier: bool = True
    payment_terms: Dict[str, Any]

class Item(BaseModel):
    id: str
    code: str
    name: str
    unit_price: float
    account_code: str
    tax_code: str
    price_variance_pct: float = 0.10

class Account(BaseModel):
    code: str
    name: str
    type: str
    tax_code: str

class TaxCode(BaseModel):
    code: str
    rate: float

class Catalogs(BaseModel):
    vendors: List[Vendor]
    items: List[Item]
    accounts: List[Account]
    tax_codes: List[TaxCode]
    vendor_items: Dict[str, List[str]]

    @field_validator("vendor_items")
    @classmethod
    def ensure_vendor_items(cls, v):
        assert isinstance(v, dict), "vendor_items must be a mapping"
        return v

def load_yaml(path: Path) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def load_catalogs(base_dir: str) -> Catalogs:
    base = Path(base_dir) / "catalogs"
    vendors = load_yaml(base / "vendors.yaml")["vendors"]
    items = load_yaml(base / "items.yaml")["items"]
    accounts = load_yaml(base / "chart_of_accounts.yaml")["accounts"]
    tax_codes = load_yaml(base / "tax_codes.yaml")["tax_codes"]
    vi = load_yaml(base / "vendor_items.yaml")["vendor_items"]

    vi_map: Dict[str, List[str]] = {}
    for entry in vi:
        vi_map[entry["vendor_id"]] = entry.get("item_codes", [])

    cat = Catalogs(
        vendors=[Vendor(**v) for v in vendors],
        items=[Item(**i) for i in items],
        accounts=[Account(**a) for a in accounts],
        tax_codes=[TaxCode(**t) for t in tax_codes],
        vendor_items=vi_map,
    )

    account_codes = {a.code for a in cat.accounts}
    item_codes = {i.code for i in cat.items}
    tax_set = {t.code for t in cat.tax_codes}
    vendor_ids = {v.id for v in cat.vendors}

    for it in cat.items:
        if it.account_code not in account_codes:
            raise ValueError(f"Item {it.code} refers to missing account {it.account_code}")
        if it.tax_code not in tax_set:
            raise ValueError(f"Item {it.code} refers to missing tax code {it.tax_code}")

    for v_id, codes in cat.vendor_items.items():
        if v_id not in vendor_ids:
            raise ValueError(f"vendor_items: unknown vendor {v_id}")
        for c in codes:
            if c not in item_codes:
                raise ValueError(f"vendor_items[{v_id}]: unknown item code {c}")

    return cat
