"""Configuration viewer page."""

from __future__ import annotations
from pathlib import Path
from typing import Optional
import yaml
import pandas as pd
import streamlit as st

from synthap.config.settings import settings
from synthap.config.runtime_config import (
    RuntimeConfig,
    _defaults_path,
    _runtime_path,
    save_runtime_config,
)

def runs_dir() -> Path:
    """Get the runs directory path."""
    p = Path(settings.runs_dir)
    p.mkdir(parents=True, exist_ok=True)
    return p

def latest_run_id() -> Optional[str]:
    """Get the latest run ID."""
    candidates = [p.name for p in runs_dir().iterdir() if p.is_dir()]
    return sorted(candidates)[-1] if candidates else None

def _load(path) -> dict:
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _flatten(d: dict, prefix: str = "") -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for k, v in d.items():
        key = f"{prefix}{k}" if not prefix else f"{prefix}.{k}"
        if isinstance(v, dict):
            rows.extend(_flatten(v, key))
        else:
            rows.append({"Setting": key, "Value": v})
    return rows


def main() -> None:
    st.title("Configuration")
    defaults = _load(_defaults_path(settings.data_dir))
    runtime_raw = _load(_runtime_path(settings.data_dir))

    st.subheader("Service defaults")
    defaults_df = pd.DataFrame(_flatten(defaults))
    st.dataframe(defaults_df)

    st.subheader("Runtime configuration")
    
    with st.form("runtime_config_form"):
        # AI Configuration Section
        st.subheader("AI Configuration")
        ai_config = runtime_raw.get('ai', {})
        ai_enabled = st.checkbox("Enable AI", value=ai_config.get('enabled', True))
        
        ai_col1, ai_col2 = st.columns(2)
        with ai_col1:
            ai_model = st.text_input(
                "AI Model",
                value=ai_config.get('model', "gpt-4o"),
                help="Default: gpt-4o"
            )
            ai_max_vendors = st.number_input(
                "Max Vendors",
                min_value=1,
                max_value=100,
                value=ai_config.get('max_vendors', 6),
                help="Default: 6"
            )
            ai_max_tokens = st.number_input(
                "Max Output Tokens",
                min_value=100,
                max_value=2000,
                value=ai_config.get('max_output_tokens', 1200),
                help="Default: 1200"
            )
        
        with ai_col2:
            ai_temperature = st.slider(
                "Temperature",
                min_value=0.0,
                max_value=1.0,
                value=ai_config.get('temperature', 0.15),
                step=0.01,
                help="Default: 0.15"
            )
            ai_top_p = st.slider(
                "Top P",
                min_value=0.0,
                max_value=1.0,
                value=ai_config.get('top_p', 1.0),
                step=0.1,
                help="Default: 1.0"
            )
        
        ai_system_prompt = st.text_area(
            "System Prompt",
            value=ai_config.get('system_prompt', '') or '',
            help="Optional: Leave empty for default"
        )
        
        ai_desc_enabled = st.checkbox(
            "Enable Line Item Descriptions",
            value=ai_config.get('line_item_description_enabled', False),
            help="Default: False"
        )
        
        ai_desc_prompt = st.text_area(
            "Line Item Description Prompt",
            value=ai_config.get('line_item_description_prompt', 
                "Write a short description for invoice line item '{item_name}'."),
            help="Template string with {item_name} placeholder"
        )
        
        # Generator Configuration Section
        st.subheader("⚙️ Generator Settings")
        gen_config = runtime_raw.get('generator', {})
        gen_col1, gen_col2 = st.columns(2)
        
        with gen_col1:
            allow_price_var = st.checkbox(
                "Allow Price Variation",
                value=gen_config.get('allow_price_variation', False),
                help="Default: False"
            )
            if allow_price_var:
                price_var_pct = st.slider(
                    "Price Variation %",
                    min_value=0.0,
                    max_value=50.0,
                    value=float(gen_config.get('price_variation_pct', 0.10) * 100),
                    step=1.0,
                    format="%g%%",
                    help="Default: 10%"
                ) / 100.0
            else:
                price_var_pct = 0.10
            
            currency = st.text_input(
                "Currency",
                value=gen_config.get('currency', 'AUD'),
                help="Default: AUD"
            )
        
        with gen_col2:
            status = st.text_input(
                "Status",
                value=gen_config.get('status', 'AUTHORISED'),
                help="Default: AUTHORISED"
            )
            business_days = st.checkbox(
                "Business Days Only",
                value=gen_config.get('business_days_only', True),
                help="Default: True"
            )

        # Artifacts Configuration Section
        st.subheader("📁 Artifacts")
        artifacts_config = runtime_raw.get('artifacts', {})
        include_meta = st.checkbox(
            "Include Meta JSON",
            value=artifacts_config.get('include_meta_json', True),
            help="Default: True"
        )
        
        # Payment Configuration Section
        st.subheader("💰 Payment Settings")
        payment_config = runtime_raw.get('payments', {})
        pay_col1, pay_col2 = st.columns(2)
        
        with pay_col1:
            pay_on_due = st.checkbox(
                "Pay on Due Date",
                value=payment_config.get('pay_on_due_date', False),
                help="Default: False"
            )
            allow_overdue = st.checkbox(
                "Allow Overdue",
                value=payment_config.get('allow_overdue', False),
                help="Default: False"
            )
        
        with pay_col2:
            pay_unspecified = st.checkbox(
                "Pay When Unspecified",
                value=payment_config.get('pay_when_unspecified', False),
                help="Default: False"
            )
            force_no_tax = st.checkbox(
                "Force No Tax",
                value=runtime_raw.get('force_no_tax', False),
                help="Default: False"
            )

        # Save and Revert buttons
        col1, col2 = st.columns(2)
        with col1:
            submit_button = st.form_submit_button("Save Configuration")
            if submit_button:
                new_config = {
                    'ai': {
                        'enabled': ai_enabled,
                        'model': ai_model,
                        'temperature': ai_temperature,
                        'top_p': ai_top_p,
                        'max_output_tokens': ai_max_tokens,
                        'system_prompt': ai_system_prompt or None,
                        'max_vendors': ai_max_vendors,
                        'line_item_description_enabled': ai_desc_enabled,
                        'line_item_description_prompt': ai_desc_prompt,
                    },
                    'generator': {
                        'allow_price_variation': allow_price_var,
                        'price_variation_pct': price_var_pct,
                        'currency': currency,
                        'status': status,
                        'business_days_only': business_days,
                    },
                    'artifacts': {
                        'include_meta_json': include_meta,
                    },
                    'payments': {
                        'pay_on_due_date': pay_on_due,
                        'allow_overdue': allow_overdue,
                        'pay_when_unspecified': pay_unspecified,
                    },
                    'force_no_tax': force_no_tax,
                }
                cfg = RuntimeConfig(**new_config)
                save_runtime_config(cfg)
                st.success("Configuration saved successfully!")
        
        with col2:
            if st.form_submit_button("Revert to Defaults"):
                defaults = _load(_defaults_path(settings.data_dir))
                save_runtime_config(RuntimeConfig(**defaults))
                st.warning("Configuration reset to defaults")
                st.rerun()


if __name__ == "__main__":  # pragma: no cover - streamlit entry point
    main()