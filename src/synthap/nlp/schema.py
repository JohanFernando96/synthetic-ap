from pydantic import BaseModel
from typing import Optional, Literal
from datetime import date

class DateRange(BaseModel):
    start: date
    end: date

class ParsedQuery(BaseModel):
    total_count: int
    date_range: DateRange
    vendor_id: Optional[str] = None
    status: Literal["unpaid"] = "unpaid"
