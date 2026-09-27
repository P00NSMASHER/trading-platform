from __future__ import annotations

import csv
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import licensed_data_drop_processor as drop


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_entitlement(path: Path, files: list[dict]) -> None:
    path.write_text(json.dumps({"schema_version": "1", "files": files}, indent=2), encoding="utf-8")


def _taq_file(root: Path) -> Path:
    root.mkdir()
    p = root / "taq_trades_20150217.csv"
    p.write_text(
        "timestamp,symbol,price,size,exchange,conditions\n"
        "2015-02-17 09:30:00,TEST,100,10,N,@\n",
        encoding="utf-8",
    )
    return p


def test_exact_hash_and_license_reference_activate_source(tmp_path: Path):
    drop_dir = tmp_path / "drop"
    data = _taq_file(drop_dir)
    ent = tmp_path / "entitlement.json"
    _write_entitlement(ent, [{
        "sha256": _sha256(data),
        "authorized": True,
        "license_reference": "ENTITLEMENT-123",
        "source_family": "nyse_daily_taq",
        "record_kind": "equity_trade",
        "trade_date": "2015-02-17",
        "delimiter": ",",
    }])

    contract = tmp_path / "real.json"
    receipt = drop.activate(
        drop_dir=drop_dir,
        work_dir=tmp_path / "work",
        entitlement_manifest=ent,
        market_contract_out=contract,
    )

    assert receipt["activated_source_count"] == 1
    assert receipt["rejected_entry_count"] == 0
    obj = json.loads(contract.read_text())
    source = obj["sources"][0]
    assert source["authorized"] is True
    assert source["data_classification"] == "authorized_historical_market_data"
    assert source["license_reference"] == "ENTITLEMENT-123"
    assert source["source_family"] == "nyse_daily_taq"
    assert source["record_kind"] == "equity_trade"
    assert source["trade_date"] == "2015-02-17"


def test_wrong_hash_never_activates(tmp_path: Path):
    drop_dir = tmp_path / "drop"
    _taq_file(drop_dir)
    ent = tmp_path / "entitlement.json"
    _write_entitlement(ent, [{
        "sha256": "0" * 64,
        "authorized": True,
        "license_reference": "ENTITLEMENT-123",
        "source_family": "nyse_daily_taq",
        "record_kind": "equity_trade",
        "trade_date": "2015-02-17",
    }])

    contract = tmp_path / "real.json"
    receipt = drop.activate(
        drop_dir=drop_dir,
        work_dir=tmp_path / "work",
        entitlement_manifest=ent,
        market_contract_out=contract,
    )

    assert receipt["activated_source_count"] == 0
    assert receipt["rejected_entry_count"] == 1
    assert receipt["rejected_entries"][0]["reason"] == "sha256_not_present_in_intake_inventory"
    assert json.loads(contract.read_text())["sources"] == []


def test_blank_license_reference_never_activates(tmp_path: Path):
    drop_dir = tmp_path / "drop"
    data = _taq_file(drop_dir)
    ent = tmp_path / "entitlement.json"
    _write_entitlement(ent, [{
        "sha256": _sha256(data),
        "authorized": True,
        "license_reference": "",
        "source_family": "nyse_daily_taq",
        "record_kind": "equity_trade",
        "trade_date": "2015-02-17",
    }])

    receipt = drop.activate(
        drop_dir=drop_dir,
        work_dir=tmp_path / "work",
        entitlement_manifest=ent,
        market_contract_out=tmp_path / "real.json",
    )
    assert receipt["activated_source_count"] == 0
    assert receipt["rejected_entries"][0]["reason"] == "license_reference_required"


def test_entitlement_cannot_override_scanned_family_or_date(tmp_path: Path):
    drop_dir = tmp_path / "drop"
    data = _taq_file(drop_dir)
    ent = tmp_path / "entitlement.json"
    _write_entitlement(ent, [{
        "sha256": _sha256(data),
        "authorized": True,
        "license_reference": "ENTITLEMENT-123",
        "source_family": "cboe_option_trades",
        "record_kind": "equity_trade",
        "trade_date": "2015-02-17",
    }])
    receipt = drop.activate(
        drop_dir=drop_dir,
        work_dir=tmp_path / "work",
        entitlement_manifest=ent,
        market_contract_out=tmp_path / "real.json",
    )
    assert receipt["activated_source_count"] == 0
    assert receipt["rejected_entries"][0]["reason"] == "source_family_mismatch_with_intake"

    _write_entitlement(ent, [{
        "sha256": _sha256(data),
        "authorized": True,
        "license_reference": "ENTITLEMENT-123",
        "source_family": "nyse_daily_taq",
        "record_kind": "equity_trade",
        "trade_date": "2015-02-18",
    }])
    receipt = drop.activate(
        drop_dir=drop_dir,
        work_dir=tmp_path / "work2",
        entitlement_manifest=ent,
        market_contract_out=tmp_path / "real2.json",
    )
    assert receipt["activated_source_count"] == 0
    assert receipt["rejected_entries"][0]["reason"] == "trade_date_mismatch_with_intake"


def test_raw_itch_cannot_be_auto_activated(tmp_path: Path):
    drop_dir = tmp_path / "drop"
    drop_dir.mkdir()
    raw = drop_dir / "nasdaq_itch41_20130425.bin"
    raw.write_bytes(b"\x00\x01\x02\x03binary")
    ent = tmp_path / "entitlement.json"
    _write_entitlement(ent, [{
        "sha256": _sha256(raw),
        "authorized": True,
        "license_reference": "ITCH-ENTITLEMENT",
        "source_family": "nasdaq_itch_4_1_decoded",
        "record_kind": "itch_decoded",
        "trade_date": "2013-04-25",
    }])

    receipt = drop.activate(
        drop_dir=drop_dir,
        work_dir=tmp_path / "work",
        entitlement_manifest=ent,
        market_contract_out=tmp_path / "real.json",
    )
    assert receipt["activated_source_count"] == 0
    assert "intake_status_not_activatable" in receipt["rejected_entries"][0]["reason"]


def test_unauthorized_entry_never_activates(tmp_path: Path):
    drop_dir = tmp_path / "drop"
    data = _taq_file(drop_dir)
    ent = tmp_path / "entitlement.json"
    _write_entitlement(ent, [{
        "sha256": _sha256(data),
        "authorized": False,
        "license_reference": "ENTITLEMENT-123",
        "source_family": "nyse_daily_taq",
        "record_kind": "equity_trade",
        "trade_date": "2015-02-17",
    }])
    receipt = drop.activate(
        drop_dir=drop_dir,
        work_dir=tmp_path / "work",
        entitlement_manifest=ent,
        market_contract_out=tmp_path / "real.json",
    )
    assert receipt["activated_source_count"] == 0
    assert receipt["rejected_entries"][0]["reason"] == "authorized_must_be_true"
