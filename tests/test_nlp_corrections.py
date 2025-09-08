from datetime import date
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from synthap.catalogs.loader import load_catalogs
from synthap.nlp.parser import parse_nlp_to_query

DATA_DIR = Path(__file__).resolve().parents[1] / "data"


def _catalogs():
    return load_catalogs(str(DATA_DIR))


def test_near_miss_vendor_corrected():
    cat = _catalogs()
    pq = parse_nlp_to_query(
        "Generate 5 bills for vendor Sparky Electrical", today=date(2024, 1, 1), catalogs=cat
    )
    assert pq.vendor_name == "Sparky Electricals"


def test_near_miss_period_phrase_corrected():
    cat = _catalogs()
    pq = parse_nlp_to_query(
        "Generate 1 bill yesterdya", today=date(2024, 5, 10), catalogs=cat
    )
    assert pq.date_range.start == date(2024, 5, 9)
    assert pq.date_range.end == date(2024, 5, 9)
