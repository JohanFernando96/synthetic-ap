from fastapi import FastAPI, Request
import uvicorn
import socket
import logging
import os
import sys
import time
from ..config.settings import settings
from .oauth import exchange_code_for_token, build_authorize_url, TokenStore

# Configure logging
logger = logging.getLogger(__name__)

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

@app.get("/health")
async def health():
    """Health check endpoint to verify server is running."""
    return {"status": "ok", "timestamp": time.time()}

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

def is_port_in_use(port: int) -> bool:
    """Check if a port is already in use."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('localhost', port)) == 0

def find_available_port(start_port: int = 5050, max_attempts: int = 10) -> int:
    """Find an available port starting from start_port."""
    port = start_port
    for i in range(max_attempts):
        if not is_port_in_use(port):
            return port
        port += 1
    # If we couldn't find an available port, return the original
    return start_port

def get_port_from_redirect_uri():
    """Extract port from the redirect URI."""
    try:
        uri = settings.xero_redirect_uri
        if '://' in uri:
            uri = uri.split('://', 1)[1]
        if ':' in uri and '/' in uri.split(':', 1)[1]:
            return int(uri.split(':', 1)[1].split('/', 1)[0])
        return 5050  # Default port
    except Exception:
        return 5050  # Default port

def kill_process_on_port(port: int):
    """Attempt to kill any process using the specified port on Windows."""
    if os.name == 'nt':  # Windows
        try:
            os.system(f'for /f "tokens=5" %a in (\'netstat -aon ^| findstr :{port}\') do taskkill /F /PID %a')
            logger.info(f"Attempted to kill any process using port {port}")
            # Wait a moment for the port to be released
            time.sleep(1)
            return not is_port_in_use(port)
        except Exception as e:
            logger.warning(f"Could not kill processes on port {port}: {e}")
            return False
    return False

def run_server():
    """Run the authentication server with improved port handling."""
    # Configure console logging
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(logging.Formatter('%(levelname)s: %(message)s'))
    logger.addHandler(console_handler)
    logger.setLevel(logging.INFO)
    
    host = "0.0.0.0"  # Listen on all interfaces
    
    # Get port from redirect URI
    configured_port = get_port_from_redirect_uri()
    logger.info(f"Extracted port {configured_port} from redirect URI: {settings.xero_redirect_uri}")
    
    # Check if port is in use and try to resolve
    if is_port_in_use(configured_port):
        logger.warning(f"Port {configured_port} is already in use!")
        
        # First, try to kill any process using this port
        if kill_process_on_port(configured_port):
            logger.info(f"Successfully released port {configured_port}")
        else:
            # If we couldn't free the port, find an available one
            new_port = find_available_port(configured_port)
            if new_port != configured_port:
                logger.info(f"Using alternative port {new_port} instead of {configured_port}")
                
                # Update the redirect URI to use the new port
                old_uri = settings.xero_redirect_uri
                new_uri = old_uri.replace(f":{configured_port}", f":{new_port}")
                settings.xero_redirect_uri = new_uri
                
                # Show warning to user
                print(f"\n⚠️  WARNING: Port {configured_port} is in use. Using port {new_port} instead.")
                print(f"⚠️  Original redirect URI: {old_uri}")
                print(f"⚠️  Updated redirect URI: {new_uri}")
                print(f"⚠️  You may need to update your Xero app settings to match the new URI.\n")
                
                configured_port = new_port
    
    print(f"\n🔐 Starting Xero Authentication Server")
    print(f"📡 Server URL: http://localhost:{configured_port}")
    print(f"🔄 Callback URI: {settings.xero_redirect_uri}")
    print(f"🔑 Client ID: {settings.xero_client_id[:5]}...{settings.xero_client_id[-5:] if settings.xero_client_id and len(settings.xero_client_id) > 10 else ''}")
    print("\n✅ The server will open in your browser shortly.\n")
    
    # Start the server
    try:
        uvicorn.run(app, host=host, port=configured_port, log_level="info")
    except Exception as e:
        logger.error(f"Failed to start auth server: {str(e)}")
        print(f"\n❌ ERROR: {str(e)}\n")
        
        # Try one more time with a fallback port
        fallback_port = 8000
        if configured_port != fallback_port and not is_port_in_use(fallback_port):
            print(f"🔄 Trying fallback port {fallback_port}...\n")
            
            # Update redirect URI for fallback port
            old_uri = settings.xero_redirect_uri
            new_uri = old_uri.replace(f":{configured_port}", f":{fallback_port}")
            settings.xero_redirect_uri = new_uri
            
            print(f"⚠️  Using fallback redirect URI: {new_uri}")
            print(f"⚠️  You MUST update your Xero app settings with this new URI\n")
            
            try:
                uvicorn.run(app, host=host, port=fallback_port, log_level="info")
            except Exception as e2:
                logger.error(f"Failed to start fallback server: {str(e2)}")
                print(f"\n❌ CRITICAL ERROR: Could not start server on any port. {str(e2)}\n")
                raise
        else:
            raise