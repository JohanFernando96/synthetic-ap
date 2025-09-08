from typing import Any, Optional

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential_jitter

from ..config.settings import settings
from .oauth import TokenStore, refresh_token_if_needed

XERO_BASE = "https://api.xero.com/api.xro/2.0"
CONN_URL = "https://api.xero.com/connections"

_TENANT_CACHE: Optional[str] = None

def _auth_headers(tok: dict) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {tok['access_token']}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

async def resolve_tenant_id(tok: dict) -> tuple[str, dict]:
    """Resolve tenant ID, refreshing tokens on 401 responses.

    Returns a tuple of ``(tenant_id, token)`` where ``token`` is potentially
    refreshed.  The tenant ID is cached after first resolution unless explicitly
    provided via configuration.
    """

    global _TENANT_CACHE
    if settings.xero_tenant_id and settings.xero_tenant_id != "REPLACE_ME":
        return settings.xero_tenant_id, tok
    if _TENANT_CACHE:
        return _TENANT_CACHE, tok

    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(CONN_URL, headers=_auth_headers(tok))
        if r.status_code == 401:
            tok = await refresh_token_if_needed()
            r = await client.get(CONN_URL, headers=_auth_headers(tok))
        r.raise_for_status()
        conns = r.json()  # list of connections
        # choose first ORGANISATION that is active
        for c in conns:
            if c.get("tenantType") == "ORGANISATION" and c.get("tenantId"):
                _TENANT_CACHE = c["tenantId"]
                return _TENANT_CACHE, tok
        raise RuntimeError(
            "No Xero organisation connection found for this token. Check app consent."
        )

def _with_tenant(headers: dict[str, str], tenant_id: str) -> dict[str, str]:
    h = dict(headers)
    h["Xero-tenant-id"] = tenant_id
    return h

def _raise_with_context(resp: httpx.Response) -> None:
    try:
        body = resp.text
    except Exception:
        body = "<no body>"
    msg = (
        f"HTTP {resp.status_code} {resp.reason_phrase} "
        f"at {resp.request.method} {resp.request.url}\n{body}"
    )
    resp.raise_for_status()  # will raise HTTPStatusError (tenacity sees it)
    # if somehow not raised:
    raise httpx.HTTPStatusError(message=msg, request=resp.request, response=resp)

@retry(wait=wait_exponential_jitter(1, 3), stop=stop_after_attempt(5))
async def post_invoices(invoices: list[dict[str, Any]]) -> dict[str, Any]:
    tok = TokenStore.load()
    if not tok:
        tok = await refresh_token_if_needed()
    tenant_id, tok = await resolve_tenant_id(tok)
    headers = _with_tenant(_auth_headers(tok), tenant_id)
    payload = {"Invoices": invoices}

    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(f"{XERO_BASE}/Invoices", json=payload, headers=headers)
        if r.status_code == 401:
            # try refresh once
            tok = await refresh_token_if_needed()
            tenant_id, tok = await resolve_tenant_id(tok)
            r = await client.post(
                f"{XERO_BASE}/Invoices",
                json=payload,
                headers=_with_tenant(_auth_headers(tok), tenant_id),
            )
        if r.status_code >= 400:
            _raise_with_context(r)
        return r.json()


@retry(wait=wait_exponential_jitter(1, 3), stop=stop_after_attempt(5))
async def post_payments(payments: list[dict[str, Any]]) -> dict[str, Any]:
    tok = TokenStore.load()
    if not tok:
        tok = await refresh_token_if_needed()
    tenant_id, tok = await resolve_tenant_id(tok)
    headers = _with_tenant(_auth_headers(tok), tenant_id)
    payload = {"Payments": payments}

    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.put(f"{XERO_BASE}/Payments", json=payload, headers=headers)
        if r.status_code == 401:
            tok = await refresh_token_if_needed()
            tenant_id, tok = await resolve_tenant_id(tok)
            r = await client.put(
                f"{XERO_BASE}/Payments",
                json=payload,
                headers=_with_tenant(_auth_headers(tok), tenant_id),
            )
        if r.status_code >= 400:
            _raise_with_context(r)
        return r.json()


@retry(wait=wait_exponential_jitter(1, 3), stop=stop_after_attempt(5))
async def upsert_contacts(
    contacts: list[dict[str, Any]], *, use_put: bool = True
) -> dict[str, Any]:
    """Create or update contacts in Xero and return the API response."""
    tok = TokenStore.load()
    if not tok:
        tok = await refresh_token_if_needed()
    tenant_id, tok = await resolve_tenant_id(tok)
    headers = _with_tenant(_auth_headers(tok), tenant_id)
    payload = {"Contacts": contacts}

    async with httpx.AsyncClient(timeout=60) as client:
        request = client.put if use_put else client.post
        r = await request(f"{XERO_BASE}/Contacts", json=payload, headers=headers)
        if r.status_code == 401:
            tok = await refresh_token_if_needed()
            tenant_id, tok = await resolve_tenant_id(tok)
            r = await request(
                f"{XERO_BASE}/Contacts",
                json=payload,
                headers=_with_tenant(_auth_headers(tok), tenant_id),
            )
        if r.status_code >= 400:
            _raise_with_context(r)
        return r.json()
