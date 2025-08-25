from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

class Settings(BaseSettings):
    # LLM
    openai_api_key: str = Field(alias="OPENAI_API_KEY", default="")

    # Xero
    xero_client_id: str = Field(alias="XERO_CLIENT_ID")
    xero_client_secret: str = Field(alias="XERO_CLIENT_SECRET")
    xero_redirect_uri: str = Field(alias="XERO_REDIRECT_URI")
    xero_scopes: str = Field(alias="XERO_SCOPES")
    xero_tenant_id: Optional[str] = Field(alias="XERO_TENANT_ID", default=None)
    xero_payment_account_code: str = Field(alias="XERO_PAYMENT_ACCOUNT_CODE", default="101")
    pay_on_due_date: bool = Field(alias="PAY_ON_DUE_DATE", default=False)

    # Service
    timezone: str = Field(default="Australia/Melbourne", alias="TIMEZONE")
    default_seed: int = Field(default=42, alias="DEFAULT_SEED")
    fiscal_year_start_month: int = Field(default=7, alias="FISCAL_YEAR_START_MONTH")
    data_dir: str = Field(default="./data", alias="DATA_DIR")
    runs_dir: str = Field(default="./runs", alias="RUNS_DIR")
    token_file: str = Field(default="./.xero_token.json", alias="XERO_TOKEN_FILE")

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

settings = Settings()
