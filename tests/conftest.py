import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from portfolio.report import parse_tables  # noqa: E402
from portfolio.store import Store  # noqa: E402


@pytest.fixture(scope="session")
def report():
    fx = json.loads((ROOT / "tests" / "fixtures" / "transaction_report_tables.json").read_text(encoding="utf-8"))
    return parse_tables(fx["tables"], fx["meta"])


@pytest.fixture
def store(tmp_path, report):
    s = Store(tmp_path / "t.db")
    s.save_report(report, "bericht.pdf")
    return s
