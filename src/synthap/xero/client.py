from typing import Any, Optional
import json
import logging

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential_jitter

from ..config.settings import settings
from .oauth import TokenStore, refresh_token_if_needed

# Set up module-level logger
logger = logging.getLogger(__name__)

XERO_BASE = "https://api.xero.com/api.xro/2.0"
CONN_URL = "https://api.xero.com/connections"

_TENANT_CACHE: Optional[str] = None

def _auth_headers(tok: dict) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {tok['access_token']}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

def debug_token():
    """Debug function to check token and tenant ID."""
    tok = TokenStore.load()
    if not tok:
        logger.error("No token found")
        return
    
    logger.info(f"Token exists with keys: {list(tok.keys())}")
    if 'tenant_id' in tok:
        logger.info(f"Tenant ID in token: {tok['tenant_id']}")
    else:
        logger.error("No tenant_id in token")
    
    if 'access_token' in tok:
        logger.info(f"Access token: {tok['access_token'][:10]}...")
    else:
        logger.error("No access_token in token")

async def resolve_tenant_id(tok: dict) -> tuple[str, dict]:
    """Resolve tenant ID, refreshing tokens on 401 responses."""
    global _TENANT_CACHE
    
    # If tenant ID is in the token, use it
    if 'tenant_id' in tok and tok['tenant_id']:
        logger.info(f"Using tenant ID from token: {tok['tenant_id']}")
        return tok['tenant_id'], tok
        
    # If tenant ID is in settings, use it
    if settings.xero_tenant_id and settings.xero_tenant_id != "REPLACE_ME":
        logger.info(f"Using tenant ID from settings: {settings.xero_tenant_id}")
        return settings.xero_tenant_id, tok
        
    # If tenant ID is in cache, use it
    if _TENANT_CACHE:
        logger.info(f"Using cached tenant ID: {_TENANT_CACHE}")
        return _TENANT_CACHE, tok

    # Otherwise, fetch from connections API
    logger.info("Fetching tenant ID from connections API")
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(CONN_URL, headers=_auth_headers(tok))
        if r.status_code == 401:
            # Refresh the token if unauthorized
            logger.info("Connections API returned 401, refreshing token")
            tok = await refresh_token_if_needed()
            r = await client.get(CONN_URL, headers=_auth_headers(tok))
        
        r.raise_for_status()
        conns = r.json()
        logger.debug(f"Got connections: {json.dumps(conns, indent=2)}")
        
        # choose first ORGANISATION that is active
        for c in conns:
            if c.get("tenantType") == "ORGANISATION" and c.get("tenantId"):
                _TENANT_CACHE = c["tenantId"]
                # Save the tenant_id in the token file for future use
                tok["tenant_id"] = _TENANT_CACHE
                TokenStore.save(tok)
                logger.info(f"Found and saved tenant ID: {_TENANT_CACHE}")
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
        body = resp.json()  # Attempt to parse JSON response
    except Exception:
        body = resp.text  # Fallback to raw text if JSON parsing fails
    msg = (
        f"HTTP {resp.status_code} {resp.reason_phrase} "
        f"at {resp.request.method} {resp.request.url}\n{body}"
    )
    resp.raise_for_status()  # will raise HTTPStatusError (tenacity sees it)
    # if somehow not raised:
    raise httpx.HTTPStatusError(message=msg, request=resp.request, response=resp)

def validate_invoice_payload(invoices: list[dict[str, Any]]) -> None:
    for invoice in invoices:
        if not invoice.get("InvoiceNumber"):
            raise ValueError("InvoiceNumber is required")
        if not invoice.get("Contact", {}).get("ContactID"):
            raise ValueError("ContactID is required")
        if not invoice.get("LineItems"):
            raise ValueError("At least one LineItem is required")
        for line_item in invoice["LineItems"]:
            if not line_item.get("Description"):
                raise ValueError("LineItem Description is required")
            if not line_item.get("Quantity"):
                raise ValueError("LineItem Quantity is required")
            if not line_item.get("UnitAmount"):
                raise ValueError("LineItem UnitAmount is required")
            if not line_item.get("AccountCode"):
                raise ValueError("LineItem AccountCode is required")
            if not line_item.get("TaxType"):
                raise ValueError("LineItem TaxType is required")

def validate_contact_payload(contacts: list[dict[str, Any]]) -> None:
    """Validate contact payload before sending to Xero API."""
    for contact in contacts:
        if not contact.get("Name"):
            raise ValueError("Contact Name is required")
            
        # Check for proper structure of Addresses
        if "Addresses" in contact:
            if not isinstance(contact["Addresses"], list):
                raise ValueError("Addresses must be an array")
            for address in contact["Addresses"]:
                if not isinstance(address, dict):
                    raise ValueError("Each Address must be an object")
                if "AddressType" not in address:
                    raise ValueError("AddressType is required in Address")
                    
        # Check for proper structure of Phones
        if "Phones" in contact:
            if not isinstance(contact["Phones"], list):
                raise ValueError("Phones must be an array")
            for phone in contact["Phones"]:
                if not isinstance(phone, dict):
                    raise ValueError("Each Phone must be an object")
                if "PhoneType" not in phone:
                    raise ValueError("PhoneType is required in Phone")

