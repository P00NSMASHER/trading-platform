from pathlib import Path
import csv
import json
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from market_data_adapter import (
    aggregate_equity_minutes,
    aggregate_option_minutes,
    build,
    load_csv,
)

EX = ROOT / "data/examples"


def test_naive_new_york_timestamp_is_normalized_to_utc():
    rows = load_csv(EX / "equity_trades.csv", kind="equity_trade", input_tz="America/New_York")
    # February is EST (UTC-5).
    assert rows[0].event_ts_utc == "2015-02-17T19:19:02.000Z"


def test_equity_minute_aggregation():
    trades = load_csv(EX / "equity_trades.csv", kind="equity_trade")
    quotes = load_csv(EX / "equity_quotes.csv", kind="equity_quote")
    bars = aggregate_equity_minutes(trades + quotes)
    first = bars[0]
    assert first.symbol == "TEST"
    assert first.trade_count == 2
    assert first.volume == 300
    assert first.open == "100"
    assert first.close == "100.1"
    assert first.vwap == "100.0666666667"
    assert first.quote_count == 2
    assert float(first.mean_quoted_spread) > 0


def test_option_minute_aggregation():
    trades = load_csv(EX / "option_trades.csv", kind="option_trade")
    quotes = load_csv(EX / "option_quotes.csv", kind="option_quote")
    bars = aggregate_option_minutes(trades + quotes)
    first = bars[0]
    assert first.underlying_symbol == "TEST"
    assert first.contract_volume == 14
    assert first.call_volume == 10
    assert first.put_volume == 4
    assert first.unique_contracts_traded == 2
    assert first.dollar_volume == 3380.0


def test_crossed_quote_is_rejected(tmp_path):
    p = tmp_path / "bad.csv"
    p.write_text(
        "timestamp,symbol,bid,ask,bid_size,ask_size\n"
        "2015-02-17 14:19:00,TEST,101,100,10,10\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="crossed quote"):
        load_csv(p, kind="equity_quote")


def test_build_writes_point_in_time_outputs(tmp_path):
    specs = [
        (EX / "equity_trades.csv", "equity_trade"),
        (EX / "equity_quotes.csv", "equity_quote"),
        (EX / "option_trades.csv", "option_trade"),
        (EX / "option_quotes.csv", "option_quote"),
    ]
    manifest = build(specs, tmp_path, source_name="synthetic_fixture")
    assert manifest["outputs"]["normalized_event_count"] == 10
    assert (tmp_path / "normalized_market_events.csv").exists()
    assert (tmp_path / "equity_minutes.csv").exists()
    assert (tmp_path / "option_minutes.csv").exists()
    saved = json.loads((tmp_path / "market_data_manifest.json").read_text())
    assert "BUY" in saved["prohibited_outputs"]
    header = next(csv.reader((tmp_path / "normalized_market_events.csv").open()))
    forbidden = {"expected_return", "target_price", "position_size", "direction"}
    assert forbidden.isdisjoint(header)
