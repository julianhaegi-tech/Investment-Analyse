from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parents[1] / "app" / "app.py")


@pytest.fixture(autouse=True)
def _fresh_cache():
    st.cache_resource.clear()
    yield
    st.cache_resource.clear()


def test_app_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("PORTFOLIO_DATA", str(tmp_path))
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception
    assert "Willkommen" in at.title[0].value


def test_app_with_report(tmp_path, monkeypatch, report):
    from portfolio.store import Store

    Store(tmp_path / "portfolio.db").save_report(report, "bericht.pdf")
    monkeypatch.setenv("PORTFOLIO_DATA", str(tmp_path))
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception
    assert at.title[0].value == "Mein Saxo-Depot"
    assert len(at.tabs) == 6
