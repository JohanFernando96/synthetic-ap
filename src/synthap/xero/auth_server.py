from fastapi import FastAPI, Request
import uvicorn
from ..config.settings import settings
from .oauth import exchange_code_for_token, build_authorize_url, TokenStore

app = FastAPI()

@app.get("/")
async def root():
    # Clear any existing tokens to force a fresh authentication
    TokenStore.clear()
    url = build_authorize_url()
    return {
        "message": "Open the authorize URL in your browser, sign in, and consent.",
        "authorize_url": url,
        "callback": f"{settings.xero_redirect_uri}",
    }

@app.get("/callback")
async def callback(request: Request):
    err = request.query_params.get("error")
    err_desc = request.query_params.get("error_description")
    code = request.query_params.get("code")

    if err:
        return {
            "status": "error",
            "error": err,
            "error_description": err_desc,
            "hint": "Check redirect URI, client_id, and scopes in your app config and .env."
        }

    if not code:
        return {"status": "error", "error": "missing_code", "hint": "No ?code param on callback."}

    try:
        await exchange_code_for_token(code)
        return {"status": "ok", "message": "Token saved. You can close this tab."}
    except Exception as e:
        return {"status": "error", "error": "token_exchange_failed", "detail": str(e)}

def run_server():
    host = "0.0.0.0"
    # Infer port from XERO_REDIRECT_URI, fallback 5050
    try:
        port = int(settings.xero_redirect_uri.split(":")[-1].split("/")[0])
    except Exception:
        port = 5050
    uvicorn.run(app, host=host, port=port, log_level="info")