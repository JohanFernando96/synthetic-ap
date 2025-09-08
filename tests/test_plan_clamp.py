from datetime import date
import os

import sys
from pathlib import Path
import importlib

sys.modules.pop("pydantic", None)
sys.modules["pydantic"] = importlib.import_module("pydantic")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

# minimal settings env vars so synthap.config.settings can load
os.environ.setdefault("OPENAI_API_KEY", "test")
os.environ.setdefault("XERO_CLIENT_ID", "cid")
os.environ.setdefault("XERO_CLIENT_SECRET", "csecret")
os.environ.setdefault("XERO_REDIRECT_URI", "http://localhost")
os.environ.setdefault("XERO_SCOPES", "accounting.transactions")
os.environ.setdefault("TIMEZONE", "UTC")
os.environ.setdefault("DEFAULT_SEED", "1")
os.environ.setdefault("FISCAL_YEAR_START_MONTH", "7")
os.environ.setdefault("DATA_DIR", str(Path(__file__).resolve().parents[1] / "data"))
os.environ.setdefault("RUNS_DIR", str(Path(__file__).resolve().parents[1] / "runs"))
os.environ.setdefault("XERO_TOKEN_FILE", "token.json")

from synthap.ai.schema import DateRange, Plan, VendorPlan
from synthap.ai.planner import clamp_plan_to_today


def _basic_plan(start, end):
    return Plan(
        total_count=1,
        date_range=DateRange(start=start, end=end),
        vendor_mix=[VendorPlan(vendor_id="V1", count=1)],
    )


def test_clamp_truncates_end():
    today = date(2024, 3, 15)
    plan = _basic_plan(date(2024, 3, 1), date(2024, 4, 1))
    clamp_plan_to_today(plan, today)
    assert plan.date_range.end == today
    assert plan.date_range.start == date(2024, 3, 1)


def test_clamp_future_start():
    today = date(2024, 3, 15)
    plan = _basic_plan(date(2024, 4, 10), date(2024, 4, 20))
    clamp_plan_to_today(plan, today)
    assert plan.date_range.start == today
    assert plan.date_range.end == today
