from datetime import date
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

"""LLM parsing tests."""

from synthap.catalogs.loader import load_catalogs
from synthap.nlp import parser as parser_mod
from synthap.nlp.parser import parse_nlp_to_query

DATA_DIR = Path(__file__).resolve().parents[1] / "data"


def test_llm_parsing(monkeypatch):
    def fake_llm(text: str, api_key: str) -> dict:
        return {"total_count": 12, "vendor_name": "BuildRight Cement"}

    monkeypatch.setattr(parser_mod, "_parse_with_llm", fake_llm)
    monkeypatch.setenv("OPENAI_API_KEY", "test")

    cat = load_catalogs(str(DATA_DIR))
    pq = parse_nlp_to_query(
        "About a dozen bills for vendor BuildRight Cement in March 2024",
        today=date(2024, 3, 1),
        catalogs=cat,
        use_llm=True,
    )
    assert pq.total_count == 12
    assert pq.vendor_name == "BuildRight Cement"
