import csv
import json
from pathlib import Path

import g2_lseg_result_adapter as adapter
from market_data_adapter import load_csv


def _equity_validation():
    return {
        "results": [
            {
                "historical_symbol": "CNMD",
                "selected_ric": "CNMD.O",
                "validation_status": "validated_single_candidate",
            },
            {
                "historical_symbol": "OTHER",
                "selected_ric": "",
                "validation_status": "no_candidate_observed",
            },
        ]
    }


def _option_contracts():
    return {
        "summary": {
            "historical_contract_set_ready_for_time_and_sales": True,
        },
        "contracts": [
            {
                "source_ric": "CNMDD271102500.U",
                "historical_symbol": "CNMD",
                "underlying_symbol": "CNMD",
                "option_symbol": "CNMDD271102500",
                "expiration": "2011-04-27",
                "strike": 25.0,
                "option_type": "call",
                "historical_date_evidence": True,
                "validation_status": "historical_chain_candidate",
            },
            {
                "source_ric": "CNMDD271103000.U",
                "historical_symbol": "CNMD",
                "underlying_symbol": "CNMD",
                "option_symbol": "CNMDD271103000",
                "expiration": "2011-04-27",
                "strike": 30.0,
                "option_type": "call",
                "historical_date_evidence": False,
                "validation_status": "search_candidate_requires_historical_confirmation",
            },
        ],
    }


def test_equity_adapter_uses_only_validated_ric_and_requested_date():
    rows = [
        {
            "#RIC": "CNMD.O",
            "Date-Time": "2011-04-27T15:22:00-04:00",
            "Type": "Trade",
            "Price": "25.10",
            "Volume": "200",
            "Ex/Cntrb.ID": "Q",
        },
        {
            "#RIC": "CNMD.O",
            "Date-Time": "2011-04-27T15:21:59-04:00",
            "Type": "Quote",
            "Bid Price": "25.05",
            "Bid Size": "3",
            "Ask Price": "25.15",
            "Ask Size": "4",
            "Ex/Cntrb.ID": "Q",
        },
        {
            "#RIC": "OTHER.O",
            "Date-Time": "2011-04-27T15:22:00-04:00",
            "Type": "Trade",
            "Price": "10",
            "Volume": "1",
        },
        {
            "#RIC": "CNMD.O",
            "Date-Time": "2011-04-28T15:22:00-04:00",
            "Type": "Trade",
            "Price": "26",
            "Volume": "1",
        },
    ]
    out = adapter.adapt_equity_rows(
        rows,
        trade_date="2011-04-27",
        validation_payload=_equity_validation(),
    )

    assert len(out["equity_trades"]) == 1
    assert len(out["equity_quotes"]) == 1
    assert out["equity_trades"][0]["symbol"] == "CNMD"
    assert out["summary"]["all_selected_symbols_have_trade_and_quote_rows"] is True
    assert out["summary"]["ignored_rows"] == {
        "unknown_or_unvalidated_ric": 1,
        "wrong_or_unparseable_date": 1,
    }


def test_equity_adapter_drops_original_research_invalid_quotes():
    rows = [
        {
            "#RIC": "CNMD.O",
            "Date-Time": "2011-04-27T15:21:59-04:00",
            "Type": "Quote",
            "Bid Price": "25.05",
            "Bid Size": "0",
            "Ask Price": "25.15",
            "Ask Size": "4",
        },
        {
            "#RIC": "CNMD.O",
            "Date-Time": "2011-04-27T15:22:00-04:00",
            "Type": "Quote",
            "Bid Price": "25.05",
            "Bid Size": "3",
            "Ask Price": "25.15",
            "Ask Size": "4",
            "Qualifiers": "NQ[PRC_QL_CD]",
        },
    ]
    out = adapter.adapt_equity_rows(
        rows,
        trade_date="2011-04-27",
        validation_payload=_equity_validation(),
    )

    assert out["equity_quotes"] == []
    assert out["summary"]["ignored_rows"] == {
        "quote:no_quote_qualifier": 1,
        "quote:original_research_zero_bid": 1,
    }
    assert out["summary"]["symbols_missing_quote_rows"] == ["CNMD"]


