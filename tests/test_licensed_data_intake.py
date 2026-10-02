from __future__ import annotations

import csv
import gzip
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import licensed_data_intake as intake


def test_equity_trade_header_becomes_pending_not_authorized(tmp_path: Path):
    drop = tmp_path / "drop"
    out = tmp_path / "out"
    drop.mkdir()
    p = drop / "taq_trades_20150217.csv"
    p.write_text(
        "timestamp,symbol,price,size,exchange,conditions\n"
        "2015-02-17 09:30:00,TEST,100,10,N,@\n",
        encoding="utf-8",
    )

    manifest = intake.scan(drop, out, license_reference="LICENSE-REF")
    assert manifest["file_count"] == 1
    assert manifest["high_confidence_contract_candidates"] == 1

    rows = list(csv.DictReader((out / "intake_files.csv").open()))
    assert rows[0]["candidate_record_kind"] == "equity_trade"
    assert rows[0]["candidate_source_family"] == "nyse_daily_taq"
    assert rows[0]["detected_trade_date"] == "2015-02-17"
    assert rows[0]["status"] == "PENDING_AUTHORIZATION_AND_REVIEW"

    contract = json.loads((out / "market_contract.pending.json").read_text())
    assert contract["sources"][0]["authorized"] is False
    assert contract["sources"][0]["license_reference"] == "LICENSE-REF"


def test_option_quote_gzip_header_is_detected(tmp_path: Path):
    drop = tmp_path / "drop"
    out = tmp_path / "out"
    drop.mkdir()
    p = drop / "cboe_option_quotes_20150302.csv.gz"
    with gzip.open(p, "wt", encoding="utf-8") as f:
        f.write(
            "timestamp,underlying_symbol,option_symbol,expiration,strike,option_type,"
            "bid,ask,bid_size,ask_size,exchange\n"
            "2015-03-02 09:30:00,TEST,TEST150320C00100000,2015-03-20,100,C,1,1.1,10,12,C\n"
        )

    intake.scan(drop, out)
    row = next(csv.DictReader((out / "intake_files.csv").open()))
    assert row["candidate_record_kind"] == "option_quote"
    assert row["candidate_source_family"] == "cboe_option_quotes"
    assert row["status"] == "PENDING_AUTHORIZATION_AND_REVIEW"


def test_raw_itch_is_inventory_only(tmp_path: Path):
    drop = tmp_path / "drop"
    out = tmp_path / "out"
    drop.mkdir()
    p = drop / "nasdaq_itch41_20130425.bin"
    p.write_bytes(b"\x00\x01\x02\x03\x00binary")

    manifest = intake.scan(drop, out)
    row = next(csv.DictReader((out / "intake_files.csv").open()))
    assert row["candidate_record_kind"] == "itch_raw_binary"
    assert row["candidate_format_version"] == "ITCH-4.1"
    assert row["status"] == "REQUIRES_AUTHORIZED_DECODER"
    assert manifest["high_confidence_contract_candidates"] == 0
    contract = json.loads((out / "market_contract.pending.json").read_text())
    assert contract["sources"] == []


def test_ambiguous_file_never_enters_pending_contract(tmp_path: Path):
    drop = tmp_path / "drop"
    out = tmp_path / "out"
    drop.mkdir()
    (drop / "notes_20150217.txt").write_text("hello world\nnot market data\n", encoding="utf-8")

    intake.scan(drop, out)
    row = next(csv.DictReader((out / "intake_files.csv").open()))
    assert row["status"] == "UNCLASSIFIED"
    contract = json.loads((out / "market_contract.pending.json").read_text())
    assert contract["sources"] == []


def test_generic_vendor_names_do_not_impersonate_nyse_or_cboe(tmp_path: Path):
    cases = [
        (
            "tickdata_equity_trades_20150217.csv",
            "timestamp,symbol,price,size\n2015-02-17 09:30:00,TEST,100,10\n",
            "equity_trade",
            "generic_authorized_market_data",
        ),
        (
            "databento_opra_trades_20150217.csv",
            "timestamp,underlying_symbol,option_symbol,expiration,strike,option_type,price,size\n"
            "2015-02-17 09:30:00,TEST,TEST150220C00100000,2015-02-20,100,C,2.5,10\n",
            "option_trade",
            "generic_authorized_market_data",
        ),
        (
            "lseg_opra_trades_20110321.csv",
            "timestamp,underlying_symbol,option_symbol,expiration,strike,option_type,price,size\n"
            "2011-03-21 09:30:00,TEST,TEST110416C00100000,2011-04-16,100,C,2.5,10\n",
            "option_trade",
            "generic_authorized_market_data",
        ),
        (
            "cboe_option_trades_20150217.csv",
            "timestamp,underlying_symbol,option_symbol,expiration,strike,option_type,price,size\n"
            "2015-02-17 09:30:00,TEST,TEST150220C00100000,2015-02-20,100,C,2.5,10\n",
            "option_trade",
            "cboe_option_trades",
        ),
    ]

    for filename, body, expected_kind, expected_family in cases:
        drop = tmp_path / filename.replace(".csv", "")
        out = tmp_path / (drop.name + "_out")
        drop.mkdir()
        (drop / filename).write_text(body, encoding="utf-8")
        intake.scan(drop, out)
        row = next(csv.DictReader((out / "intake_files.csv").open()))
        assert row["candidate_record_kind"] == expected_kind
        assert row["candidate_source_family"] == expected_family
