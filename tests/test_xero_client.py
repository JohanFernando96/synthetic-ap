import asyncio
import httpx
import sys
from pathlib import Path
import types

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

fake_settings = types.ModuleType("synthap.config.settings")


class DummySettings:
    xero_tenant_id = None
    xero_payment_account_code = "101"


fake_settings.settings = DummySettings()
sys.modules["synthap.config.settings"] = fake_settings

from synthap.xero import client as xc


def test_post_payments_uses_put(monkeypatch):
    called = {}

    class DummyClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            pass

        async def put(self, url, json, headers):
            called['method'] = 'PUT'
            return httpx.Response(200, json={"Payments": []})

    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **kw: DummyClient())
    monkeypatch.setattr(xc.TokenStore, "load", staticmethod(lambda: {"access_token": "tok"}))

    async def fake_resolve(tok):
        return "tenant"

    monkeypatch.setattr(xc, "resolve_tenant_id", fake_resolve)

    payments = [
        {
            "Invoice": {"InvoiceID": "1"},
            "Account": {"Code": "001"},
            "Date": "2024-01-01",
            "Amount": 10,
        }
    ]

    asyncio.run(xc.post_payments(payments))
    assert called.get('method') == 'PUT'
