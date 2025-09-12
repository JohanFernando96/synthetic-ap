from __future__ import annotations
from pydantic import BaseModel, Field, field_validator
from typing import List, Optional
from datetime import date

class DateRange(BaseModel):
    start: date
    end: date

class VendorPlan(BaseModel):
    vendor_id: str
    count: int
    min_lines_per_invoice: int = 1
    max_lines_per_invoice: int = 3

    @field_validator("count")
    @classmethod
    def positive_count(cls, v):
        if v < 0: raise ValueError("count must be >= 0")
        return v

class Plan(BaseModel):
    rationale: Optional[str] = None
    total_count: int
    date_range: DateRange
    vendor_mix: List[VendorPlan] = Field(default_factory=list)

    allow_price_variation: Optional[bool] = None
    price_variation_pct: Optional[float] = None
    business_days_only: Optional[bool] = None
    status: Optional[str] = None
    currency: Optional[str] = None

    @field_validator("total_count")
    @classmethod
    def total_positive(cls, v):
        if v <= 0: raise ValueError("total_count must be > 0")
        return v

    def normalize_counts(self) -> None:
        s = sum(v.count for v in self.vendor_mix)
        if s == self.total_count:
            return
        # Simple fix-up: nudge first vendor
        if self.vendor_mix:
            diff = self.total_count - s
            self.vendor_mix[0].count += diff
            if self.vendor_mix[0].count < 0:
                self.vendor_mix[0].count = 0

class SyntheticContactRequest(BaseModel):
    industry: str
    num_contacts: int
    items_per_vendor: int = 2

class SyntheticContactData(BaseModel):
    id: str  # Generated vendor ID
    name: str
    is_supplier: bool = True
    payment_terms: dict = Field(default_factory=lambda: {"type": "DAYSAFTERBILLDATE", "days": 30})
    xero_contact_id: Optional[str] = None  # Will be populated after Xero API call
    xero_account_number: Optional[str] = None

class SyntheticItemData(BaseModel):
    id: str  # Generated UUID
    code: str
    name: str
    unit_price: float
    account_code: str = "453"  # Default account code for inventory
    tax_code: str = "INPUT"
    price_variance_pct: float = 0.10

class SyntheticVendorItemRelation(BaseModel):
    vendor_id: str
    item_codes: List[str]