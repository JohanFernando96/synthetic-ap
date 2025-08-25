from datetime import date
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest

from synthap.catalogs.loader import load_catalogs
from synthap.nlp.parser import parse_nlp_to_query, QueryScopeError


DATA_DIR = Path(__file__).resolve().parents[1] / "data"


def _catalogs():
    return load_catalogs(str(DATA_DIR))


def test_unknown_vendor_triggers_out_of_scope():
    cat = _catalogs()
    with pytest.raises(QueryScopeError):
        parse_nlp_to_query(
            "Generate 10 bills for Q1 2024 for Vendor ABC",
            today=date(2024, 1, 1),
            catalogs=cat,
        )


def test_vendor_without_items_out_of_scope():
    cat = _catalogs()
    with pytest.raises(QueryScopeError):
        parse_nlp_to_query(
            "Generate 5 bills for 2024 for vendor No Contact",
            today=date(2024, 1, 1),
            catalogs=cat,
        )


def test_decimal_bill_count_invalid():
    cat = _catalogs()
    with pytest.raises(ValueError):
        parse_nlp_to_query(
            "Generate 10.1 bills for Q1 2024",
            today=date(2024, 1, 1),
            catalogs=cat,
        )

