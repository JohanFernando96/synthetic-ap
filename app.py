"""Dashboard entry point for the Streamlit UI."""

from __future__ import annotations
from datetime import datetime
from pathlib import Path
import pandas as pd
import streamlit as st
import subprocess
import requests
import json
import time
import socket
import threading
import os
import glob

from synthap.catalogs.loader import load_catalogs
from synthap import runs_dir 
from synthap.config.settings import settings
from synthap.config.runtime_config import load_runtime_config
from synthap.xero.oauth import build_authorize_url, TokenStore

# ------------------- Streamlit Utilities -------------------

def safe_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """
    Safely convert DataFrame for Streamlit display to avoid Arrow conversion errors.
    Fixes issues with mixed types that cause "Could not convert float: tried to convert to boolean" errors.
    """
    if df is None or df.empty:
        return pd.DataFrame()
    
    # Create a copy to avoid modifying the original
    result = df.copy()
    
    # Handle boolean-like columns that might contain numeric values
    for col in result.columns:
        # Check if column contains potentially boolean-like values with mixed types
        if result[col].dtype == 'object':
            # Convert values that look like booleans to proper strings to avoid conversion errors
            try:
                has_bool_values = result[col].isin([True, False, 0, 1, 0.1, 1.0]).any()
                if has_bool_values:
                    # Convert to string to avoid Arrow conversion issues
                    result[col] = result[col].astype(str)
            except:
                # If comparison fails, convert the column to string to be safe
                result[col] = result[col].astype(str)
                
    # Ensure all object columns that might have None are converted to string
    for col in result.select_dtypes(include=['object']).columns:
        result[col] = result[col].fillna('').astype(str)
            
    return result

# ------------------- Backend Authentication Functions -------------------

class XeroAuthBackend:
    """Backend functionality for Xero authentication."""
    
    @staticmethod
    def get_token_path() -> Path:
        """Get the token file path from settings or use default."""
        if settings.token_file:
            return Path(settings.token_file)
        return Path(".xero_token.json")
    
    @staticmethod
    def start_auth_server():
        """Start the authentication server process internally and verify it's running."""
        try:
            # Get the port from redirect URI
            port = 5050
            try:
                uri = settings.xero_redirect_uri
                if '://' in uri:
                    uri = uri.split('://', 1)[1]
                if ':' in uri and '/' in uri.split(':', 1)[1]:
                    port = int(uri.split(':', 1)[1].split('/', 1)[0])
            except Exception:
                pass
                
            # Try to kill any existing process on this port
            if os.name == 'nt':  # Windows
                try:
                    os.system(f'for /f "tokens=5" %a in (\'netstat -aon ^| findstr :{port}\') do taskkill /F /PID %a')
                    print(f"Attempted to kill any process using port {port}")
                    time.sleep(1)  # Give time for the port to be released
                except Exception as e:
                    print(f"Could not kill process on port {port}: {e}")
            
            # Run the auth server in a separate thread to avoid blocking the UI
            def run_auth_server_thread():
                try:
                    # Import here to avoid circular imports
                    from synthap.xero.auth_server import run_server
                    run_server()
                except Exception as e:
                    print(f"Error in auth server thread: {e}")
            
            # Start the thread
            import threading
            auth_thread = threading.Thread(target=run_auth_server_thread, daemon=True)
            auth_thread.start()
            
            print(f"Authentication server thread started, waiting for port {port} to be available...")
            
            # Check if server starts up (with timeout)
            max_attempts = 15  # Increased timeout
            for attempt in range(max_attempts):
                try:
                    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                        s.settimeout(1)
                        result = s.connect_ex(('localhost', port))
                        if result == 0:
                            print(f"Authentication server is running on port {port}")
                            # Wait a bit more for the server to fully initialize
                            time.sleep(1)
                            return True
                except Exception:
                    pass
                    
                # Wait before next attempt
                time.sleep(1)
                print(f"Waiting for authentication server to start (attempt {attempt+1}/{max_attempts})...")
                
            print(f"Authentication server did not start within the timeout period")
            return False
        except Exception as e:
            print(f"Failed to start authentication server: {e}")
            return False

    @staticmethod
    def get_auth_url(max_retries=10, retry_delay=1):
        """Get the authorization URL from the server with retries."""
        # Extract port from redirect URI
        port = 5050  # Default port
        try:
            uri = settings.xero_redirect_uri
            if '://' in uri:
                uri = uri.split('://', 1)[1]
            if ':' in uri and '/' in uri.split(':', 1)[1]:
                port = int(uri.split(':', 1)[1].split('/', 1)[0])
        except Exception:
            pass
        
        base_url = f"http://localhost:{port}"
        print(f"Connecting to auth server at {base_url}")
        
        # First check server health
        for attempt in range(max_retries):
            try:
                health_response = requests.get(f"{base_url}/health", timeout=5)
                if health_response.status_code == 200:
                    print("Auth server is healthy, fetching authorization URL")
                    break
                time.sleep(retry_delay)
            except Exception as e:
                print(f"Health check attempt {attempt+1}/{max_retries}: {str(e)}")
                time.sleep(retry_delay)
        
        # Now get the actual authorization URL
        for attempt in range(max_retries):
            try:
                response = requests.get(base_url, timeout=5)
                if response.status_code == 200:
                    url = response.json().get("authorize_url")
                    if url:
                        return url
                # If we didn't get a valid URL, wait and retry
                time.sleep(retry_delay)
            except Exception as e:
                # On exception, wait and retry
                print(f"Auth URL attempt {attempt+1}/{max_retries}: {str(e)}")
                time.sleep(retry_delay)
        
        return None
    
    @staticmethod
    def check_token_exists() -> bool:
        """Check if token file exists."""
        return XeroAuthBackend.get_token_path().exists()
    
    @staticmethod
    def get_token_data():
        """Get token data if it exists."""
        token_path = XeroAuthBackend.get_token_path()
        if token_path.exists():
            try:
                with open(token_path, 'r') as f:
                    return json.load(f)
            except Exception:
                pass
        return None
    
    @staticmethod
    def get_tenant_id():
        """Get tenant ID from token if available."""
        token_data = XeroAuthBackend.get_token_data()
        if token_data:
            return token_data.get("tenant_id")
        return None
    
    @staticmethod
    def is_authenticated():
        """Check if user is authenticated with Xero."""
        tenant_id = XeroAuthBackend.get_tenant_id()
        return tenant_id is not None
    
    @staticmethod
    def search_token_files():
        """Search for token files in the workspace."""
        # Try common locations for the token file
        possible_paths = [
            ".xero_token.json",
            "xero_token.json",
            ".env/xero_token.json",
            ".env/.xero_token.json",
            os.path.expanduser("~/.xero_token.json")
        ]
        
        # Also search for any file with "xero" and "token" in the name
        possible_paths.extend(glob.glob("**/*xero*token*.json", recursive=True))
        
        for path in possible_paths:
            try:
                if Path(path).exists():
                    with open(path, 'r') as f:
                        data = json.load(f)
                        if data.get("tenant_id"):
                            return path, data
            except Exception:
                continue
        
        return None, None
        
    @staticmethod
    def clear_token():
        """Clear the token to force a new authentication."""
        try:
            TokenStore.clear()
            return True
        except Exception as e:
            print(f"Failed to clear token: {e}")
            return False


