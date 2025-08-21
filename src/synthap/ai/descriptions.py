from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from ..config.runtime_config import AIConfig


def generate_line_description(item_name: str, cfg: AIConfig) -> str:
    """Generate a realistic invoice line description for a given item name.

    Falls back to the raw item name if the OpenAI request fails for any reason.
    """
    from openai import OpenAI

    from ..config.settings import settings

    prompt = cfg.line_item_description_prompt.format(item_name=item_name)
    system = cfg.system_prompt or (
        "You craft concise, realistic descriptions for invoice line items."
    )
    client = OpenAI(api_key=settings.openai_api_key)
    try:
        resp = client.chat.completions.create(
            model=cfg.model,
            temperature=float(cfg.temperature),
            top_p=float(cfg.top_p),
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        )
        return resp.choices[0].message.content.strip()
    except Exception:
        return item_name
