from __future__ import annotations
import re
from datetime import date, timedelta
from typing import NamedTuple

class DateRange(NamedTuple):
    start: date
    end: date

def _week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())

def resolve_period_au(text: str, today: date) -> DateRange:
    t = text.lower().strip()

    # absolute quarter: Q[1-4] YYYY (AU FY naming: Q1=Jul-Sep of that YYYY)
    m = re.search(r"\bq([1-4])\s+(\d{4})\b", t)
    if m:
        q = int(m.group(1)); y = int(m.group(2))
        if q == 1:  return DateRange(date(y,7,1),  date(y,9,30))
        if q == 2:  return DateRange(date(y,10,1), date(y,12,31))
        if q == 3:  return DateRange(date(y+1,1,1), date(y+1,3,31))
        if q == 4:  return DateRange(date(y+1,4,1), date(y+1,6,30))

    if "yesterday" in t:
        d = today - timedelta(days=1)
        return DateRange(d, d)
    if "today" in t:
        return DateRange(today, today)
    if "last week" in t:
        end = _week_start(today) - timedelta(days=1)
        start = end - timedelta(days=6)
        return DateRange(start, end)
    if "last month" in t:
        y = today.year; mth = today.month
        prev_y = y if mth > 1 else y-1
        prev_m = mth-1 if mth>1 else 12
        from calendar import monthrange
        return DateRange(date(prev_y, prev_m, 1), date(prev_y, prev_m, monthrange(prev_y, prev_m)[1]))
    if "last quarter" in t:
        # AU quarters rolling based on today
        mth = today.month
        if mth in (7,8,9):     # Q1
            return DateRange(date(today.year-1,4,1), date(today.year-1,6,30)) # last Q4 prev FY
        if mth in (10,11,12):  # Q2
            return DateRange(date(today.year,7,1), date(today.year,9,30))
        if mth in (1,2,3):     # Q3
            return DateRange(date(today.year,10,1), date(today.year,12,31))
        if mth in (4,5,6):     # Q4
            return DateRange(date(today.year,1,1), date(today.year,3,31))

    # default: current month
    from calendar import monthrange
    return DateRange(date(today.year, today.month, 1), date(today.year, today.month, monthrange(today.year, today.month)[1]))