# ------------------- Dashboard Data Functions -------------------

def load_latest_run_stats() -> dict:
    """Load statistics from the most recent run."""
    runs = sorted([p for p in runs_dir().iterdir() if p.is_dir()], reverse=True)
    if not runs:
        return {}
    
    latest_run = runs[0]
    try:
        invoices = pd.read_parquet(latest_run / "invoices.parquet")
        lines = pd.read_parquet(latest_run / "invoice_lines.parquet")
        
        # Ensure dataframes are safe for Streamlit
        invoices = safe_dataframe(invoices)
        lines = safe_dataframe(lines)
        
        return {
            "run_id": latest_run.name,
            "invoice_count": len(invoices),
            "total_amount": lines["line_amount"].sum(),
            "avg_invoice_lines": len(lines) / len(invoices),
            "timestamp": datetime.strptime(latest_run.name.split("-")[0:3], "%Y-%m-%d").strftime("%Y-%m-%d"),
        }
    except Exception:
        return {}

# ------------------- UI Components -------------------

def render_connection_status() -> None:
    """Render connection status with detailed information."""
    st.subheader("System Status")
    
    # Check various system components
    backend_ok = True  # catalogs loaded successfully
    openai_ok = bool(settings.openai_api_key)
    xero_ok = XeroAuthBackend.is_authenticated()
    
    # Create status columns with more detail
    status_cols = st.columns(3)
    
    # Backend Status
    with status_cols[0]:
        if backend_ok:
            st.success("Backend: Connected")
        else:
            st.error("Backend: Unavailable")
            st.caption("⚠️ Unable to load catalogs")
    
    # OpenAI Status
    with status_cols[1]:
        if openai_ok:
            st.success("OpenAI: Connected")
            st.caption(f"Model: {load_runtime_config(settings.data_dir).ai.model}")
        else:
            st.error("OpenAI: Disconnected")
            st.caption("⚠️ Missing API key in settings")
    
    # Xero Status
    with status_cols[2]:
        if xero_ok:
            tenant_id = XeroAuthBackend.get_tenant_id()
            st.success("Xero: Connected")
            st.caption(f"Tenant ID: {tenant_id}")
            
            # Create two columns for the buttons
            btn_col1, btn_col2 = st.columns(2)
            
            # Add a button to reconnect to the same Xero account
            with btn_col1:
                if st.button("Reconnect Xero", key="reconnect_same"):
                    st.session_state["xero_auth_flow"] = "starting"
                    st.rerun()
            
            # Add a button to switch to a different Xero account
            with btn_col2:
                if st.button("Switch Account", key="switch_account"):
                    # Clear the token first to force new authentication
                    if XeroAuthBackend.clear_token():
                        st.session_state["xero_auth_flow"] = "starting"
                        st.session_state["switching_account"] = True
                        st.rerun()
                    else:
                        st.error("Failed to clear current authentication. Please try again.")
        else:
            st.error("Xero: Disconnected")
            st.caption("⚠️ No authentication token found")
            
            # Add button to connect to Xero
            if st.button("Connect to Xero"):
                st.session_state["xero_auth_flow"] = "starting"
                st.rerun()


