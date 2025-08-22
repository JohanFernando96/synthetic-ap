import httpx
from typing import List, Dict, Any, Optional
from tenacity import retry, wait_exponential_jitter, stop_after_attempt
from ..config.settings import settings
from .oauth import TokenStore, refresh_token_if_needed

XERO_BASE = "https://api.xero.com/api.xro/2.0"
CONN_URL = "https://api.xero.com/connections"

_TENANT_CACHE: Optional[str] = None

def _auth_headers(tok: Dict) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {tok['access_token']}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

async def resolve_tenant_id(tok: Dict) -> str:
    global _TENANT_CACHE
    if settings.xero_tenant_id and settings.xero_tenant_id != "REPLACE_ME":
        return settings.xero_tenant_id
    if _TENANT_CACHE:
        return _TENANT_CACHE

    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(CONN_URL, headers=_auth_headers(tok))
        r.raise_for_status()
        conns = r.json()  # list of connections
        # choose first ORGANISATION that is active
        for c in conns:
            if c.get("tenantType") == "ORGANISATION" and c.get("tenantId"):
                _TENANT_CACHE = c["tenantId"]
                return _TENANT_CACHE
        raise RuntimeError("No Xero organisation connection found for this token. Check app consent.")

def _with_tenant(headers: Dict[str, str], tenant_id: str) -> Dict[str, str]:
    h = dict(headers)
    h["Xero-tenant-id"] = tenant_id
    return h

def _raise_with_context(resp: httpx.Response) -> None:
    try:
        body = resp.text
    except Exception:
        body = "<no body>"
    msg = f"HTTP {resp.status_code} {resp.reason_phrase} at {resp.request.method} {resp.request.url}\n{body}"
    resp.raise_for_status()  # will raise HTTPStatusError (tenacity sees it)
    # if somehow not raised:
    raise httpx.HTTPStatusError(message=msg, request=resp.request, response=resp)

@retry(wait=wait_exponential_jitter(1, 3), stop=stop_after_attempt(5))
async def post_invoices(invoices: List[Dict[str, Any]]) -> Dict[str, Any]:
    tok = TokenStore.load()
    if not tok:
        tok = await refresh_token_if_needed()

    tenant_id = await resolve_tenant_id(tok)
    headers = _with_tenant(_auth_headers(tok), tenant_id)
    payload = {"Invoices": invoices}

    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(f"{XERO_BASE}/Invoices", json=payload, headers=headers)
        if r.status_code == 401:
            # try refresh once
            tok = await refresh_token_if_needed()
            tenant_id = await resolve_tenant_id(tok)
            r = await client.post(f"{XERO_BASE}/Invoices", json=payload, headers=_with_tenant(_auth_headers(tok), tenant_id))
        if r.status_code >= 400:
            _raise_with_context(r)
        return r.json()


@retry(wait=wait_exponential_jitter(1, 3), stop=stop_after_attempt(5))
async def post_payments(payments: List[Dict[str, Any]]) -> Dict[str, Any]:
    tok = TokenStore.load()
    if not tok:
        tok = await refresh_token_if_needed()

    tenant_id = await resolve_tenant_id(tok)
    headers = _with_tenant(_auth_headers(tok), tenant_id)
    payload = {"Payments": payments}

    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(f"{XERO_BASE}/Payments", json=payload, headers=headers)
        if r.status_code == 401:
            tok = await refresh_token_if_needed()
            tenant_id = await resolve_tenant_id(tok)
            r = await client.post(=======
        r = await client.put(f"{XERO_BASE}/Payments", json=payload, headers=headers)
        if r.status_code == 401:
            tok = await refresh_token_if_needed()
            tenant_id = await resolve_tenant_id(tok)
            r = await client.put(
                f"{XERO_BASE}/Payments", json=payload, headers=_with_tenant(_auth_headers(tok), tenant_id)
            )
        if r.status_code >= 400:
            _raise_with_context(r)
        return r.json()
