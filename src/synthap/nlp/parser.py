from __future__ import annotations
import json
import re
import difflib
from dataclasses import dataclass
from datetime import date
from typing import Optional

from .periods import resolve_period_au  # AU fiscal / common phrases
from ..catalogs.loader import Catalogs
import os


class QueryScopeError(ValueError):
    """Raised when the user's request refers to unknown catalog entries."""

@dataclass
class ParsedQueryDateRange:
    start: date
    end: date

@dataclass
class ParsedQuery:
    total_count: int
    date_range: ParsedQueryDateRange
    vendor_id: Optional[str] = None
    vendor_name: Optional[str] = None
    # Optional hints (not used by Stage-1 generator but safe to expose)
    min_lines_per_invoice: Optional[int] = None
    max_lines_per_invoice: Optional[int] = None
    pay_count: Optional[int] = None
    pay_all: bool = False

COUNT_PATTERNS = [
    r"\bgenerate\s+(\d+(?:\.\d+)?)\b",
    r"\bneed\s+(\d+(?:\.\d+)?)\b",
    r"\b(\d+(?:\.\d+)?)\s+(?:bills|invoices)\b",
]

VENDOR_PATTERNS = [
    r"\bfor\s+vendor\s+([A-Za-z0-9 _\-\&\.]+)\b",
    r"\bfor\s+([A-Za-z0-9 _\-\&\.]+)\s+bills?\b",
]

LINE_RANGE_PATTERNS = [
    r"\bwith\s+(\d+)\s*-\s*(\d+)\s+line\s+items?\b",
    r"\bwith\s+between\s+(\d+)\s+and\s+(\d+)\s+lines?\b",
    r"\bwith\s+(\d+)\s+to\s+(\d+)\s+line\s+items?\b",
    r"\bwith\s+(\d+)\s+line\s+items?\b",  # exact count fallback
]

PAY_COUNT_PATTERNS = [
    r"pay for only (\d+(?:\.\d+)?)",
    r"pay only (\d+(?:\.\d+)?)",
    r"pay for (\d+(?:\.\d+)?) bills?",
    r"pay (\d+(?:\.\d+)?) bills?",
    r"pay for (\d+(?:\.\d+)?)",
    r"pay (\d+(?:\.\d+)?)",
]

PAY_ALL_PATTERNS = [
    r"pay for all",
    r"pay all",
    r"pay every(thing| bill)",
]


PERIOD_PHRASES = [
    "yesterday",
    "today",
    "last week",
    "last month",
    "last quarter",
]


def _correct_period_phrases(text: str) -> str:
    """Use fuzzy matching to fix near-miss period phrases."""
    words = text.split()
    lower = [w.lower() for w in words]
    for phrase in PERIOD_PHRASES:
        parts = phrase.split()
        n = len(parts)
        for i in range(len(words) - n + 1):
            segment = " ".join(lower[i : i + n])
            if segment == phrase:
                continue
            ratio = difflib.SequenceMatcher(None, segment, phrase).ratio()
            if ratio >= 0.8:
                words[i : i + n] = phrase.split()
                lower[i : i + n] = phrase.split()
    return " ".join(words)


def _ensure_int(value: Optional[object]) -> Optional[int]:
    """Convert a value to int if possible, validating integers."""
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError("Invalid number 'bool'")
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if value.is_integer():
            return int(value)
        raise ValueError(f"Invalid non-integer number '{value}'")
    if isinstance(value, str):
        if value.strip().isdigit():
            return int(value)
        raise ValueError(f"Invalid number '{value}'")
    raise ValueError(f"Invalid number '{value}'")


def _parse_with_llm(text: str, api_key: str) -> dict:
    """Use an LLM to extract structured fields from the query."""
    from openai import OpenAI

    client = OpenAI(api_key=api_key)
    system = (
        "You parse accounts payable generation requests and extract"\
        " fields. Return JSON with keys: total_count, vendor_name,"\
        " min_lines_per_invoice, max_lines_per_invoice, pay_count, pay_all."
    )
    user = {"query": text}
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        temperature=0,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(user)},
        ],
    )
    return json.loads(resp.choices[0].message.content)

def _extract_int(patterns: list[str], text: str) -> Optional[int]:
    for p in patterns:
        m = re.search(p, text, flags=re.IGNORECASE)
        if m:
            s = m.group(1)
            if "." in s:
                raise ValueError(f"Invalid non-integer number '{s}'")
            try:
                return int(s)
            except ValueError:
                raise ValueError(f"Invalid number '{s}'")
    return None

