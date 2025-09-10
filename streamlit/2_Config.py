"""Configuration editor page."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import streamlit as st
import yaml


from synthap.config.runtime_config import (
    RuntimeConfig,
    _defaults_path,
    _runtime_path,
    load_runtime_config,

    save_runtime_config,
)
from synthap.config.settings import settings



def _load_yaml(path: Path) -> dict[str, Any]:

    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def main() -> None:
    st.title("Configuration")

    defaults_cfg = RuntimeConfig(**_load_yaml(_defaults_path(settings.data_dir)))
    cfg = load_runtime_config(settings.data_dir)

    left, right = st.columns(2)
    with left:
        st.subheader("Default configuration")
        st.json(defaults_cfg.model_dump())

    with right:
        st.subheader("Runtime configuration")
        with st.form("cfg_form"):
            st.markdown("### AI")
            ai_enabled = st.checkbox("Enabled", value=cfg.ai.enabled)
            ai_model = st.text_input("Model", value=cfg.ai.model)
            ai_temperature = st.number_input("Temperature", value=cfg.ai.temperature)
            ai_top_p = st.number_input("Top-p", value=cfg.ai.top_p)
            ai_max_tokens = st.number_input(
                "Max output tokens", value=cfg.ai.max_output_tokens, step=1
            )
            ai_system_prompt = st.text_area(
                "System prompt", value=cfg.ai.system_prompt or "", placeholder="Optional"
            )
            ai_max_vendors = st.number_input(
                "Max vendors", min_value=0, value=cfg.ai.max_vendors, step=1
            )
            ai_line_item_desc = st.checkbox(
                "Line item descriptions",
                value=cfg.ai.line_item_description_enabled,
            )
            ai_line_item_prompt = st.text_area(
                "Line item description prompt", value=cfg.ai.line_item_description_prompt
            )

            st.markdown("### Generator")
            gen_allow_var = st.checkbox(
                "Allow price variation",
                value=cfg.generator.allow_price_variation,
            )
            gen_price_var_pct = st.number_input(
                "Price variation %", value=cfg.generator.price_variation_pct
            )
            gen_currency = st.text_input("Currency", value=cfg.generator.currency)
            gen_status = st.text_input("Status", value=cfg.generator.status)
            gen_business_days = st.checkbox(
                "Business days only",
                value=cfg.generator.business_days_only,
            )

            st.markdown("### Artifacts")
            art_meta = st.checkbox(
                "Include meta.json", value=cfg.artifacts.include_meta_json
            )

            st.markdown("### Other")
            no_tax = st.checkbox("Force no tax", value=cfg.force_no_tax)

            st.markdown("### Payments")
            pay_on_due = st.checkbox(
                "Pay on due date", value=cfg.payments.pay_on_due_date
            )
            allow_overdue = st.checkbox(
                "Allow overdue", value=cfg.payments.allow_overdue
            )
            pay_when_unspecified = st.checkbox(
                "Pay when unspecified",
                value=cfg.payments.pay_when_unspecified,
            )

            col_save, col_revert = st.columns(2)
            save_clicked = col_save.form_submit_button("Save")
            revert_clicked = col_revert.form_submit_button("Revert to defaults")

        if save_clicked:
            cfg.ai.enabled = ai_enabled
            cfg.ai.model = ai_model
            cfg.ai.temperature = ai_temperature
            cfg.ai.top_p = ai_top_p
            cfg.ai.max_output_tokens = int(ai_max_tokens)
            cfg.ai.system_prompt = ai_system_prompt or None
            cfg.ai.max_vendors = int(ai_max_vendors)
            cfg.ai.line_item_description_enabled = ai_line_item_desc
            cfg.ai.line_item_description_prompt = ai_line_item_prompt

            cfg.generator.allow_price_variation = gen_allow_var
            cfg.generator.price_variation_pct = gen_price_var_pct
            cfg.generator.currency = gen_currency
            cfg.generator.status = gen_status
            cfg.generator.business_days_only = gen_business_days

            cfg.artifacts.include_meta_json = art_meta

            cfg.force_no_tax = no_tax

            cfg.payments.pay_on_due_date = pay_on_due
            cfg.payments.allow_overdue = allow_overdue
            cfg.payments.pay_when_unspecified = pay_when_unspecified

            save_runtime_config(cfg)
            st.success("Configuration saved")

        if revert_clicked:
            _runtime_path(settings.data_dir).unlink(missing_ok=True)
            st.warning("Runtime configuration reset")
            st.rerun()



if __name__ == "__main__":  # pragma: no cover - streamlit entry point
    main()

