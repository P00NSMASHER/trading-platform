from __future__ import annotations

import csv
import json
from pathlib import Path

import g2_vendor_content_preflight as content_preflight


REQUEST_FIELDS = [
    "trade_date",
    "record_kind",
    "historical_symbols",
    "unique_symbol_count",
    "symbol_date_pair_count",
    "route",
]


def _write_request(path: Path, *, day: str = "2015-02-17") -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=REQUEST_FIELDS)
        writer.writeheader()
        writer.writerow(
            {
                "trade_date": day,
                "record_kind": "equity_trade",
                "historical_symbols": "AAA;BBB",
                "unique_symbol_count": "2",
                "symbol_date_pair_count": "2",
                "route": "candidate_tickdata_equity_trades",
            }
        )


def _source(source_id: str, path: Path, day: str = "2015-02-17") -> dict:
    return {
        "source_id": source_id,
        "source_family": "generic_authorized_market_data",
        "record_kind": "equity_trade",
        "path": str(path),
        "authorized": True,
        "data_classification": "authorized_historical_market_data",
        "license_reference": "LICENSE-TEST",
        "trade_date": day,
        "timezone": "America/New_York",
        "delimiter": ",",
        "encoding": "utf-8",
        "format_version": "fixture",
        "column_map": {},
    }


def _write_contract(path: Path, sources: list[dict]) -> None:
    path.write_text(
        json.dumps({"schema_version": "1", "sources": sources}, indent=2),
        encoding="utf-8",
    )


def test_content_preflight_unions_split_files_for_required_symbols(tmp_path: Path):
    request = tmp_path / "request.csv"
    _write_request(request)

    a = tmp_path / "a.csv"
    b = tmp_path / "b.csv"
    a.write_text(
        "timestamp,symbol,price,size\n"
        "2015-02-17 09:30:00,AAA,10,100\n",
        encoding="utf-8",
    )
    b.write_text(
        "timestamp,symbol,price,size\n"
        "2015-02-17 09:31:00,BBB,20,200\n",
        encoding="utf-8",
    )

    contract = tmp_path / "contract.json"
    _write_contract(contract, [_source("a", a), _source("b", b)])

    result = content_preflight.preflight(request, contract)

    assert result["requested_source_date_rows"] == 1
    assert result["requested_symbol_date_pairs"] == 2
    assert result["content_complete_source_date_rows"] == 1
    assert result["content_complete_symbol_date_pairs"] == 2
    assert result["missing_or_invalid_source_date_rows"] == 0
    assert result["ready_for_coverage_audit"] is True
    assert result["dates"][0]["missing_required_symbols"] == []
    assert result["dates"][0]["observed_required_symbol_count"] == 2
    assert result["coverage_policy"]["g2_coverage_counted"] is False


def test_content_preflight_blocks_missing_required_symbol(tmp_path: Path):
    request = tmp_path / "request.csv"
    _write_request(request)

    a = tmp_path / "a.csv"
    a.write_text(
        "timestamp,symbol,price,size\n"
        "2015-02-17 09:30:00,AAA,10,100\n",
        encoding="utf-8",
    )

    contract = tmp_path / "contract.json"
    _write_contract(contract, [_source("a", a)])

    result = content_preflight.preflight(request, contract)

    assert result["content_complete_source_date_rows"] == 0
    assert result["missing_or_invalid_source_date_rows"] == 1
    assert result["ready_for_coverage_audit"] is False
    assert result["dates"][0]["missing_required_symbols"] == ["BBB"]


def test_content_preflight_fails_closed_on_malformed_relevant_source(tmp_path: Path):
    request = tmp_path / "request.csv"
    _write_request(request)

    good = tmp_path / "good.csv"
    bad = tmp_path / "bad.csv"
    good.write_text(
        "timestamp,symbol,price,size\n"
        "2015-02-17 09:30:00,AAA,10,100\n"
        "2015-02-17 09:31:00,BBB,20,200\n",
        encoding="utf-8",
    )
    bad.write_text(
        "timestamp,symbol,price,size\n"
        "2015-02-17 09:32:00,AAA,NOT_A_PRICE,10\n",
        encoding="utf-8",
    )

    contract = tmp_path / "contract.json"
    _write_contract(contract, [_source("good", good), _source("bad", bad)])

    result = content_preflight.preflight(request, contract)

    assert result["content_complete_source_date_rows"] == 0
    assert result["source_error_count"] == 1
    assert result["ready_for_coverage_audit"] is False
    assert result["dates"][0]["source_error_count"] == 1
    assert result["dates"][0]["source_errors"][0]["source_id"] == "bad"


def test_content_preflight_rejects_unexpected_declared_date(tmp_path: Path):
    request = tmp_path / "request.csv"
    _write_request(request)

    good = tmp_path / "good.csv"
    extra = tmp_path / "extra.csv"
    good.write_text(
        "timestamp,symbol,price,size\n"
        "2015-02-17 09:30:00,AAA,10,100\n"
        "2015-02-17 09:31:00,BBB,20,200\n",
        encoding="utf-8",
    )
    extra.write_text(
        "timestamp,symbol,price,size\n"
        "2015-02-18 09:30:00,AAA,10,100\n",
        encoding="utf-8",
    )

    contract = tmp_path / "contract.json"
    _write_contract(
        contract,
        [_source("good", good), _source("extra", extra, day="2015-02-18")],
    )

    result = content_preflight.preflight(request, contract)

    assert result["content_complete_source_date_rows"] == 1
    assert result["unexpected_declared_dates"] == ["2015-02-18"]
    assert result["ready_for_coverage_audit"] is False
