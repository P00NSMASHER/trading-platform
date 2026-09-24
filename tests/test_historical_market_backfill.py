from pathlib import Path
import csv
import json
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from historical_market_backfill import (
    NON_SYNTHETIC_CLASS,
    aggregate_order_flow_minutes,
    build,
    build_microstructure_minutes,
    load_contract,
    load_itch_executions,
    load_market_events,
    validate_contract,
)

EX = ROOT / "data/examples"


def write_contract(tmp_path, sources):
    p = tmp_path / "contract.json"
    p.write_text(json.dumps({"schema_version": "1", "sources": sources}, indent=2), encoding="utf-8")
    return p


def source(path, *, source_id, family, kind, classification="synthetic_fixture", license_reference="", column_map=None, format_version="fixture"):
    return {
        "source_id": source_id,
        "source_family": family,
        "record_kind": kind,
        "path": str(path),
        "authorized": True,
        "data_classification": classification,
        "license_reference": license_reference,
        "trade_date": "2015-02-17",
        "timezone": "America/New_York",
        "delimiter": ",",
        "encoding": "utf-8",
        "format_version": format_version,
        "column_map": column_map or {},
    }


def test_contract_rejects_unauthorized_source(tmp_path):
    s = source(EX / "equity_trades.csv", source_id="x", family="nyse_daily_taq", kind="equity_trade")
    s["authorized"] = False
    p = write_contract(tmp_path, [s])
    with pytest.raises(PermissionError, match="authorized must be true"):
        load_contract(p)


def test_real_source_requires_license_reference(tmp_path):
    s = source(EX / "equity_trades.csv", source_id="x", family="nyse_daily_taq", kind="equity_trade", classification=NON_SYNTHETIC_CLASS)
    p = write_contract(tmp_path, [s])
    with pytest.raises(ValueError, match="license_reference"):
        load_contract(p)


def test_explicit_column_mapping_normalizes_vendor_shape(tmp_path):
    vendor = tmp_path / "taq.csv"
    vendor.write_text("TradeTime,Ticker,Px,Sz,Venue,Cond\n2015-02-17 14:19:02,TEST,100.25,50,N,Q\n", encoding="utf-8")
    s = source(vendor, source_id="taq", family="nyse_daily_taq", kind="equity_trade", column_map={
        "timestamp": "TradeTime", "symbol": "Ticker", "price": "Px", "size": "Sz", "exchange": "Venue", "conditions": "Cond"
    })
    p = write_contract(tmp_path, [s])
    specs, _ = load_contract(p)
    rows = load_market_events(specs[0])
    assert rows[0].symbol == "TEST"
    assert rows[0].price == "100.25"
    assert rows[0].event_ts_utc == "2015-02-17T19:19:02.000Z"


def test_decoded_itch_requires_format_version(tmp_path):
    s = source(EX / "itch_decoded.csv", source_id="itch", family="nasdaq_itch_5_0_decoded", kind="itch_decoded", format_version="")
    p = write_contract(tmp_path, [s])
    with pytest.raises(ValueError, match="format_version"):
        load_contract(p)


def test_itch_execution_signing_uses_resting_side(tmp_path):
    s = source(EX / "itch_decoded.csv", source_id="itch", family="nasdaq_itch_5_0_decoded", kind="itch_decoded", format_version="ITCH-5.0", column_map={
        "timestamp": "timestamp", "message_type": "message_type", "symbol": "stock", "order_reference": "order_reference",
        "side": "side", "shares": "shares", "price": "price", "executed_shares": "executed_shares", "execution_price": "execution_price",
        "match_number": "match_number", "printable": "printable", "cancelled_shares": "cancelled_shares", "new_order_reference": "new_order_reference"
    })
    p = write_contract(tmp_path, [s])
    specs, _ = load_contract(p)
    exes = load_itch_executions(specs[0])
    assert len(exes) == 2
    assert exes[0].resting_side == "S" and exes[0].aggressor_side == "B"
    assert exes[1].resting_side == "B" and exes[1].aggressor_side == "S"
    minute = aggregate_order_flow_minutes(exes)[0]
    assert minute.buy_aggressor_shares == 200
    assert minute.sell_aggressor_shares == 100
    assert minute.absolute_order_imbalance == "0.3333333333"


def test_microstructure_effective_spread_is_point_in_time():
    # Existing fixture has trades and quotes in the same minute.
    trade_spec = type("S", (), {})
    # Use Step-2 canonical loader through source contracts is tested elsewhere; here use adapter fixture directly.
    import market_data_adapter as mda
    events = mda.load_csv(EX / "equity_trades.csv", kind="equity_trade") + mda.load_csv(EX / "equity_quotes.csv", kind="equity_quote")
    rows = build_microstructure_minutes(events, quote_max_age_seconds=120)
    assert rows
    assert rows[0].mean_effective_spread_pct != ""
    assert rows[0].realized_spread_uses_future_market_data == 1


