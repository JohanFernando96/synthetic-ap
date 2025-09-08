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
from typer.testing import CliRunner
import json
from datetime import timedelta




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


def test_cli_generate_limit_to_today(tmp_path, monkeypatch):
    today = date.today()

    import types, sys, importlib.util
    from types import SimpleNamespace
    from pathlib import Path

    # Stub external modules before importing CLI
    dummy_client = types.ModuleType("synthap.xero.client")
    dummy_client.post_invoices = lambda *a, **k: None
    dummy_client.post_payments = lambda *a, **k: None
    dummy_client.resolve_tenant_id = lambda tok: ("TEN", tok)
    dummy_client.upsert_contacts = lambda *a, **k: None
    dummy_mapper = types.ModuleType("synthap.xero.mapper")
    dummy_mapper.map_invoice = lambda inv: {}
    dummy_oauth = types.ModuleType("synthap.xero.oauth")
    class DummyTokenStore:
        load = staticmethod(lambda: None)
        save = staticmethod(lambda tok: None)
    dummy_oauth.TokenStore = DummyTokenStore
    monkeypatch.setitem(sys.modules, "synthap.xero.client", dummy_client)
    monkeypatch.setitem(sys.modules, "synthap.xero.mapper", dummy_mapper)
    monkeypatch.setitem(sys.modules, "synthap.xero.oauth", dummy_oauth)

    # Ensure real settings module with env vars
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setenv("XERO_CLIENT_ID", "cid")
    monkeypatch.setenv("XERO_CLIENT_SECRET", "csecret")
    monkeypatch.setenv("XERO_REDIRECT_URI", "http://localhost")
    monkeypatch.setenv("XERO_SCOPES", "accounting.transactions")
    monkeypatch.setenv("TIMEZONE", "UTC")
    monkeypatch.setenv("DEFAULT_SEED", "1")
    monkeypatch.setenv("FISCAL_YEAR_START_MONTH", "7")
    monkeypatch.setenv("DATA_DIR", str(Path(__file__).resolve().parents[1] / "data"))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path))
    monkeypatch.setenv("XERO_TOKEN_FILE", "token.json")
    spec = importlib.util.spec_from_file_location(
        "synthap.config.settings",
        Path(__file__).resolve().parents[1] / "src/synthap/config/settings.py",
    )
    real_settings = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(real_settings)  # type: ignore[assignment]
    monkeypatch.setitem(sys.modules, "synthap.config.settings", real_settings)

    import synthap.cli as cli
    import synthap.ai.planner as planner

    class DummyPlan:
        def __init__(self):
            self.date_range = SimpleNamespace(
                start=today - timedelta(days=1),
                end=today + timedelta(days=7),
            )
            self.allow_price_variation = None
            self.price_variation_pct = None
            self.business_days_only = None
            self.vendor_mix = []
        def model_dump(self, mode="json"):
            return {
                "total_count": 1,
                "date_range": {
                    "start": self.date_range.start.isoformat(),
                    "end": self.date_range.end.isoformat(),
                },
                "vendor_mix": [],
                "allow_price_variation": None,
                "price_variation_pct": None,
                "business_days_only": None,
                "status": "AUTHORISED",
                "currency": "AUD",
            }

    monkeypatch.setattr(planner, "plan_from_query", lambda *a, **k: DummyPlan())
    clamp_called = {}
    def fake_clamp(plan, today_arg):
        clamp_called["yes"] = True
    monkeypatch.setattr(planner, "clamp_plan_to_today", fake_clamp)
    monkeypatch.setattr(cli, "load_catalogs", lambda data_dir: None)
    cfg = SimpleNamespace(force_no_tax=False,
                          artifacts=SimpleNamespace(include_meta_json=False),
                          payments=SimpleNamespace(pay_when_unspecified=False))
    monkeypatch.setattr(cli, "load_runtime_config", lambda data_dir: cfg)
    monkeypatch.setattr(cli, "parse_nlp_to_query", lambda *a, **k: SimpleNamespace(pay_count=None, pay_all=False))
    monkeypatch.setattr(cli, "generate_from_plan", lambda **k: [])
    monkeypatch.setattr(cli, "validate_invoices", lambda *a, **k: None)
    monkeypatch.setattr(cli, "to_rows", lambda invoices: (None, None))
    monkeypatch.setattr(cli, "write_parquet", lambda *a, **k: None)
    monkeypatch.setattr(cli, "write_json", lambda *a, **k: None)
    monkeypatch.setattr(cli, "map_invoice", lambda inv: {})
    monkeypatch.setattr(cli, "select_invoices_to_pay", lambda *a, **k: [])

    cli.generate(query="x", seed=1, limit_to_today=True, allow_price_variation=None, price_variation_pct=None)
    assert clamp_called.get("yes")
