from __future__ import annotations

import csv
import json
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

import g4_exact_activation as activation
import g4_exchange_reference_completion as exact
import metadata_resolver as resolver


ROOT = Path(__file__).resolve().parents[1]
NY = ZoneInfo("America/New_York")


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "historical_symbol",
        "target_trade_date",
        "fact_date",
        "available_at",
        "shares_outstanding",
        "source_reference",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _private_completion(root: Path) -> None:
    nyse_rows = []
    for (symbol, target), source_date in sorted(exact.NYSE_TARGETS.items()):
        day = exact.date.fromisoformat(source_date)
        available = datetime.combine(day, time(23, 59, 59), tzinfo=NY)
        nyse_rows.append(
            {
                "historical_symbol": symbol,
                "target_trade_date": target,
                "fact_date": source_date,
                "available_at": available.isoformat(),
                "shares_outstanding": "32200000" if symbol == "ACO" else "166900000",
                "source_reference": f"EQY_US_ALL_REF_MASTER_{source_date.replace('-', '')}.zip",
            }
        )

    nasdaq_rows = []
    for (symbol, target), source_date in sorted(exact.NASDAQ_TARGETS.items()):
        nasdaq_rows.append(
            {
                "historical_symbol": symbol,
                "target_trade_date": target,
                "fact_date": "2015-02-01",
                "available_at": f"{source_date}T07:15:00-05:00",
                "shares_outstanding": "86544015",
                "source_reference": f"NASDAQ{exact.date.fromisoformat(source_date).strftime('%m%d%Y')}.txt",
            }
        )

    _write_csv(root / "g4_nyse_exact_shares.csv", nyse_rows)
    _write_csv(root / "g4_nasdaq_exact_shares.csv", nasdaq_rows)
    receipt = {
        "schema_version": "1",
        "status": "READY_FOR_PRIVATE_G4_ACTIVATION",
        "rows_materialized": 18,
        "nyse_rows": 13,
        "nasdaq_rows": 5,
        "g4_target_state": {
            "required": 3828,
            "exact_resolved": 3828,
            "reviewed_excluded": 0,
            "blocking_unresolved": 0,
        },
    }
    (root / "g4_exact_materialization_receipt.json").write_text(
        json.dumps(receipt, indent=2) + "\n",
        encoding="utf-8",
    )


def test_activation_contract_atomically_replaces_g4_exclusions(tmp_path: Path):
    private = tmp_path / "private"
    private.mkdir()
    _private_completion(private)
    output = tmp_path / "active_metadata_sources.json"

    result = activation.build_activation_contract(
        private_root=private,
        base_contract=ROOT / "config/metadata_sources.public_progress.json",
        output_contract=output,
        nyse_license_reference="NYSE entitlement case test",
        nasdaq_license_reference="Nasdaq authorized historical extract test",
    )

    assert result["status"] == "STAGED_EXACT_G4_CONTRACT"
    assert result["g4_target_state"]["exact_resolved"] == 3828
    assert result["canonical_outputs_modified"] is False

    raw = json.loads(output.read_text(encoding="utf-8"))
    assert raw["reviewed_share_exclusions"]["enabled"] is False

    sources = {source["source_id"]: source for source in raw["sources"]}
    nyse = sources["private-g4-nyse-taq-master-exact-completion"]
    nasdaq = sources["private-g4-nasdaq-fundamental-exact-completion"]
    assert nyse["record_kind"] == "shares_outstanding"
    assert nyse["source_family"] == "nyse_daily_taq_master"
    assert nyse["authorized"] is True
    assert nyse["data_classification"] == "authorized_reference_data"
    assert nasdaq["source_family"] == "generic_authorized_reference_data"
    assert nasdaq["authorized"] is True

    # Production parser must accept the generated runtime contract.
    resolver.load_contract(output)


def test_activation_rejects_partial_private_delivery(tmp_path: Path):
    private = tmp_path / "private"
    private.mkdir()
    _private_completion(private)

    path = private / "g4_nasdaq_exact_shares.csv"
    rows = list(csv.DictReader(path.open(newline="", encoding="utf-8")))
    _write_csv(path, rows[:-1])

    with pytest.raises(ValueError, match="row counts"):
        activation.load_private_completion(private)


def test_activation_rejects_blank_license_reference(tmp_path: Path):
    private = tmp_path / "private"
    private.mkdir()
    _private_completion(private)

    with pytest.raises(ValueError, match="nyse_license_reference"):
        activation.build_activation_contract(
            private_root=private,
            base_contract=ROOT / "config/metadata_sources.public_progress.json",
            output_contract=tmp_path / "active.json",
            nyse_license_reference="",
            nasdaq_license_reference="Nasdaq authorized historical extract test",
        )


def test_activation_rechecks_pre_cutoff_availability(tmp_path: Path):
    private = tmp_path / "private"
    private.mkdir()
    _private_completion(private)

    path = private / "g4_nasdaq_exact_shares.csv"
    rows = list(csv.DictReader(path.open(newline="", encoding="utf-8")))
    rows[0]["available_at"] = f"{rows[0]['target_trade_date']}T16:00:00-05:00"
    _write_csv(path, rows)

    with pytest.raises(ValueError, match="after cutoff"):
        activation.load_private_completion(private)


def test_resolver_verification_requires_exact_3828_no_exclusions(tmp_path: Path):
    good = {
        "shares_symbol_dates_resolved": 3828,
        "shares_symbol_dates_excluded": 0,
        "shares_symbol_dates_accounted_for": 3828,
        "shares_symbol_dates_unresolved": 0,
        "ready_g4_shares_outstanding": True,
    }
    (tmp_path / "metadata_readiness_summary.json").write_text(
        json.dumps(good),
        encoding="utf-8",
    )
    assert activation.validate_resolver_output(tmp_path) == good

    bad = dict(good)
    bad["shares_symbol_dates_resolved"] = 3827
    bad["shares_symbol_dates_excluded"] = 1
    (tmp_path / "metadata_readiness_summary.json").write_text(
        json.dumps(bad),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="did not reach exact 3828"):
        activation.validate_resolver_output(tmp_path)
