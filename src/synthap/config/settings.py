import os
from typing import Optional
from dotenv import load_dotenv

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
load_dotenv()


load_dotenv()


class Settings(BaseSettings):
    # LLM
    openai_api_key: str = os.getenv("OPENAI_API_KEY")

    # Xero
    xero_client_id: str = os.getenv("XERO_CLIENT_ID")
    xero_client_secret: str = os.getenv("XERO_CLIENT_SECRET")
    xero_redirect_uri: str = os.getenv("XERO_REDIRECT_URI")
    xero_scopes: str = os.getenv("XERO_SCOPES")
    xero_tenant_id: Optional[str] = os.getenv("XERO_TENANT_ID", default="a325094c-dbc8-490a-9e5c-bdbd4f15eef5")
    xero_payment_account_code: str = os.getenv("XERO_PAYMENT_ACCOUNT_CODE", default="101")
    pay_on_due_date: bool = os.getenv("PAY_ON_DUE_DATE", default=False)

    # Service
    timezone: str = os.getenv("TIMEZONE")
    default_seed: int = os.getenv("DEFAULT_SEED")
    fiscal_year_start_month: int = os.getenv("FISCAL_YEAR_START_MONTH")
    data_dir: str = os.getenv("DATA_DIR")
    runs_dir: str = os.getenv("RUNS_DIR")
    token_file: str = os.getenv("XERO_TOKEN_FILE")

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


settings = Settings()