def handle_xero_auth_flow():
    """Handle the Xero authentication flow state machine."""
    # State machine for authentication flow
    auth_flow_state = st.session_state.get("xero_auth_flow")
    
    if not auth_flow_state:
        return
    
    # Container for all auth-related UI
    auth_container = st.container()
    
    if auth_flow_state == "starting":
        with auth_container:
            if st.session_state.get("switching_account"):
                st.info("Starting Xero authentication process for a new account...")
            else:
                st.info("Starting Xero authentication process...")
            
            # Start auth server in a separate thread to avoid blocking UI
            with st.spinner("Starting authentication server..."):
                if XeroAuthBackend.start_auth_server():
                    # Give the server more time to start
                    time.sleep(3)  # Increased from 2 to 3 seconds
                    st.session_state["xero_auth_flow"] = "server_started"
                    st.rerun()
                else:
                    st.error("Failed to start authentication server. Please try again.")
                    st.session_state.pop("xero_auth_flow", None)
                    if "switching_account" in st.session_state:
                        st.session_state.pop("switching_account")
                    return
        
    elif auth_flow_state == "server_started":
        with auth_container:
            # First, check if auth happened already
            tenant_id = XeroAuthBackend.get_tenant_id()
            if tenant_id:
                st.success(f"✅ Authentication successful! Connected to Xero tenant: {tenant_id}")
                st.session_state["xero_auth_flow"] = "completed"
                st.rerun()
            
            # Show a progress message while attempting to connect
            with st.spinner("Connecting to authentication server..."):
                # Get auth URL with more retries and longer wait time
                auth_url = XeroAuthBackend.get_auth_url(max_retries=10, retry_delay=2)
            
            if not auth_url:
                st.error("Failed to connect to the authentication server. This could be due to:")
                st.markdown("""
                - The server failed to start properly
                - A port conflict (another service might be using port 5050)
                - Network or firewall restrictions
                """)
                if st.button("Retry Authentication"):
                    # Restart the auth process
                    st.session_state["xero_auth_flow"] = "starting"
                    st.rerun()
                if st.button("Cancel", key="cancel_auth"):
                    st.session_state.pop("xero_auth_flow", None)
                    if "switching_account" in st.session_state:
                        st.session_state.pop("switching_account")
                    st.rerun()
                return
            
            # Display auth instructions
            st.info("Please complete these steps to connect to Xero:")
            st.markdown("### 1. Click the button below to open Xero authentication")
            st.link_button("Sign in to Xero", auth_url, use_container_width=True)
            st.caption("This will open in a new tab.")
            
            st.markdown("### 2. After signing in to Xero")
            st.write("- Select the organization you want to connect")
            st.write("- Authorize the requested permissions")
            st.write("- You'll see a 'Token saved. You can close this tab.' message when complete")
            
            st.markdown("### 3. Then click the button below")
            
            # Add a check button and a continue button
            col1, col2 = st.columns(2)
            with col1:
                if st.button("Check Authentication Status", use_container_width=True):
                    # Re-check token file
                    if XeroAuthBackend.is_authenticated():
                        st.session_state["xero_auth_flow"] = "completed"
                        st.rerun()
                    else:
                        # Search for token files if the default one isn't found
                        token_path, token_data = XeroAuthBackend.search_token_files()
                        if token_path and token_data and token_data.get("tenant_id"):
                            st.success(f"Found token file at {token_path} with tenant ID: {token_data.get('tenant_id')}")
                            st.session_state["xero_auth_flow"] = "completed"
                            st.session_state["found_token_path"] = token_path
                            st.rerun()
                        else:
                            st.error("Authentication not completed or token not found. Make sure you completed the Xero authentication flow.")
                            
            with col2:
                if st.button("Cancel Authentication", use_container_width=True):
                    st.session_state.pop("xero_auth_flow", None)
                    if "switching_account" in st.session_state:
                        st.session_state.pop("switching_account")
                    st.rerun()
            
    elif auth_flow_state == "completed":
        with auth_container:
            # If we found a token file in an alternate location, show that info
            if "found_token_path" in st.session_state:
                st.info(f"Token file found at: {st.session_state['found_token_path']}")
                st.caption("You may need to update your XERO_TOKEN_FILE setting to point to this location.")
            
            tenant_id = XeroAuthBackend.get_tenant_id()
            
            if st.session_state.get("switching_account"):
                st.success(f"✅ Successfully switched to Xero tenant: {tenant_id}")
            else:
                st.success(f"✅ Successfully connected to Xero tenant: {tenant_id}")
            
            if st.button("Continue to Dashboard", use_container_width=True):
                # Clear the auth flow state and return to main dashboard
                st.session_state.pop("xero_auth_flow", None)
                if "found_token_path" in st.session_state:
                    st.session_state.pop("found_token_path")
                if "switching_account" in st.session_state:
                    st.session_state.pop("switching_account")
                st.rerun()


