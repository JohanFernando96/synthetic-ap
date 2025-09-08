"""Catalog data generator using LLM + Xero contacts."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, List
from uuid import uuid4

import yaml
from slugify import slugify
from openai import OpenAI

from ..config.settings import settings
from ..xero.client import upsert_contacts

DEFAULT_PAYMENT_TERMS = {"type": "DAYSAFTERBILLDATE", "days": 30}
DEFAULT_ACCOUNT_CODE = "453"


def _call_llm(industry: str, contacts: int, items_per_vendor: int) -> List[dict[str, Any]]:
    """Call an LLM to generate vendor and item data."""
    client = OpenAI(api_key=settings.openai_api_key)
    prompt = (
        "You generate synthetic vendor catalog data for accounting tests in Australia. "
        f"Industry: {industry}. Provide {contacts} vendors and {items_per_vendor} items per vendor. "
        "For each item supply name, unit_price in AUD and whether GST applies with tax_code 'INPUT' or 'EXEMPTEXPENSES'. "
        "Respond with JSON: {\"vendors\":[{\"name\":...,\"items\":[{\"name\":...,\"unit_price\":123.4,\"tax_code\":\"INPUT\"}]}]}"
    )
    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            temperature=0.2,
            messages=[
                {
                    "role": "system",
                    "content": "You output only JSON and no extra text.",
                },
                {"role": "user", "content": prompt},
            ],
        )
        data = json.loads(resp.choices[0].message.content)
        return data.get("vendors", [])
    except Exception:
        return []


async def generate_catalogs(
    industry: str,
    contact_count: int,
    items_per_vendor: int,
    data_dir: str | Path | None = None,
) -> None:
    """Generate vendor/item catalogs and append them to YAML data files."""

    base = Path(data_dir or settings.data_dir) / "catalogs"
    vendors_yaml = base / "vendors.yaml"
    items_yaml = base / "items.yaml"
    vendor_items_yaml = base / "vendor_items.yaml"

    existing_vendors = yaml.safe_load(vendors_yaml.read_text("utf-8")) or {}
    vendor_records: list = existing_vendors.get("vendors", [])

    existing_items = yaml.safe_load(items_yaml.read_text("utf-8")) or {}
    item_records: list = existing_items.get("items", [])

    existing_vi = yaml.safe_load(vendor_items_yaml.read_text("utf-8")) or {}
    vi_records: list = existing_vi.get("vendor_items", [])

    vendors = _call_llm(industry, contact_count, items_per_vendor)

    new_vi_entries = []

    for vend in vendors:
        name = vend.get("name", "Vendor")
        slug = slugify(name).upper()
        vendor_id = f"VEND-{slug[:12]}"

        contact_payload = {"Name": name, "IsSupplier": True}
        resp = await upsert_contacts([contact_payload])
        contact_id = resp.get("Contacts", [{}])[0].get("ContactID", str(uuid4()))

        vendor_records.append(
            {
                "id": vendor_id,
                "name": name,
                "xero_contact_id": contact_id,
                "is_supplier": True,
                "payment_terms": DEFAULT_PAYMENT_TERMS,
            }
        )

        codes: list[str] = []
        for idx, item in enumerate(vend.get("items", []), start=1):
            code = f"{slug[:4]}-{idx:03d}".upper()
            item_records.append(
                {
                    "id": str(uuid4()),
                    "code": code,
                    "name": item.get("name", "Item"),
                    "unit_price": float(item.get("unit_price", 0.0)),
                    "account_code": DEFAULT_ACCOUNT_CODE,
                    "tax_code": item.get("tax_code", "INPUT"),
                    "price_variance_pct": 0.10,
                }
            )
            codes.append(code)

        new_vi_entries.append({"vendor_id": vendor_id, "item_codes": codes})

    vi_records.extend(new_vi_entries)

    vendors_yaml.write_text(
        yaml.safe_dump({"vendors": vendor_records}, sort_keys=False),
        encoding="utf-8",
    )
    items_yaml.write_text(
        yaml.safe_dump({"items": item_records}, sort_keys=False),
        encoding="utf-8",
    )
    vendor_items_yaml.write_text(
        yaml.safe_dump({"vendor_items": vi_records}, sort_keys=False),
        encoding="utf-8",
    )


if __name__ == "__main__":  # pragma: no cover
    asyncio.run(generate_catalogs("construction", 1, 1))

