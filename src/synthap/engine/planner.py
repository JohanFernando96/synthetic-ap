from datetime import date, timedelta
from typing import List
from ..catalogs.loader import Vendor

def business_days(start: date, end: date) -> List[date]:
    d = start
    out = []
    while d <= end:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out

def calc_due_date(issue: date, vendor: Vendor) -> date:
    t = vendor.payment_terms
    t_type = t.get("type", "DAYSAFTERBILLDATE").upper()
    if t_type == "DAYSAFTERBILLDATE":
        days = int(t.get("days", 30))
        return issue + timedelta(days=days)
    if t_type == "OFFOLLOWINGMONTH":
        dom = int(t.get("day_of_month", 31))
        y = issue.year + (1 if issue.month == 12 else 0)
        m = 1 if issue.month == 12 else issue.month + 1
        from dateutil.relativedelta import relativedelta
        start_next = date(y, m, 1)
        last_next = start_next + relativedelta(months=1) - timedelta(days=1)
        day = min(dom, last_next.day)
        return date(y, m, day)
    return issue + timedelta(days=30)