def test_synthetic_contract_cannot_unlock_real_comparison(tmp_path):
    events = tmp_path / "events.csv"
    events.write_text(
        "event_id,historical_symbol,first_documented_illicit_trade_ts,research_use_only\n"
        "E1,TEST,2015-02-17 14:19:00,1\n", encoding="utf-8"
    )
    sources = [
        source(EX / "equity_trades.csv", source_id="eqt", family="synthetic_fixture", kind="equity_trade"),
        source(EX / "equity_quotes.csv", source_id="eqq", family="synthetic_fixture", kind="equity_quote"),
        source(EX / "option_trades.csv", source_id="opt", family="synthetic_fixture", kind="option_trade"),
        source(EX / "option_quotes.csv", source_id="opq", family="synthetic_fixture", kind="option_quote"),
    ]
    contract = write_contract(tmp_path, sources)
    manifest = build(contract, events, tmp_path / "out", pre_minutes=0, post_minutes=0)
    readiness = manifest["non_synthetic_comparison_readiness"]
    assert readiness["eligible_for_real_feature_backfill"] is False
    assert "no_non_synthetic_authorized_market_source_present" in readiness["reasons"]


def test_event_panel_aligns_on_first_documented_trade(tmp_path):
    events = tmp_path / "events.csv"
    events.write_text(
        "event_id,historical_symbol,first_documented_illicit_trade_ts,research_use_only\n"
        "E1,TEST,2015-02-17 14:19:00,1\n", encoding="utf-8"
    )
    sources = [
        source(EX / "equity_trades.csv", source_id="eqt", family="synthetic_fixture", kind="equity_trade"),
        source(EX / "equity_quotes.csv", source_id="eqq", family="synthetic_fixture", kind="equity_quote"),
        source(EX / "option_trades.csv", source_id="opt", family="synthetic_fixture", kind="option_trade"),
        source(EX / "option_quotes.csv", source_id="opq", family="synthetic_fixture", kind="option_quote"),
    ]
    contract = write_contract(tmp_path, sources)
    out = tmp_path / "out"
    manifest = build(contract, events, out, pre_minutes=1, post_minutes=1)
    rows = list(csv.DictReader((out / "event_minute_panel.csv").open()))
    assert len(rows) == 3
    center = [r for r in rows if r["relative_minute"] == "0"][0]
    assert center["minute_ts_utc"] == "2015-02-17T19:19:00.000Z"
    assert center["share_volume"] != ""
    assert center["option_contract_volume"] != ""
    assert manifest["alignment"]["anchor"] == "first_documented_illicit_trade_ts"


def test_point_in_time_shares_outstanding_never_uses_future_record(tmp_path):
    events = tmp_path / "events.csv"
    events.write_text("event_id,historical_symbol,first_documented_illicit_trade_ts,research_use_only\nE1,TEST,2015-02-17 14:19:00,1\n", encoding="utf-8")
    shares = tmp_path / "shares.csv"
    shares.write_text(
        "symbol,effective_at,shares_outstanding\n"
        "TEST,2015-02-01T00:00:00Z,1000\n"
        "TEST,2015-03-01T00:00:00Z,1\n", encoding="utf-8")
    contract = write_contract(tmp_path, [source(EX / "equity_trades.csv", source_id="eq", family="synthetic_fixture", kind="equity_trade")])
    out = tmp_path / "out"
    build(contract, events, out, pre_minutes=0, post_minutes=0, shares_file=shares)
    row = next(csv.DictReader((out / "event_minute_panel.csv").open()))
    assert float(row["share_turnover"]) == 0.3  # 300 / 1000, not 300 / future 1


def test_manifest_hashes_authorized_inputs(tmp_path):
    events = tmp_path / "events.csv"
    events.write_text("event_id,historical_symbol,first_documented_illicit_trade_ts,research_use_only\nE1,TEST,2015-02-17 14:19:00,1\n", encoding="utf-8")
    contract = write_contract(tmp_path, [source(EX / "equity_trades.csv", source_id="eq", family="synthetic_fixture", kind="equity_trade")])
    out = tmp_path / "out"
    manifest = build(contract, events, out, pre_minutes=0, post_minutes=0)
    assert len(manifest["source_contracts"][0]["sha256"]) == 64
    assert manifest["source_contract_policy"]["credentials_stored_in_contract"] is False
    assert "BUY" in manifest["prohibited_outputs"]


def test_validate_contract_reports_classification_counts(tmp_path):
    p = write_contract(tmp_path, [source(EX / "equity_trades.csv", source_id="eq", family="synthetic_fixture", kind="equity_trade")])
    report = validate_contract(p)
    assert report["valid"] is True
    assert report["synthetic_source_count"] == 1
    assert report["non_synthetic_authorized_source_count"] == 0
