from datetime import date
import json
import sys
from pathlib import Path
import random

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pandas as pd

from synthap.nlp.parser import parse_nlp_to_query
from synthap.engine.payments import generate_payments
from synthap.engine.payments import select_invoices_to_pay


def test_parse_pay_count():
    pq = parse_nlp_to_query(
        "Generate 10 bills for Q1 2024 and pay for 4 bills",
        today=date(2024, 1, 1),
    )
    assert pq.total_count == 10
    assert pq.pay_count == 4
    assert not pq.pay_all


def test_parse_pay_count_with_only():
    pq = parse_nlp_to_query(
        "Generate 6 bills for the Q1 2023 pay for only 2",
        today=date(2023, 1, 1),
    )
    assert pq.pay_count == 2
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
        account_code="101",
        payment_date=date(2024, 1, 1),
    )
    assert len(payments) == 2
    assert payments[0]["Account"]["Code"] == "101"
    assert payments[0]["Date"] == "2024-01-01"
    assert payments[0]["Invoice"]["LineItems"] == []


def test_generate_payments_date_within_term(monkeypatch):
    invoices = [
        {
            "InvoiceID": "1",
            "AmountDue": 100,
            "DateString": "2024-01-01T00:00:00",
            "DueDateString": "2024-01-10T00:00:00",
        }
    ]

    monkeypatch.setattr(random, "randint", lambda a, b: 0)
    payments = generate_payments(invoices, account_code="101")
    assert payments[0]["Date"] == "2024-01-01"
    assert payments[0]["Date"] < "2024-01-10"


def test_generate_payments_pay_on_due_date():
    invoices = [
        {
            "InvoiceID": "1",
            "AmountDue": 100,
            "DateString": "2024-01-01T00:00:00",
            "DueDateString": "2024-01-10T00:00:00",
        }
    ]

    payments = generate_payments(invoices, account_code="101", pay_on_due_date=True)
    assert payments[0]["Date"] == "2024-01-10"


def test_generate_payments_overdue(monkeypatch):
    invoices = [
        {
            "InvoiceID": "1",
            "AmountDue": 100,
            "DateString": "2024-01-01T00:00:00",
            "DueDateString": "2024-01-10T00:00:00",
        }
    ]
    monkeypatch.setattr(random, "randint", lambda a, b: 0)
    payments = generate_payments(
        invoices,
        account_code="101",
        allow_overdue=True,
    )
    assert payments[0]["Date"] > "2024-01-10"


def test_select_invoices_to_pay_respects_config():
    all_refs = ["A", "B", "C"]
    rng = random.Random(42)

    # No directive and config forbids paying
    refs = select_invoices_to_pay(all_refs, None, False, False, rng)
    assert refs == []

    # No directive but config allows random payment
    refs2 = select_invoices_to_pay(all_refs, None, False, True, rng)
    assert 1 <= len(refs2) <= len(all_refs)


def test_insert_writes_reports_with_xero_data(tmp_path, monkeypatch):
    import types, sys, synthap
    import synthap.config

    fake_settings = types.ModuleType("synthap.config.settings")

    class DummySettings:
        runs_dir = str(tmp_path)
        xero_payment_account_code = "101"
        pay_on_due_date = False
        data_dir = str(tmp_path)

    fake_settings.settings = DummySettings()
    sys.modules["synthap.config.settings"] = fake_settings

    # Ensure runtime config has payment defaults
    import synthap.cli as cli
    from synthap.config import runtime_config as rc_module

    class DummyRuntimeCfg(rc_module.RuntimeConfig):
        def __init__(self):
            super().__init__(payments=rc_module.PaymentCfg())

    def fake_load_runtime_config(base_dir: str):
        return DummyRuntimeCfg()

    from synthap import cli
    monkeypatch.setattr(cli, "load_runtime_config", fake_load_runtime_config)

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
