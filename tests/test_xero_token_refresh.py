import asyncio
import sys
import types
from pathlib import Path

import httpx

# Ensure the package path and stub settings to avoid env dependency
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

fake_settings = types.ModuleType("synthap.config.settings")


class DummySettings:
    xero_tenant_id = None
    xero_payment_account_code = "101"


fake_settings.settings = DummySettings()
sys.modules["synthap.config.settings"] = fake_settings

from synthap.xero import client as xc  # noqa: E402


def test_resolve_tenant_refreshes_expired_token(monkeypatch):
    tok = {"access_token": "old", "refresh_token": "r"}
    xc._TENANT_CACHE = None  # ensure cache doesn't bypass logic

    class DummyClient:
        def __init__(self):
            self.first = True
        async def __aenter__(self):
            return self
        async def __aexit__(self, exc_type, exc, tb):
            pass
        async def get(self, url, headers):
            if self.first:
                self.first = False
                return httpx.Response(401, request=httpx.Request("GET", url))
            return httpx.Response(
                200,
                json=[{"tenantType": "ORGANISATION", "tenantId": "TEN"}],
                request=httpx.Request("GET", url),
            )

    monkeypatch.setattr(xc.httpx, "AsyncClient", lambda *a, **kw: DummyClient())

    called = {}
    async def fake_refresh():
        called["yes"] = True
        tok["access_token"] = "new"
        return tok
    monkeypatch.setattr(xc, "refresh_token_if_needed", fake_refresh)

    tenant_id, newtok = asyncio.run(xc.resolve_tenant_id(tok))
    assert tenant_id == "TEN"
    assert called.get("yes")
    assert newtok["access_token"] == "new"


def test_post_invoices_refreshes_and_uses_new_token(monkeypatch):
    tok = {"access_token": "old", "refresh_token": "r"}
    xc._TENANT_CACHE = None

    class DummyClient:
        def __init__(self):
            self.step = 0
        async def __aenter__(self):
            return self
        async def __aexit__(self, exc_type, exc, tb):
            pass
        async def get(self, url, headers):
            assert url == xc.CONN_URL
            if self.step == 0:
                self.step += 1
                return httpx.Response(401, request=httpx.Request("GET", url))
            return httpx.Response(
                200,
                json=[{"tenantType": "ORGANISATION", "tenantId": "TEN"}],
                request=httpx.Request("GET", url),
            )
        async def post(self, url, json, headers):
            assert headers["Authorization"] == "Bearer new"
            return httpx.Response(200, json={"Invoices": []}, request=httpx.Request("POST", url))

    monkeypatch.setattr(xc.httpx, "AsyncClient", lambda *a, **kw: DummyClient())
    monkeypatch.setattr(xc.TokenStore, "load", staticmethod(lambda: tok))
    monkeypatch.setattr(xc.TokenStore, "save", staticmethod(lambda t: None))

    async def fake_refresh():
        tok["access_token"] = "new"
        return tok
    monkeypatch.setattr(xc, "refresh_token_if_needed", fake_refresh)

    asyncio.run(xc.post_invoices([{}]))
