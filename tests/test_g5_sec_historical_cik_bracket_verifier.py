from __future__ import annotations

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import g5_sec_historical_cik_bracket_verifier as verifier


def _queue(tmp_path: Path, dates: str = "2015-02-17") -> Path:
    path = tmp_path / "queue.csv"
    path.write_text(
        "historical_symbol,required_event_dates\n"
        f"AAA,{dates}\n",
        encoding="utf-8",
    )
    return path


def _tickers():
    return {"0": {"ticker": "AAA", "cik_str": 12345}}


def _root():
    return {
        "filings": {
            "recent": {
                "accessionNumber": ["BEFORE", "AFTER"],
                "filingDate": ["2015-02-10", "2015-02-25"],
                "form": ["10-Q", "10-K"],
            },
            "files": [],
        }
    }


def _filing(accepted: str, symbol: str) -> str:
    return (
        "<ACCEPTANCE-DATETIME>" + accepted + "\n"
        '<dei:TradingSymbol contextRef="D"> ' + symbol + " </dei:TradingSymbol>\n"
    )


def test_current_ticker_lead_requires_archival_symbol_bracket(tmp_path: Path):
    def fetch_json(url: str):
        if url == verifier.SEC_TICKERS_URL:
            return _tickers()
        assert url.endswith("CIK0000012345.json")
        return _root()

    def fetch_text(url: str):
        if "BEFORE" in url:
            return _filing("20150210120000", "AAA")
        return _filing("20150225120000", "AAA")

    out = tmp_path / "reviewed.csv"
    summary = verifier.verify(
        acquisition_queue_path=_queue(tmp_path),
        output_path=out,
        fetch_json=fetch_json,
        fetch_text=fetch_text,
    )
    assert summary["verified_symbol_count"] == 1
    assert summary["gap_symbol_count"] == 0
    assert summary["canonical_g5_dates_resolved_change"] == 0

    rows = list(csv.DictReader(out.open(encoding="utf-8")))
    assert rows[0]["historical_symbol"] == "AAA"
    assert rows[0]["cik"] == "0000012345"
    assert rows[0]["review_status"] == "EXPLICIT_HISTORICAL_CIK_VERIFIED"
    assert rows[0]["valid_from"] == "2015-02-10"
    assert rows[0]["valid_through"] == "2015-02-25"


def test_post_event_match_without_pre_event_match_does_not_verify(tmp_path: Path):
    def fetch_json(url: str):
        if url == verifier.SEC_TICKERS_URL:
            return _tickers()
        return _root()

    def fetch_text(url: str):
        if "BEFORE" in url:
            return _filing("20150210120000", "WRONG")
        return _filing("20150225120000", "AAA")

    summary = verifier.verify(
        acquisition_queue_path=_queue(tmp_path),
        output_path=tmp_path / "reviewed.csv",
        fetch_json=fetch_json,
        fetch_text=fetch_text,
    )
    assert summary["verified_symbol_count"] == 0
    assert summary["gap_reasons"] == {
        "NO_MATCHING_TRADING_SYMBOL_BRACKET": 1
    }


def test_both_sides_must_use_same_current_cik_lead(tmp_path: Path):
    payload = {
        "0": {"ticker": "AAA", "cik_str": 12345},
        "1": {"ticker": "AAA", "cik_str": 67890},
    }
    try:
        verifier.verify(
            acquisition_queue_path=_queue(tmp_path),
            output_path=tmp_path / "reviewed.csv",
            fetch_json=lambda url: payload if url == verifier.SEC_TICKERS_URL else {},
            fetch_text=lambda _url: "",
        )
    except verifier.G5HistoricalCikBracketError as exc:
        assert "ambiguous for AAA" in str(exc)
    else:
        raise AssertionError("expected ambiguous lead failure")


def test_every_required_event_date_must_be_bracketed(tmp_path: Path):
    def fetch_json(url: str):
        if url == verifier.SEC_TICKERS_URL:
            return _tickers()
        return _root()

    def fetch_text(url: str):
        if "BEFORE" in url:
            return _filing("20150210120000", "AAA")
        return _filing("20150225120000", "AAA")

    summary = verifier.verify(
        acquisition_queue_path=_queue(
            tmp_path, "2015-02-17;2017-02-17"
        ),
        output_path=tmp_path / "reviewed.csv",
        fetch_json=fetch_json,
        fetch_text=fetch_text,
        max_bracket_days=400,
    )
    assert summary["verified_symbol_count"] == 0


def test_nonmatching_current_ticker_has_no_closing_value(tmp_path: Path):
    summary = verifier.verify(
        acquisition_queue_path=_queue(tmp_path),
        output_path=tmp_path / "reviewed.csv",
        fetch_json=lambda url: (
            {"0": {"ticker": "BBB", "cik_str": 12345}}
            if url == verifier.SEC_TICKERS_URL
            else {}
        ),
        fetch_text=lambda _url: "",
    )
    assert summary["verified_symbol_count"] == 0
    assert summary["gap_reasons"] == {"NO_CURRENT_SEC_CIK_LEAD": 1}


def test_trading_symbol_parser_accepts_xbrl_and_rejects_other_symbol():
    text = (
        '<dei:TradingSymbol contextRef="D">AAA</dei:TradingSymbol>\n'
        "Trading Symbol: BBB\n"
    )
    assert verifier._trading_symbols(text) == {"AAA", "BBB"}
