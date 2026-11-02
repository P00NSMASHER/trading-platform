import csv
from pathlib import Path

import g2_dxfeed_option_adapter as adapter
from market_data_adapter import load_csv


def test_parse_dxfeed_option_symbol():
    parsed = adapter.parse_option_symbol(".AAPL190927C210")
    assert parsed == {
        "underlying_symbol": "AAPL",
        "option_symbol": ".AAPL190927C210",
        "expiration": "2019-09-27",
        "strike": "210",
        "option_type": "C",
    }


def test_public_bid_ask_sample_shape_adapts_to_canonical_quote():
    row = {
        "EventSymbol": ".AAPL190927C210",
        "EventTime": "20190905-083500.617-0500",
        "BidTime": "20190905-083458-0500",
        "BidExchangeCode": "X",
        "BidPrice": "6.85",
        "BidSize": "37",
        "AskTime": "20190905-083500-0500",
        "AskExchangeCode": "Z",
        "AskPrice": "7.05",
        "AskSize": "2",
    }
    out = adapter.adapt_quote_row(
        row,
        trade_date="2019-09-05",
        allowed_underlyings={"AAPL"},
    )
    assert out["underlying_symbol"] == "AAPL"
    assert out["option_symbol"] == ".AAPL190927C210"
    assert out["expiration"] == "2019-09-27"
    assert out["option_type"] == "C"
    assert out["bid"] == "6.85"
    assert out["ask"] == "7.05"
    assert out["bid_size"] == "37"
    assert out["ask_size"] == "2"
    assert out["exchange"] == "X/Z"
    assert out["timestamp"].startswith("2019-09-05T08:35:00.617")


def test_public_last_sale_sample_shape_adapts_to_canonical_trade():
    row = {
        "EventSymbol": ".AAPL190927C210",
        "EventTime": "20190905-083726.208-0500",
        "Time": "20190905-083726-0500",
        "Sequence": "208:0",
        "ExchangeCode": "C",
        "Price": "7.01",
        "Size": "1",
        "Tick": "1",
        "Change": "1.65",
        "DayVolume": "9",
        "DayTurnover": "NaN",
        "Flags": "0",
    }
    out = adapter.adapt_trade_row(
        row,
        trade_date="2019-09-05",
        allowed_underlyings={"AAPL"},
    )
    assert out["price"] == "7.01"
    assert out["size"] == "1"
    assert out["exchange"] == "C"
    assert out["conditions"] == "0"


def test_public_tns_sample_uses_sale_conditions_for_trade_conditions():
    row = {
        "EventSymbol": ".AAPL190927C210",
        "EventTime": "20190905-083726.208-0500",
        "Time": "20190905-083726-0500",
        "Sequence": "208:18",
        "ExchangeCode": "C",
        "Price": "7.01",
        "Size": "1",
        "BidPrice": "6.9",
        "AskPrice": "7.1",
        "SaleConditions": "L",
        "Flags": "52",
    }
    out = adapter.adapt_trade_row(
        row,
        trade_date="2019-09-05",
        allowed_underlyings={"AAPL"},
    )
    assert out["conditions"] == "L"


def test_scope_is_fail_closed_for_wrong_date_and_underlying():
    row = {
        "EventSymbol": ".AAPL190927C210",
        "EventTime": "20190905-083726.208-0500",
        "ExchangeCode": "C",
        "Price": "7.01",
        "Size": "1",
    }
    wrong_date = adapter.adapt_rows(
        [row],
        event_kind="Trade",
        trade_date="2019-09-06",
        allowed_underlyings={"AAPL"},
    )
    assert wrong_date["option_trades"] == []
    assert wrong_date["summary"]["rejected_rows"] == 1

    wrong_underlying = adapter.adapt_rows(
        [row],
        event_kind="Trade",
        trade_date="2019-09-05",
        allowed_underlyings={"JNPR"},
    )
    assert wrong_underlying["option_trades"] == []
    assert wrong_underlying["summary"]["rejected_rows"] == 1
    assert wrong_underlying["summary"]["g2_coverage_change"] is False


