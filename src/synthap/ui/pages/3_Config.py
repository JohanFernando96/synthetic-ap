"""Configuration viewer page."""

from __future__ import annotations

import yaml
import streamlit as st

from synthap.config.runtime_config import (
    AIConfig,
    ArtifactsCfg,
    GeneratorCfg,
    PaymentCfg,
    RuntimeConfig,
    _defaults_path,
    load_runtime_config,
    save_runtime_config,
)
from synthap.config.settings import settings


def _load(path) -> dict:
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def main() -> None:
    st.title("Configuration")
    defaults = _load(_defaults_path(settings.data_dir))
    cfg = load_runtime_config(settings.data_dir)

    st.subheader("Service defaults")
    st.json(defaults)

    st.subheader("Runtime configuration")
    with st.form("runtime_cfg"):
        st.markdown("### AI")
        ai_enabled = st.checkbox("Enabled", value=cfg.ai.enabled)
        ai_model = st.text_input("Model", cfg.ai.model)
        ai_temperature = st.number_input("Temperature", value=cfg.ai.temperature, step=0.01)
        ai_top_p = st.number_input("Top p", value=cfg.ai.top_p, step=0.01)
        ai_max_tokens = st.number_input("Max output tokens", value=cfg.ai.max_output_tokens)
        ai_system_prompt = st.text_area("System prompt", value=cfg.ai.system_prompt or "")
        ai_max_vendors = st.number_input("Max vendors", value=cfg.ai.max_vendors, step=1)
        ai_line_desc = st.checkbox(
            "Line item description enabled", value=cfg.ai.line_item_description_enabled
        )
        ai_line_prompt = st.text_input(
            "Line item description prompt", cfg.ai.line_item_description_prompt
        )

        st.markdown("### Generator")
        gen_allow_price_var = st.checkbox(
            "Allow price variation", value=cfg.generator.allow_price_variation
        )
        gen_price_var_pct = st.number_input(
            "Price variation pct", value=cfg.generator.price_variation_pct, step=0.01
        )
        gen_currency = st.text_input("Currency", cfg.generator.currency)
        gen_status = st.text_input("Status", cfg.generator.status)
        gen_business_days = st.checkbox(
            "Business days only", value=cfg.generator.business_days_only
        )

        st.markdown("### Artifacts")
        art_include_meta = st.checkbox(
            "Include meta JSON", value=cfg.artifacts.include_meta_json
        )

        force_no_tax = st.checkbox("Force no tax", value=cfg.force_no_tax)

        st.markdown("### Payments")
        pay_on_due = st.checkbox("Pay on due date", value=cfg.payments.pay_on_due_date)
        allow_overdue = st.checkbox("Allow overdue", value=cfg.payments.allow_overdue)
        pay_when_unspecified = st.checkbox(
            "Pay when unspecified", value=cfg.payments.pay_when_unspecified
        )
        overdue_count = st.number_input(
            "Overdue count", value=cfg.payments.overdue_count, step=1
        )

        submitted = st.form_submit_button("Save")
        if submitted:
            new_cfg = RuntimeConfig(
                ai=AIConfig(
                    enabled=ai_enabled,
                    model=ai_model,
                    temperature=ai_temperature,
                    top_p=ai_top_p,
                    max_output_tokens=int(ai_max_tokens),
                    system_prompt=ai_system_prompt or None,
                    max_vendors=int(ai_max_vendors),
                    line_item_description_enabled=ai_line_desc,
                    line_item_description_prompt=ai_line_prompt,
                ),
                generator=GeneratorCfg(
                    allow_price_variation=gen_allow_price_var,
                    price_variation_pct=gen_price_var_pct,
                    currency=gen_currency,
                    status=gen_status,
                    business_days_only=gen_business_days,
                ),
                artifacts=ArtifactsCfg(include_meta_json=art_include_meta),
                force_no_tax=force_no_tax,
                payments=PaymentCfg(
                    pay_on_due_date=pay_on_due,
                    allow_overdue=allow_overdue,
                    pay_when_unspecified=pay_when_unspecified,
                    overdue_count=int(overdue_count),
                ),
            )
            save_runtime_config(new_cfg)
            st.rerun()


if __name__ == "__main__":  # pragma: no cover - streamlit entry point
    main()

