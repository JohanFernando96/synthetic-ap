from datetime import date
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pandas as pd

from synthap.nlp.parser import parse_nlp_to_query
from synthap.engine.payments import generate_payments


def test_parse_pay_count():
    pq = parse_nlp_to_query(
        "Generate 10 bills for Q1 2024 and pay for 4 bills",
        today=date(2024, 1, 1),
    )
    assert pq.total_count == 10
    assert pq.pay_count == 4
    assert not pq.pay_all


def test_parse_pay_all():
    pq = parse_nlp_to_query(
        "Generate 10 bills for Q1 2024 and pay for all",
        today=date(2024, 1, 1),
    )
    assert pq.pay_all is True
def test_generate_payments_builds_payloads():
    invoices = [
        {"InvoiceID": "1", "AmountDue": 100},
        {"InvoiceID": "2", "AmountDue": 200},
    ]
    payments = generate_payments(
        invoices,
        account_code="001",
        payment_date=date(2024, 1, 1),
    )
    assert len(payments) == 2
    assert payments[0]["Account"]["Code"] == "001"
    assert payments[0]["Date"] == "2024-01-01"
    assert all("LineItems" not in p["Invoice"] for p in payments)


def test_insert_writes_reports_with_xero_data(tmp_path, monkeypatch):
    import types, sys, synthap
    import synthap.config

    fake_settings = types.ModuleType("synthap.config.settings")

    class DummySettings:
        runs_dir = str(tmp_path)
        xero_payment_account_code = "001"

    fake_settings.settings = DummySettings()
    sys.modules["synthap.config.settings"] = fake_settings

    sys.modules.pop("pydantic", None)
    import pydantic  # reload real module

    # Provide a dummy openai module so the CLI can be imported without the
    # heavyweight dependency.
    fake_openai = types.ModuleType("openai")
    class DummyOpenAI:
        pass
    fake_openai.OpenAI = DummyOpenAI
    sys.modules["openai"] = fake_openai

    # Stub FastAPI and uvicorn since the auth server isn't exercised in tests
    fake_fastapi = types.ModuleType("fastapi")
    class DummyFastAPI:
        def __init__(self, *a, **kw):
            pass
        def get(self, *a, **kw):
            def decorator(f):
                return f
            return decorator
    class DummyRequest:
        def __init__(self, *a, **kw):
            self.query_params = {}
    fake_fastapi.FastAPI = DummyFastAPI
    fake_fastapi.Request = DummyRequest
    sys.modules["fastapi"] = fake_fastapi
    fake_uvicorn = types.ModuleType("uvicorn")
    fake_uvicorn.run = lambda *a, **kw: None
    sys.modules["uvicorn"] = fake_uvicorn

    from synthap import cli

    base = tmp_path / "run1"
    base.mkdir()

    inv_df = pd.DataFrame(
        [
            {
                "reference": "ABC",
                "contact_id": "c1",
                "currency": "USD",
                "date": "2024-01-01",
                "due_date": "2024-01-31",
                "status": "AUTHORISED",
                "vendor_id": "v1",
            }
        ]
    )
    inv_df.to_parquet(base / "invoices.parquet", index=False)

    line_df = pd.DataFrame(
        [
            {
                "reference": "ABC",
                "description": "Item",
                "quantity": 1,
                "unit_amount": 100,
                "account_code": "200",
                "tax_type": "NONE",
                "line_amount": 100,
            }
        ]
    )
    line_df.to_parquet(base / "invoice_lines.parquet", index=False)

    (base / "to_pay.json").write_text(
        json.dumps({"run_id": "run1", "references": ["ABC"]})
    )

    monkeypatch.setattr(cli.settings, "runs_dir", str(tmp_path))

    async def fake_post_invoices(batch):
        return {
            "Invoices": [
                {
                    "InvoiceID": "inv1",
                    "InvoiceNumber": "INV-1",
                    "Reference": "ABC",
                    "AmountDue": 100.0,
                }
            ]
        }

    async def fake_post_payments(payments):
        return {
            "Payments": [
                {
                    "PaymentID": "pay1",
                    "Invoice": {"InvoiceID": "inv1"},
                    "Amount": 100.0,
                }
            ]
        }

    monkeypatch.setattr(cli, "post_invoices", fake_post_invoices)
    monkeypatch.setattr(cli, "post_payments", fake_post_payments)

    cli.insert(run_id="run1", reference=None, limit=None)

    inv_report = json.loads((base / "invoice_report.json").read_text())
    pay_report = json.loads((base / "payment_report.json").read_text())
    log_report = json.loads((base / "xero_log.json").read_text())

    assert inv_report["run_id"] == "run1"
    assert inv_report["invoices"][0]["InvoiceID"] == "inv1"
    assert pay_report["run_id"] == "run1"
    assert pay_report["payments"][0]["PaymentID"] == "pay1"
    actions = [e["action"] for e in log_report["events"]]
    assert "post_invoices" in actions and "post_payments" in actions