def _extract_vendor(text: str) -> Optional[str]:
    for p in VENDOR_PATTERNS:
        m = re.search(p, text, flags=re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return None

def _extract_line_range(text: str) -> tuple[Optional[int], Optional[int]]:
    for p in LINE_RANGE_PATTERNS:
        m = re.search(p, text, flags=re.IGNORECASE)
        if m:
            if m.lastindex == 2:
                a, b = int(m.group(1)), int(m.group(2))
                if a > b:
                    a, b = b, a
                return a, b
            elif m.lastindex == 1:
                n = int(m.group(1))
                return n, n
    return None, None

def _extract_pay_info(text: str) -> tuple[Optional[int], bool]:
    count = _extract_int(PAY_COUNT_PATTERNS, text)
    all_flag = any(re.search(p, text, flags=re.IGNORECASE) for p in PAY_ALL_PATTERNS)
    return count, all_flag

def parse_nlp_to_query(
    text: str,
    today: date,
    catalogs: Catalogs | None = None,
    use_llm: bool = False,
) -> ParsedQuery:
    t = _correct_period_phrases(text.strip())

    llm_data = None
    api_key = os.getenv("OPENAI_API_KEY")
    if use_llm and api_key:
        try:
            llm_data = _parse_with_llm(t, api_key)
        except Exception:
            llm_data = None

    count = _ensure_int(llm_data.get("total_count")) if llm_data else None
    if count is None:
        count = _extract_int(COUNT_PATTERNS, t) or 10

    if count <= 0:
        raise ValueError("Bill count must be a positive integer")

    # AU-aware period resolver (handles 'Q1 2025', 'last quarter', 'yesterday', etc.)
    dr = resolve_period_au(t, today=today)

    vendor_name = llm_data.get("vendor_name") if llm_data else None
    if not vendor_name:
        vendor_name = _extract_vendor(t)

    vendor_id = None
    if catalogs and vendor_name:
        name_map = {v.name.lower(): v for v in catalogs.vendors}
        key = vendor_name.lower()
        v = name_map.get(key)
        if not v:
            close = difflib.get_close_matches(key, list(name_map.keys()), n=1, cutoff=0.8)
            if close:
                v = name_map[close[0]]
                vendor_name = v.name
            else:
                raise QueryScopeError(f"Query out of scope: unknown vendor '{vendor_name}'")
        item_codes = catalogs.vendor_items.get(v.id, [])
        if not item_codes:
            raise QueryScopeError(
                f"Query out of scope: vendor '{vendor_name}' has no items"
            )
        item_map = {i.code: i for i in catalogs.items}
        account_codes = {a.code for a in catalogs.accounts}
        tax_codes = {t.code for t in catalogs.tax_codes}
        for code in item_codes:
            it = item_map.get(code)
            if not it:
                raise QueryScopeError(
                    f"Query out of scope: unknown item '{code}' for vendor '{vendor_name}'"
                )
            if it.account_code not in account_codes:
                raise QueryScopeError(
                    f"Query out of scope: item '{code}' missing account '{it.account_code}'"
                )
            if it.tax_code not in tax_codes:
                raise QueryScopeError(
                    f"Query out of scope: item '{code}' missing tax code '{it.tax_code}'"
                )
        vendor_id = v.id

    if llm_data:
        min_lines = _ensure_int(llm_data.get("min_lines_per_invoice"))
        max_lines = _ensure_int(llm_data.get("max_lines_per_invoice"))
        pay_count = _ensure_int(llm_data.get("pay_count"))
        pay_all = bool(llm_data.get("pay_all"))
    else:
        min_lines = max_lines = pay_count = None
        pay_all = False

    if min_lines is None or max_lines is None:
        lr_min, lr_max = _extract_line_range(t)
        if min_lines is None:
            min_lines = lr_min
        if max_lines is None:
            max_lines = lr_max

    if pay_count is None:
        pc, pa = _extract_pay_info(t)
        pay_count = pc if pc is not None else pay_count
        pay_all = pa or pay_all

    return ParsedQuery(
        total_count=count,
        date_range=ParsedQueryDateRange(start=dr.start, end=dr.end),
        vendor_id=vendor_id,
        vendor_name=vendor_name,
        min_lines_per_invoice=min_lines,
        max_lines_per_invoice=max_lines,
        pay_count=pay_count,
        pay_all=pay_all,
    )
