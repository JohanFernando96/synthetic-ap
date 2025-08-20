import json
from pathlib import Path
import httpx
from urllib.parse import urlencode
from typing import Dict, Optional
from ..config.settings import settings

AUTH_URL = "https://login.xero.com/identity/connect/authorize"
TOKEN_URL = "https://identity.xero.com/connect/token"

def _token_path() -> Path:
    return Path(settings.token_file)

class TokenStore:
    @classmethod
    def load(cls) -> Optional[Dict]:
        p = _token_path()
        if not p.exists():
            return None
        return json.loads(p.read_text())

    @classmethod
    def save(cls, tok: Dict) -> None:
        _token_path().write_text(json.dumps(tok, indent=2))

def build_authorize_url(state: str = "xero-local"):
    params = {
        "response_type": "code",
        "client_id": settings.xero_client_id,
        "redirect_uri": settings.xero_redirect_uri,
        "scope": settings.xero_scopes,
        "state": state,
        "prompt": "consent",
    }
    return f"{AUTH_URL}?{urlencode(params)}"

async def exchange_code_for_token(code: str) -> Dict:
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": settings.xero_redirect_uri,
    }
    auth = (settings.xero_client_id, settings.xero_client_secret)
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(TOKEN_URL, data=data, auth=auth)
        r.raise_for_status()
        tok = r.json()
    TokenStore.save(tok)
    return tok

async def refresh_token_if_needed() -> Dict:
    tok = TokenStore.load()
    if not tok or "refresh_token" not in tok:
        raise RuntimeError("No refresh_token stored. Run `auth-init` first.")
    data = {
        "grant_type": "refresh_token",
        "refresh_token": tok["refresh_token"],
    }
    auth = (settings.xero_client_id, settings.xero_client_secret)
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(TOKEN_URL, data=data, auth=auth)
        r.raise_for_status()
        newtok = r.json()
    TokenStore.save(newtok)
    return newtok