def test_option_adapter_requires_historical_chain_contracts():
    rows = [
        {
            "#RIC": "CNMDD271102500.U",
            "Date-Time": "2011-04-27T15:22:00-04:00",
            "Type": "Trade",
            "Price": "1.25",
            "Volume": "10",
        },
        {
            "#RIC": "CNMDD271102500.U",
            "Date-Time": "2011-04-27T15:21:59-04:00",
            "Type": "Quote",
            "Bid Price": "1.20",
            "Bid Size": "5",
            "Ask Price": "1.30",
            "Ask Size": "7",
        },
        {
            "#RIC": "CNMDD271103000.U",
            "Date-Time": "2011-04-27T15:22:00-04:00",
            "Type": "Trade",
            "Price": "0.50",
            "Volume": "1",
        },
    ]
    out = adapter.adapt_option_rows(
        rows,
        trade_date="2011-04-27",
        contract_payload=_option_contracts(),
    )

    assert len(out["option_trades"]) == 1
    assert len(out["option_quotes"]) == 1
    assert out["option_trades"][0]["underlying_symbol"] == "CNMD"
    assert out["option_trades"][0]["option_symbol"] == "CNMDD271102500"
    assert out["summary"]["ignored_rows"]["unknown_or_nonhistorical_contract_ric"] == 1
    assert out["summary"]["historical_contract_count"] == 1


def test_option_adapter_rejects_search_only_manifest():
    payload = _option_contracts()
    payload["summary"]["historical_contract_set_ready_for_time_and_sales"] = False

    try:
        adapter.option_contract_map(payload)
    except ValueError as exc:
        assert "historical-chain evidence" in str(exc)
    else:
        raise AssertionError("search-only option manifest must fail closed")


def test_written_equity_lanes_are_accepted_by_market_data_adapter(tmp_path: Path):
    rows = [
        {
            "#RIC": "CNMD.O",
            "Date-Time": "2011-04-27T15:22:00-04:00",
            "Type": "Trade",
            "Price": "25.10",
            "Volume": "200",
            "Ex/Cntrb.ID": "Q",
            "Qualifiers": "",
        },
        {
            "#RIC": "CNMD.O",
            "Date-Time": "2011-04-27T15:21:59-04:00",
            "Type": "Quote",
            "Bid Price": "25.05",
            "Bid Size": "3",
            "Ask Price": "25.15",
            "Ask Size": "4",
            "Ex/Cntrb.ID": "Q",
            "Qualifiers": "R[PRC_QL_CD]",
        },
    ]
    payload = adapter.adapt_equity_rows(
        rows,
        trade_date="2011-04-27",
        validation_payload=_equity_validation(),
    )
    adapter.write_adaptation(payload, output_dir=tmp_path)

    trades = load_csv(tmp_path / "equity_trades.csv", kind="equity_trade")
    quotes = load_csv(tmp_path / "equity_quotes.csv", kind="equity_quote")

    assert len(trades) == 1
    assert len(quotes) == 1
    assert trades[0].symbol == "CNMD"
    assert quotes[0].symbol == "CNMD"


def test_written_option_lanes_are_accepted_by_market_data_adapter(tmp_path: Path):
    rows = [
        {
            "#RIC": "CNMDD271102500.U",
            "Date-Time": "2011-04-27T15:22:00-04:00",
            "Type": "Trade",
            "Price": "1.25",
            "Volume": "10",
        },
        {
            "#RIC": "CNMDD271102500.U",
            "Date-Time": "2011-04-27T15:21:59-04:00",
            "Type": "Quote",
            "Bid Price": "1.20",
            "Bid Size": "5",
            "Ask Price": "1.30",
            "Ask Size": "7",
        },
    ]
    payload = adapter.adapt_option_rows(
        rows,
        trade_date="2011-04-27",
        contract_payload=_option_contracts(),
    )
    adapter.write_adaptation(payload, output_dir=tmp_path)

    trades = load_csv(tmp_path / "option_trades.csv", kind="option_trade")
    quotes = load_csv(tmp_path / "option_quotes.csv", kind="option_quote")

    assert len(trades) == 1
    assert len(quotes) == 1
    assert trades[0].underlying_symbol == "CNMD"
    assert trades[0].option_symbol == "CNMDD271102500"
    assert quotes[0].underlying_symbol == "CNMD"


def test_write_receipt_hashes_the_private_input(tmp_path: Path):
    source = tmp_path / "raw.csv"
    source.write_text("#RIC,Date-Time,Type\n", encoding="utf-8")
    payload = {
        "lane": "equity",
        "trade_date": "2011-04-27",
        "equity_trades": [],
        "equity_quotes": [],
        "summary": {"g2_coverage_change": False},
    }
    receipt = adapter.write_adaptation(
        payload,
        output_dir=tmp_path / "out",
        input_path=source,
    )
    saved = json.loads(
        (tmp_path / "out" / "lseg_adaptation_receipt.json").read_text()
    )
    assert saved["input_receipt"]["sha256"] == receipt["input_receipt"]["sha256"]
    assert saved["summary"]["g2_coverage_change"] is False
