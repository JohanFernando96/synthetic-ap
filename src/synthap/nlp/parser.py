from __future__ import annotations
import json
import re
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
    r"pay for (\d+)",
    r"pay (\d+)",
    r"pay for (\d+) bills?",
    r"pay (\d+) bills?",
]

PAY_ALL_PATTERNS = [
    r"pay for all",
    r"pay all",
    r"pay every(thing| bill)",
]

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

    t = text.strip()

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

    vendor_name = _extract_vendor(t)
    min_lines, max_lines = _extract_line_range(t)
    pay_count, pay_all = _extract_pay_info(t)

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
