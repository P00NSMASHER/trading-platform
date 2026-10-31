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


@pytest.mark.parametrize(
    ("timestamp", "reason"),
    [
        ("2024-03-10 02:30:00", "nonexistent"),
        ("2024-11-03 01:30:00", "ambiguous"),
    ],
)
@pytest.mark.parametrize("kind", ["equity_trade", "equity_quote"])
def test_naive_dst_gap_or_fold_is_rejected(tmp_path, timestamp, reason, kind):
    # The same fail-closed parser must protect both trade and quote inputs.
    csv_path = tmp_path / "dst.csv"
    if kind == "equity_trade":
        csv_path.write_text(
            "timestamp,symbol,price,size\n"
            f"{timestamp},TEST,100,10\n",
            encoding="utf-8",
        )
    else:
        csv_path.write_text(
            "timestamp,symbol,bid,ask,bid_size,ask_size\n"
            f"{timestamp},TEST,99,101,10,10\n",
            encoding="utf-8",
        )
    with pytest.raises(ValueError, match=rf"row 2: {reason} local timestamp.*explicit UTC offset"):
        load_csv(csv_path, kind=kind, input_tz="America/New_York")


@pytest.mark.parametrize(
    ("timestamp", "expected_utc"),
    [
        ("2024-11-03T01:30:00-04:00", "2024-11-03T05:30:00.000Z"),
        ("2024-11-03T01:30:00-05:00", "2024-11-03T06:30:00.000Z"),
        ("2024-03-10T03:30:00-04:00", "2024-03-10T07:30:00.000Z"),
        ("2024-11-04 12:00:00", "2024-11-04T17:00:00.000Z"),
    ],
)
def test_dst_explicit_offsets_and_unambiguous_wall_times_preserved(
    tmp_path, timestamp, expected_utc
):
    csv_path = tmp_path / "known-clock.csv"
    csv_path.write_text(
        "timestamp,symbol,price,size\n"
        f"{timestamp},TEST,100,10\n",
        encoding="utf-8",
    )
    rows = load_csv(csv_path, kind="equity_trade", input_tz="America/New_York")
    assert rows[0].event_ts_utc == expected_utc


def test_explicit_offset_does_not_require_an_unrelated_input_timezone(tmp_path):
    csv_path = tmp_path / "offset.csv"
    csv_path.write_text(
        "timestamp,symbol,price,size\n"
        "2024-11-03T01:30:00-05:00,TEST,100,10\n",
        encoding="utf-8",
    )
    rows = load_csv(csv_path, kind="equity_trade", input_tz="Not/A_Real_Zone")
    assert rows[0].event_ts_utc == "2024-11-03T06:30:00.000Z"


@pytest.mark.parametrize("kind", ["equity_trade", "equity_quote", "option_trade", "option_quote"])
@pytest.mark.parametrize("invalid_size", ["0.99999999999999999", "1.0000000000000001", "9223372036854775808"])
def test_source_sizes_reject_float_rounding_and_64bit_overflow(tmp_path, kind, invalid_size):
    # All four inputs share the size parser. Former float coercion fabricated
    # an integer size for fractional values just below/above 1.
    field = "size" if kind.endswith("trade") else "bid_size"
    csv_path = tmp_path / "exact-size.csv"
    header = "timestamp,symbol,underlying_symbol,option_symbol,expiration,strike,option_type,price,size,bid,ask,bid_size,ask_size\n"
    row = ["2024-05-02T14:00:00Z", "TEST", "TEST", "TEST240517C00100000", "2024-05-17", "100", "C", "100", "10", "99", "101", "10", "10"]
    row[8 if field == "size" else 11] = invalid_size
    csv_path.write_text(header + ",".join(row) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match=rf"row 2: invalid {field}="):
        load_csv(csv_path, kind=kind)


@pytest.mark.parametrize("kind", ["equity_trade", "equity_quote", "option_trade", "option_quote"])
@pytest.mark.parametrize(("size", "expected"), [
    ("100.0", "100"), ("1e2", "100"),
    ("9007199254740993", "9007199254740993"),
    ("9223372036854775807", "9223372036854775807"),
])
def test_source_sizes_preserve_exact_valid_integrals(tmp_path, kind, size, expected):
    field = "size" if kind.endswith("trade") else "bid_size"
    csv_path = tmp_path / "valid-size.csv"
    header = "timestamp,symbol,underlying_symbol,option_symbol,expiration,strike,option_type,price,size,bid,ask,bid_size,ask_size\n"
    row = ["2024-05-02T14:00:00Z", "TEST", "TEST", "TEST240517C00100000", "2024-05-17", "100", "C", "100", "10", "99", "101", "10", "10"]
    row[8 if field == "size" else 11] = size
    csv_path.write_text(header + ",".join(row) + "\n", encoding="utf-8")
    event = load_csv(csv_path, kind=kind)[0]
    assert getattr(event, field) == expected