def render_catalog_metrics(cat) -> None:
    """Render catalog-related metrics."""
    st.subheader("Catalog Statistics")
    cat_cols = st.columns(4)
    
    cat_cols[0].metric("Vendors", len(cat.vendors))
    cat_cols[1].metric("Items", len(cat.items))
    cat_cols[2].metric("Chart of Accounts", len(cat.accounts))
    cat_cols[3].metric("Tax Codes", len(cat.tax_codes))


def render_generation_metrics(run_stats: dict) -> None:
    """Render generation-related metrics."""
    st.subheader("Generation Statistics")
    if run_stats:
        gen_cols = st.columns(4)
        gen_cols[0].metric("Last Run Date", run_stats.get("timestamp", "—"))
        gen_cols[1].metric("Invoices Generated", run_stats.get("invoice_count", 0))
        gen_cols[2].metric(
            "Total Amount", 
            f"${run_stats.get('total_amount', 0):,.2f}"
        )
        gen_cols[3].metric(
            "Avg Lines per Invoice", 
            f"{run_stats.get('avg_invoice_lines', 0):.1f}"
        )
    else:
        st.info("No generation runs found")

        


def main() -> None:
    """Render the overview dashboard."""
    st.set_page_config(
        page_title="RedOwl Synthetic AP Generator",
        layout="wide",
        initial_sidebar_state="expanded"
    )

    st.title("RedOwl Synthetic AP Generator")
    
    try:
        # Handle Xero authentication flow if active
        handle_xero_auth_flow()
        
        # Only show regular dashboard if not in auth flow
        if not st.session_state.get("xero_auth_flow"):
            # Load data
            cat = load_catalogs(settings.data_dir)
            run_stats = load_latest_run_stats()
            
            # Render dashboard sections
            render_connection_status()
            st.divider()
            
            render_catalog_metrics(cat)
            st.divider()
            
            render_generation_metrics(run_stats)
            
            # Configuration Overview
            st.divider()
            with st.expander("Current Configuration"):
                config = load_runtime_config(settings.data_dir)
                st.json({
                    "AI Settings": {
                        "Model": config.ai.model,
                        "Temperature": config.ai.temperature,
                        "Max Vendors": config.ai.max_vendors,
                        "AI Descriptions": config.ai.line_item_description_enabled
                    },
                    "Generator Settings": {
                        "Currency": config.generator.currency,
                        "Status": config.generator.status,
                        "Business Days Only": config.generator.business_days_only,
                        "Price Variation": config.generator.allow_price_variation
                    },
                    "Payment Settings": {
                        "Pay on Due Date": config.payments.pay_on_due_date,
                        "Allow Overdue": config.payments.allow_overdue
                    }
                })
            
    except Exception as e:
        st.error("Error loading dashboard data")
        st.exception(e)


if __name__ == "__main__":  # pragma: no cover - streamlit entry point
    main()