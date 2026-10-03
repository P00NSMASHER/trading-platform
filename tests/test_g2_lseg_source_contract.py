import csv
import json
from pathlib import Path

import pytest

import g2_lseg_source_contract as contract
import historical_market_backfill as hmb


def _write_csv(path: Path, fields: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _write_equity_adaptation(root: Path, trade_date: str = "2011-04-27") -> Path:
    folder = root / trade_date / "equity"
    folder.mkdir(parents=True, exist_ok=True)

    _write_csv(
        folder / "equity_trades.csv",
        ["timestamp", "symbol", "price", "size", "exchange", "conditions"],
        [
            {
                "timestamp": "2011-04-27T15:22:00-04:00",
                "symbol": "CNMD",
                "price": "25.10",
                "size": "200",
                "exchange": "Q",
                "conditions": "",
            }
        ],
    )
    _write_csv(
        folder / "equity_quotes.csv",
        [
            "timestamp", "symbol", "bid", "ask", "bid_size", "ask_size",
            "exchange", "conditions",
        ],
        [
            {
                "timestamp": "2011-04-27T15:21:59-04:00",
                "symbol": "CNMD",
                "bid": "25.05",
                "ask": "25.15",
                "bid_size": "3",
                "ask_size": "4",
                "exchange": "Q",
                "conditions": "",
            }
        ],
    )
    receipt = {
        "schema_version": "1",
        "lane": "equity",
        "trade_date": trade_date,
        "summary": {
            "trade_rows": 1,
            "quote_rows": 1,
            "g2_coverage_change": False,
        },
    }
    receipt_path = folder / "lseg_adaptation_receipt.json"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    return receipt_path


def _write_option_adaptation(root: Path, trade_date: str = "2011-04-27") -> Path:
    folder = root / trade_date / "options"
    folder.mkdir(parents=True, exist_ok=True)

    _write_csv(
        folder / "option_trades.csv",
        [
            "timestamp", "symbol", "underlying_symbol", "option_symbol",
            "expiration", "strike", "option_type", "price", "size",
            "exchange", "conditions",
        ],
        [
            {
                "timestamp": "2011-04-27T15:22:00-04:00",
                "symbol": "CNMDD271102500",
                "underlying_symbol": "CNMD",
                "option_symbol": "CNMDD271102500",
                "expiration": "2011-04-27",
                "strike": "25",
                "option_type": "call",
                "price": "1.25",
                "size": "10",
                "exchange": "",
                "conditions": "",
            }
        ],
    )
    _write_csv(
        folder / "option_quotes.csv",
        [
            "timestamp", "symbol", "underlying_symbol", "option_symbol",
            "expiration", "strike", "option_type", "bid", "ask",
            "bid_size", "ask_size", "exchange", "conditions",
        ],
        [
            {
                "timestamp": "2011-04-27T15:21:59-04:00",
                "symbol": "CNMDD271102500",
                "underlying_symbol": "CNMD",
                "option_symbol": "CNMDD271102500",
                "expiration": "2011-04-27",
                "strike": "25",
                "option_type": "call",
                "bid": "1.20",
                "ask": "1.30",
                "bid_size": "5",
                "ask_size": "7",
                "exchange": "",
                "conditions": "",
            }
        ],
    )
    receipt = {
        "schema_version": "1",
        "lane": "options",
        "trade_date": trade_date,
        "summary": {
            "trade_rows": 1,
            "quote_rows": 1,
            "g2_coverage_change": False,
        },
    }
    receipt_path = folder / "lseg_adaptation_receipt.json"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    return receipt_path


def test_builds_four_lane_contract_and_validates_with_production_loader(tmp_path: Path):
    adapted = tmp_path / "adapted"
    _write_equity_adaptation(adapted)
    _write_option_adaptation(adapted)

    identity = tmp_path / "security_identity_manifest.json"
    identity.write_text('{"schema_version":"1"}', encoding="utf-8")
    output = tmp_path / "contract" / "historical_market_sources.lseg.json"

    payload = contract.write_contract(
        adapted_root=adapted,
        output_path=output,
        license_reference="verified-lseg-entitlement",
        security_identity_manifest=identity,
    )

    assert len(payload["sources"]) == 4
    assert payload["security_identity_manifest"] == "../security_identity_manifest.json"
    assert {
        row["record_kind"] for row in payload["sources"]
    } == {
        "equity_trade",
        "equity_quote",
        "option_trade",
        "option_quote",
    }
    assert all(
        row["source_family"] == "generic_authorized_market_data"
        for row in payload["sources"]
    )
    assert all(
        row["data_classification"] == hmb.NON_SYNTHETIC_CLASS
        for row in payload["sources"]
    )
    assert all(row["authorized"] is True for row in payload["sources"])
    assert all(
        row["license_reference"] == "verified-lseg-entitlement"
        for row in payload["sources"]
    )

    loaded, raw = hmb.load_contract(output)
    assert len(loaded) == 4
    assert raw["security_identity_manifest"] == "../security_identity_manifest.json"


def test_contract_paths_are_relative_to_contract_location(tmp_path: Path):
    adapted = tmp_path / "private" / "adapted"
    _write_equity_adaptation(adapted)
    output = tmp_path / "private" / "contracts" / "sources.json"

    payload = contract.write_contract(
        adapted_root=adapted,
        output_path=output,
        license_reference="entitlement-ref",
    )

    for source in payload["sources"]:
        assert not Path(source["path"]).is_absolute()
        resolved = (output.parent / source["path"]).resolve()
        assert resolved.exists()


def test_empty_lane_file_is_omitted_not_promoted(tmp_path: Path):
    adapted = tmp_path / "adapted"
    receipt = _write_equity_adaptation(adapted)
    (receipt.parent / "equity_quotes.csv").write_text(
        "timestamp,symbol,bid,ask,bid_size,ask_size,exchange,conditions\n",
        encoding="utf-8",
    )
    output = tmp_path / "contract.json"

    payload = contract.write_contract(
        adapted_root=adapted,
        output_path=output,
        license_reference="entitlement-ref",
    )

    assert [row["record_kind"] for row in payload["sources"]] == ["equity_trade"]
    report = payload["lseg_generation_receipts"][0]
    assert report["omitted"] == [
        {
            "record_kind": "equity_quote",
            "reason": "adapted_file_has_no_data_rows",
            "path_name": "equity_quotes.csv",
        }
    ]


def test_blank_license_reference_fails_closed(tmp_path: Path):
    adapted = tmp_path / "adapted"
    _write_equity_adaptation(adapted)

    with pytest.raises(ValueError, match="license_reference"):
        contract.build_contract(
            adapted_root=adapted,
            output_path=tmp_path / "contract.json",
            license_reference="",
        )


def test_receipt_cannot_claim_coverage(tmp_path: Path):
    adapted = tmp_path / "adapted"
    receipt = _write_equity_adaptation(adapted)
    payload = json.loads(receipt.read_text())
    payload["summary"]["g2_coverage_change"] = True
    receipt.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="non-authoritative"):
        contract.build_contract(
            adapted_root=adapted,
            output_path=tmp_path / "contract.json",
            license_reference="entitlement-ref",
        )


def test_duplicate_date_lane_receipts_fail_closed(tmp_path: Path):
    adapted = tmp_path / "adapted"
    first = _write_equity_adaptation(adapted)
    duplicate = adapted / "duplicate" / "equity"
    duplicate.mkdir(parents=True, exist_ok=True)
    for name in ("equity_trades.csv", "equity_quotes.csv"):
        duplicate.joinpath(name).write_bytes(first.parent.joinpath(name).read_bytes())
    duplicate.joinpath("lseg_adaptation_receipt.json").write_bytes(first.read_bytes())

    with pytest.raises(ValueError, match="duplicate generated source_id"):
        contract.build_contract(
            adapted_root=adapted,
            output_path=tmp_path / "contract.json",
            license_reference="entitlement-ref",
        )
