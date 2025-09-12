import json
import os
from pathlib import Path
import httpx
from urllib.parse import urlencode
from typing import Dict, Optional, List
from ..config.settings import settings
import logging

AUTH_URL = "https://login.xero.com/identity/connect/authorize"
TOKEN_URL = "https://identity.xero.com/connect/token"
CONN_URL = "https://api.xero.com/connections"

# Configure logging
logger = logging.getLogger(__name__)

def _token_path() -> Path:
    return Path(settings.token_file)

def _auth_headers(tok: dict) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {tok['access_token']}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

class TokenStore:
    @classmethod
    def load(cls) -> Optional[Dict]:
        p = _token_path()
        if not p.exists():
            logger.warning(f"Token file not found at {p}")
            return None
        try:
            token_data = json.loads(p.read_text())
            logger.debug(f"Loaded token with keys: {list(token_data.keys())}")
            return token_data
        except Exception as e:
            logger.error(f"Error loading token: {str(e)}")
            return None

    @classmethod
    def save(cls, tok: Dict) -> None:
        try:
            token_path = _token_path()
            token_path.parent.mkdir(exist_ok=True, parents=True)
            token_path.write_text(json.dumps(tok, indent=2))
            logger.info(f"Saved token to {token_path}")
        except Exception as e:
            logger.error(f"Error saving token: {str(e)}")
    
    @classmethod
    def clear(cls) -> None:
        """Clear the token file to force a new authentication"""
        p = _token_path()
        if p.exists():
            p.unlink()
            logger.info(f"Cleared token file at {p}")

def check_scopes() -> Dict[str, bool]:
    """
    Check if the configured scopes include all required scopes for the application.
    
    Returns a dictionary with the status of each required scope.
    """
    required_scopes = [
        "accounting.contacts",
        "accounting.settings",
        "accounting.transactions"
    ]
    
    if not settings.xero_scopes:
        logger.error("No Xero scopes configured")
        return {scope: False for scope in required_scopes}
    
    configured_scopes = settings.xero_scopes.split()
    logger.info(f"Configured scopes: {configured_scopes}")
    
    result = {}
    for scope in required_scopes:
        has_scope = scope in configured_scopes
        result[scope] = has_scope
        if has_scope:
            logger.info(f"✓ Found required scope: {scope}")
        else:
            logger.error(f"✗ Missing required scope: {scope}")
    
    return result

def build_authorize_url(state: str = "xero-local"):
    """
    Build the authorization URL for Xero OAuth flow.
    
    Ensures all required scopes are included.
    """
    # Ensure required scopes are included
    required_scopes = ["accounting.contacts", "accounting.settings", "accounting.transactions"]
    
    # Get current scopes
    current_scopes = settings.xero_scopes.split() if settings.xero_scopes else []
    
    # Add any missing required scopes
    for scope in required_scopes:
        if scope not in current_scopes:
            current_scopes.append(scope)
            logger.info(f"Added missing required scope: {scope}")
    
    # Update scope parameter
    params = {
        "response_type": "code",
        "client_id": settings.xero_client_id,
        "redirect_uri": settings.xero_redirect_uri,
        "scope": " ".join(current_scopes),
        "state": state,
        "prompt": "consent",  # Always force consent screen
    }
    
    auth_url = f"{AUTH_URL}?{urlencode(params)}"
    logger.info(f"Built authorization URL with scopes: {params['scope']}")
    return auth_url

async def exchange_code_for_token(code: str) -> Dict:
    """
    Exchange authorization code for access token.
    
    Captures and stores tenant ID in the token for future use.
    """
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": settings.xero_redirect_uri,
    }
    auth = (settings.xero_client_id, settings.xero_client_secret)
    
    logger.info(f"Exchanging code for token with client ID: {settings.xero_client_id}")
    
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(TOKEN_URL, data=data, auth=auth)
        r.raise_for_status()
        tok = r.json()
        
        logger.info(f"Token exchange successful. Received token with keys: {list(tok.keys())}")
        
        # Get tenant ID immediately after authentication
        headers = _auth_headers(tok)
        r = await client.get(CONN_URL, headers=headers)
        r.raise_for_status()
        conns = r.json()
        
        logger.info(f"Found {len(conns)} connections")
        
        # Choose first ORGANISATION that is active
        for c in conns:
            if c.get("tenantType") == "ORGANISATION" and c.get("tenantId"):
                # Add tenant ID to the token data
                tok["tenant_id"] = c["tenantId"]
                # Log the tenant ID and access token
                logger.info(f"✓ Tenant ID: {tok['tenant_id']}")
                logger.info(f"✓ Access token (first 10 chars): {tok['access_token'][:10]}...")
                break
        
        if "tenant_id" not in tok:
            logger.error("No tenant ID found in connections response")
                
    TokenStore.save(tok)
    return tok

async def refresh_token_if_needed() -> Dict:
    """
    Refresh the OAuth token.
    
    Always refreshes the token and updates tenant ID.
    """
    tok = TokenStore.load()
    if not tok or "refresh_token" not in tok:
        logger.error("No refresh_token stored. Authentication required.")
        raise RuntimeError("No refresh_token stored. Run `auth-init` first.")
    
    data = {
        "grant_type": "refresh_token",
        "refresh_token": tok["refresh_token"],
    }
    auth = (settings.xero_client_id, settings.xero_client_secret)
    
    logger.info(f"Refreshing token using refresh_token (first 10 chars): {tok['refresh_token'][:10]}...")
    
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(TOKEN_URL, data=data, auth=auth)
            r.raise_for_status()
            newtok = r.json()
            
            logger.info(f"Token refresh successful. Received new token with keys: {list(newtok.keys())}")
            
            # Also fetch the connections to update the tenant ID
            headers = _auth_headers(newtok)
            r = await client.get(CONN_URL, headers=headers)
            r.raise_for_status()
            conns = r.json()
            
            logger.info(f"Found {len(conns)} connections after refresh")
            
            # Choose first ORGANISATION that is active
            for c in conns:
                if c.get("tenantType") == "ORGANISATION" and c.get("tenantId"):
                    # Add tenant ID to the token data
                    newtok["tenant_id"] = c["tenantId"]
                    logger.info(f"[OK] Refreshed token with tenant ID: {newtok['tenant_id']}")
                    break
            
            if "tenant_id" not in newtok:
                logger.error("No tenant ID found in connections response after refresh")
                # If we had a tenant ID in the old token, preserve it
                if "tenant_id" in tok:
                    newtok["tenant_id"] = tok["tenant_id"]
                    logger.info(f"Preserving previous tenant ID: {newtok['tenant_id']}")
        
        TokenStore.save(newtok)
        return newtok
    except Exception as e:
        logger.error(f"Error refreshing token: {str(e)}")
        # If refresh fails, try to use the existing token
        if "tenant_id" in tok and "access_token" in tok:
            logger.warning("Using existing token as refresh failed")
            return tok
        raise