@retry(wait=wait_exponential_jitter(1, 3), stop=stop_after_attempt(5))
async def post_invoices(invoices: list[dict[str, Any]]) -> dict[str, Any]:
    validate_invoice_payload(invoices)  # Validate payload before sending
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
            logger.error("Xero API error response: %s", r.text)
            logger.error("Payload sent: %s", json.dumps(payload, indent=2))
        return r.json()

@retry(wait=wait_exponential_jitter(1, 3), stop=stop_after_attempt(5))
async def post_payments(payments: list[dict[str, Any]]) -> dict[str, Any]:
    """Post payments to Xero API."""
    tok = TokenStore.load()
    if not tok:
        tok = await refresh_token_if_needed()
    tenant_id, tok = await resolve_tenant_id(tok)
    headers = _with_tenant(_auth_headers(tok), tenant_id)
    payload = {"Payments": payments}

    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(f"{XERO_BASE}/Payments", json=payload, headers=headers)
        if r.status_code == 401:
            # try refresh once
            tok = await refresh_token_if_needed()
            tenant_id, tok = await resolve_tenant_id(tok)
            r = await client.post(
                f"{XERO_BASE}/Payments",
                json=payload,
                headers=_with_tenant(_auth_headers(tok), tenant_id),
            )
        if r.status_code >= 400:
            logger.error("Xero API error response: %s", r.text)
            logger.error("Payload sent: %s", json.dumps(payload, indent=2))
        return r.json()

@retry(wait=wait_exponential_jitter(1, 3), stop=stop_after_attempt(5))
async def get_contacts() -> dict[str, Any]:
    """Get contacts from Xero API."""
    tok = TokenStore.load()
    if not tok:
        tok = await refresh_token_if_needed()
    tenant_id, tok = await resolve_tenant_id(tok)
    headers = _with_tenant(_auth_headers(tok), tenant_id)

    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.get(f"{XERO_BASE}/Contacts", headers=headers)
        if r.status_code == 401:
            # try refresh once
            logger.info("Token expired during get_contacts, refreshing...")
            tok = await refresh_token_if_needed()
            tenant_id, tok = await resolve_tenant_id(tok)
            r = await client.get(
                f"{XERO_BASE}/Contacts",
                headers=_with_tenant(_auth_headers(tok), tenant_id),
            )
        if r.status_code >= 400:
            logger.error("Xero API error response: %s", r.text)
        return r.json()

@retry(wait=wait_exponential_jitter(1, 3), stop=stop_after_attempt(5))
async def create_contacts(contacts: list[dict[str, Any]]) -> dict[str, Any]:
    """Create contacts in Xero API."""
    logger.info(f"Creating {len(contacts)} contacts in Xero")
    
    # Validate contacts structure
    validate_contact_payload(contacts)
    
    tok = TokenStore.load()
    if not tok:
        tok = await refresh_token_if_needed()
        
    # Debug token before using it
    debug_token()
    
    tenant_id, tok = await resolve_tenant_id(tok)
    headers = _with_tenant(_auth_headers(tok), tenant_id)
    payload = {"Contacts": contacts}
    
    logger.debug(f"Xero create_contacts payload: {json.dumps(payload, indent=2)}")
    
    async with httpx.AsyncClient(timeout=60) as client:
        # Log the full request details for debugging
        logger.info(f"Sending request to {XERO_BASE}/Contacts with tenant ID: {tenant_id}")
        logger.debug(f"Headers: {json.dumps(headers, indent=2)}")
        
        r = await client.post(f"{XERO_BASE}/Contacts", json=payload, headers=headers)
        if r.status_code == 401:
            logger.info("Token expired, refreshing...")
            tok = await refresh_token_if_needed()
            tenant_id, tok = await resolve_tenant_id(tok)
            
            # Log refreshed token info
            logger.info(f"Using refreshed token with tenant ID: {tenant_id}")
            
            r = await client.post(
                f"{XERO_BASE}/Contacts",
                json=payload,
                headers=_with_tenant(_auth_headers(tok), tenant_id),
            )
        
        if r.status_code >= 400:
            logger.error(f"Xero API error response: {r.text}")
            logger.error(f"Payload sent: {json.dumps(payload, indent=2)}")
        else:
            logger.info(f"Successfully created contacts in Xero")
            logger.debug(f"Xero response: {r.text}")
        
        return r.json()