def test_crossed_quote_is_rejected():
    row = {
        "EventSymbol": ".AAPL190927C210",
        "EventTime": "20190905-083500.617-0500",
        "BidExchangeCode": "X",
        "BidPrice": "7.10",
        "BidSize": "37",
        "AskExchangeCode": "Z",
        "AskPrice": "7.05",
        "AskSize": "2",
    }
    out = adapter.adapt_rows(
        [row],
        event_kind="Quote",
        trade_date="2019-09-05",
        allowed_underlyings={"AAPL"},
    )
    assert out["option_quotes"] == []
    assert out["summary"]["rejected_rows"] == 1
    assert out["summary"]["rejection_reasons"]["crossed dxFeed quote"] == 1


def test_native_time_and_sale_reader_skips_correction_action_rows(tmp_path: Path):
    source = tmp_path / "tns.csv"
    source.write_text(
        "#=TimeAndSale,EventSymbol,EventTime,Time,Sequence,ExchangeCode,Price,Size,BidPrice,AskPrice,SaleConditions,Flags\n"
        "TimeAndSale,.AAPL190927C210,20190905-083726.208-0500,20190905-083726-0500,208:18,C,7.01,1,6.9,7.1,L,52\n"
        "TimeAndSale&C,.AAPL190927C210,20190905-083726.208-0500,20190905-083726-0500,208:18,C,7.01,1,6.9,7.1,L,52\n",
        encoding="utf-8",
    )
    rows = adapter._parse_dxfeed_csv(source)
    assert len(rows) == 1
    assert rows[0]["TimeAndSale"] == "TimeAndSale"


def test_written_dxfeed_lanes_are_accepted_by_market_data_adapter(tmp_path: Path):
    trade_payload = adapter.adapt_rows(
        [
            {
                "EventSymbol": ".AAPL190927C210",
                "EventTime": "20190905-083726.208-0500",
                "ExchangeCode": "C",
                "Price": "7.01",
                "Size": "1",
                "Flags": "0",
            }
        ],
        event_kind="Trade",
        trade_date="2019-09-05",
        allowed_underlyings={"AAPL"},
    )
    quote_payload = adapter.adapt_rows(
        [
            {
                "EventSymbol": ".AAPL190927C210",
                "EventTime": "20190905-083500.617-0500",
                "BidExchangeCode": "X",
                "BidPrice": "6.85",
                "BidSize": "37",
                "AskExchangeCode": "Z",
                "AskPrice": "7.05",
                "AskSize": "2",
            }
        ],
        event_kind="Quote",
        trade_date="2019-09-05",
        allowed_underlyings={"AAPL"},
    )

    raw_trade = tmp_path / "raw_trade.csv"
    raw_trade.write_text("placeholder\n", encoding="utf-8")
    raw_quote = tmp_path / "raw_quote.csv"
    raw_quote.write_text("placeholder\n", encoding="utf-8")

    trade_out = tmp_path / "trade_out"
    quote_out = tmp_path / "quote_out"
    adapter.write_adaptation(
        trade_payload,
        output_dir=trade_out,
        input_path=raw_trade,
    )
    adapter.write_adaptation(
        quote_payload,
        output_dir=quote_out,
        input_path=raw_quote,
    )

    trades = load_csv(trade_out / "option_trades.csv", kind="option_trade")
    quotes = load_csv(quote_out / "option_quotes.csv", kind="option_quote")
    assert len(trades) == 1
    assert len(quotes) == 1
    assert trades[0].underlying_symbol == "AAPL"
    assert quotes[0].underlying_symbol == "AAPL"


def test_receipt_hashes_input_and_never_promotes_coverage(tmp_path: Path):
    source = tmp_path / "bid-ask.csv"
    source.write_text("#=Quote,EventSymbol,EventTime\n", encoding="utf-8")
    payload = {
        "trade_date": "2019-09-05",
        "allowed_underlyings": ["AAPL"],
        "option_trades": [],
        "option_quotes": [],
        "summary": {
            "event_kind": "Quote",
            "input_rows": 0,
            "trade_rows": 0,
            "quote_rows": 0,
            "rejected_rows": 0,
            "rejection_reasons": {},
            "g2_coverage_change": False,
        },
    }
    receipt = adapter.write_adaptation(
        payload,
        output_dir=tmp_path / "out",
        input_path=source,
    )
    assert receipt["input_receipt"]["sha256"]
    assert receipt["authorization_promoted"] is False
    assert receipt["validation_promoted"] is False
    assert receipt["g2_coverage_change"] == 0
