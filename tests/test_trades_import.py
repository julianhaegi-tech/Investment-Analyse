import io

import pandas as pd

from saxo_analyse.importers.common import parse_date, parse_number
from saxo_analyse.importers.saxo_trades import parse_trades_file


def test_numbers_and_dates():
    assert parse_number("31,036.42") == 31036.42
    assert parse_number("1'234.50") == 1234.5
    assert parse_number("1.234,56") == 1234.56
    assert parse_number("-3.8 %") == -3.8
    assert parse_number("-") is None
    assert parse_date("04-Nov-2026") == "2026-11-04"
    assert parse_date("12-Okt-2025") == "2025-10-12"
    assert parse_date("15.03.2026") == "2026-03-15"
    assert parse_date("2026-03-15T09:01:02") == "2026-03-15"


def test_saxo_style_excel_with_preamble():
    rows = [
        ["Trades", None, None, None, None, None, None],
        ["Konto 00000/000000", None, None, None, None, None, None],
        ["Handelsdatum", "Instrument", "ISIN", "Kauf/Verkauf", "Menge", "Preis", "Instrumentwährung"],
        ["15-Okt-2025", "Amundi MSCI World SRI", "IE000AAAAAA1", "Kauf", "500", "10.00", "EUR"],
        ["2026-05-02", "Amundi MSCI World SRI", "IE000AAAAAA1", "Verkauf", "-500", "11.50", "EUR"],
        ["2026-05-04", "Amundi ACWI", "IE000BBBBBB2", "Kauf", "300", "20.00", "EUR"],
    ]
    buf = io.BytesIO()
    pd.DataFrame(rows).to_excel(buf, header=False, index=False)
    res = parse_trades_file(buf.getvalue(), "trades.xlsx")
    t = res["trades"]
    assert [x["side"] for x in t] == ["BUY", "SELL", "BUY"]
    assert t[1]["quantity"] == 500 and t[0]["trade_date"] == "2025-10-15"
    assert t[2]["isin"] == "IE000BBBBBB2" and t[2]["currency"] == "EUR"


def test_english_csv_signed_amount():
    csv = ("Trade Date;Instrument;Amount;Price;Instrument currency;Commission\n"
           "2026-01-05;iShares X (IE00B4L5Y983);-10;80.5;USD;5\n")
    res = parse_trades_file(csv.encode(), "x.csv")
    (t,) = res["trades"]
    assert t["side"] == "SELL" and t["isin"] == "IE00B4L5Y983" and t["fees_chf"] == 5
