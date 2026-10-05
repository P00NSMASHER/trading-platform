from __future__ import annotations

import csv
import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import g5_control_activation as activation


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _control_csv(path: Path, event_dates: list[str]) -> None:
    fields = [
        "event_date",
        "historical_symbol",
        "available_at",
        "sector",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for event_date in event_dates:
            symbols = (
                ["ADBE", "LBMH", "WG"]
                if event_date == "2014-12-15"
                else ["TEST1", "TEST2", "TEST3"]
            )
            for symbol in symbols:
                writer.writerow(
                    {
                        "event_date": event_date,
                        "historical_symbol": symbol,
                        "available_at": f"{event_date}T08:00:00-05:00",
                        "sector": "TECH",
                    }
                )


def _manifest(tmp_path: Path, csv_path: Path, *, sha: str | None = None, license_reference: str = "AUTHORIZED-TEST") -> Path:
    path = tmp_path / "manifest.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "1",
                "research_use_only": True,
                "sources": [
                    {
                        "source_id": "private-g5-test-control-source",
                        "path": str(csv_path),
                        "expected_sha256": sha or _sha256(csv_path),
                        "license_reference": license_reference,
                        "timezone": "America/New_York",
                        "delimiter": ",",
                        "encoding": "utf-8",
                        "column_map": {
                            "event_date": "event_date",
                            "historical_symbol": "historical_symbol",
                            "available_at": "available_at",
                            "sector": "sector",
                        },
                    }
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def test_stage_one_real_g5_date_shrinks_exclusions_without_promoting_readiness(tmp_path: Path):
    data = tmp_path / "control.csv"
    _control_csv(data, ["2014-12-15"])
    manifest = _manifest(tmp_path, data)
    contract = tmp_path / "active.json"
    exclusions = tmp_path / "remaining.json"

    result = activation.build_activation_contract(
        source_manifest=manifest,
        activate_dates=["2014-12-15"],
        output_contract=contract,
        replacement_exclusions_output=exclusions,
        base_contract=ROOT / "config/metadata_sources.public_progress.json",
        events_path=ROOT / "data/processed/historical_events.csv",
    )

    assert result["status"] == "STAGED_PARTIAL_G5_ACTIVATION"
    assert result["required_event_date_count"] == 72
    assert result["activated_date_count"] == 1
    assert result["remaining_excluded_date_count"] == 71
    assert result["expected_control_dates_resolved_after_validation"] == 1
    assert result["canonical_outputs_modified"] is False
    assert result["control_readiness_promoted"] is False
    assert result["model_evaluation_ready_claimed"] is False

    replacement = json.loads(exclusions.read_text(encoding="utf-8"))
    remaining_dates = {row["event_date"] for row in replacement["exclusions"]}
    assert "2014-12-15" not in remaining_dates
    assert len(remaining_dates) == 71

    staged = json.loads(contract.read_text(encoding="utf-8"))
    spec = staged["reviewed_control_exclusions"]
    assert spec["enabled"] is True
    assert spec["expected_count"] == 71
    assert spec["expected_sha256"] == _sha256(exclusions)
    assert spec["path"] == str(exclusions.resolve())
    added = [s for s in staged["sources"] if s["source_id"] == "private-g5-test-control-source"]
    assert len(added) == 1
    assert added[0]["authorized"] is True
    assert added[0]["record_kind"] == "control_universe"
    assert added[0]["source_family"] == "generic_authorized_reference_data"


def test_source_for_still_excluded_date_fails_closed(tmp_path: Path):
    data = tmp_path / "control.csv"
    _control_csv(data, ["2014-12-15", "2015-01-20"])
    manifest = _manifest(tmp_path, data)

    with pytest.raises(activation.G5ControlActivationError, match="still-excluded date"):
        activation.build_activation_contract(
            source_manifest=manifest,
            activate_dates=["2014-12-15"],
            output_contract=tmp_path / "active.json",
            replacement_exclusions_output=tmp_path / "remaining.json",
            base_contract=ROOT / "config/metadata_sources.public_progress.json",
            events_path=ROOT / "data/processed/historical_events.csv",
        )


def test_source_hash_and_license_are_required(tmp_path: Path):
    data = tmp_path / "control.csv"
    _control_csv(data, ["2014-12-15"])

    bad_hash = _manifest(tmp_path, data, sha="0" * 64)
    with pytest.raises(activation.G5ControlActivationError, match="SHA-256 mismatch"):
        activation.build_activation_contract(
            source_manifest=bad_hash,
            activate_dates=["2014-12-15"],
            output_contract=tmp_path / "active-hash.json",
            replacement_exclusions_output=tmp_path / "remaining-hash.json",
            base_contract=ROOT / "config/metadata_sources.public_progress.json",
            events_path=ROOT / "data/processed/historical_events.csv",
        )

    no_license = _manifest(tmp_path, data, license_reference="")
    with pytest.raises(activation.G5ControlActivationError, match="license_reference"):
        activation.build_activation_contract(
            source_manifest=no_license,
            activate_dates=["2014-12-15"],
            output_contract=tmp_path / "active-license.json",
            replacement_exclusions_output=tmp_path / "remaining-license.json",
            base_contract=ROOT / "config/metadata_sources.public_progress.json",
            events_path=ROOT / "data/processed/historical_events.csv",
        )


def test_unknown_or_unrepresented_activation_date_fails_closed(tmp_path: Path):
    data = tmp_path / "control.csv"
    _control_csv(data, ["2014-12-15"])
    manifest = _manifest(tmp_path, data)

    with pytest.raises(activation.G5ControlActivationError, match="not currently reviewed exclusions"):
        activation.build_activation_contract(
            source_manifest=manifest,
            activate_dates=["2010-01-01"],
            output_contract=tmp_path / "active-unknown.json",
            replacement_exclusions_output=tmp_path / "remaining-unknown.json",
            base_contract=ROOT / "config/metadata_sources.public_progress.json",
            events_path=ROOT / "data/processed/historical_events.csv",
        )

    empty_date = tmp_path / "other.csv"
    _control_csv(empty_date, ["2015-01-20"])
    other_manifest = _manifest(tmp_path, empty_date)
    with pytest.raises(activation.G5ControlActivationError, match="still-excluded date"):
        activation.build_activation_contract(
            source_manifest=other_manifest,
            activate_dates=["2014-12-15"],
            output_contract=tmp_path / "active-missing.json",
            replacement_exclusions_output=tmp_path / "remaining-missing.json",
            base_contract=ROOT / "config/metadata_sources.public_progress.json",
            events_path=ROOT / "data/processed/historical_events.csv",
        )


def test_resolver_validation_distinguishes_accounted_from_model_eval_ready(tmp_path: Path):
    summary = {
        "event_date_count": 72,
        "control_dates_resolved": 1,
        "control_dates_excluded": 71,
        "control_dates_accounted_for": 72,
        "control_dates_partial": 0,
        "control_dates_unresolved": 0,
        "ready_g5_matched_control_universe": True,
        "ready_g5_model_evaluation_controls": False,
    }
    (tmp_path / "metadata_readiness_summary.json").write_text(
        json.dumps(summary),
        encoding="utf-8",
    )
    actual = activation.validate_resolver_output(
        tmp_path,
        required_event_date_count=72,
        remaining_excluded_date_count=71,
    )
    assert actual["ready_g5_matched_control_universe"] is True
    assert actual["ready_g5_model_evaluation_controls"] is False

    summary["ready_g5_model_evaluation_controls"] = True
    (tmp_path / "metadata_readiness_summary.json").write_text(
        json.dumps(summary),
        encoding="utf-8",
    )
    with pytest.raises(activation.G5ControlActivationError, match="resolver activation state mismatch"):
        activation.validate_resolver_output(
            tmp_path,
            required_event_date_count=72,
            remaining_excluded_date_count=71,
        )


def test_exact_final_validation_requires_72_resolved_and_zero_exclusions(tmp_path: Path):
    summary = {
        "event_date_count": 72,
        "control_dates_resolved": 72,
        "control_dates_excluded": 0,
        "control_dates_accounted_for": 72,
        "control_dates_partial": 0,
        "control_dates_unresolved": 0,
        "ready_g5_matched_control_universe": True,
        "ready_g5_model_evaluation_controls": True,
    }
    (tmp_path / "metadata_readiness_summary.json").write_text(
        json.dumps(summary),
        encoding="utf-8",
    )
    actual = activation.validate_resolver_output(
        tmp_path,
        required_event_date_count=72,
        remaining_excluded_date_count=0,
    )
    assert actual["control_dates_resolved"] == 72
    assert actual["ready_g5_model_evaluation_controls"] is True


def test_quality_validation_requires_zero_control_quarantine(tmp_path: Path):
    summary = {
        "quarantined_control_dates": 0,
        "reviewed_control_exclusion_count": 71,
        "domain_quality": [
            {
                "domain": "control_universe",
                "status": "READY_WITH_REVIEWED_EXCLUSIONS",
            }
        ],
    }
    (tmp_path / "metadata_quality_summary.json").write_text(
        json.dumps(summary),
        encoding="utf-8",
    )
    assert activation.validate_quality_output(
        tmp_path,
        remaining_excluded_date_count=71,
    )["quarantined_control_dates"] == 0

    summary["quarantined_control_dates"] = 1
    (tmp_path / "metadata_quality_summary.json").write_text(
        json.dumps(summary),
        encoding="utf-8",
    )
    with pytest.raises(activation.G5ControlActivationError, match="quality activation state mismatch"):
        activation.validate_quality_output(
            tmp_path,
            remaining_excluded_date_count=71,
        )


def test_source_availability_after_first_event_cutoff_fails_closed(tmp_path: Path):
    data = tmp_path / "late-control.csv"
    fields = ["event_date", "historical_symbol", "available_at", "sector"]
    with data.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerow(
            {
                "event_date": "2014-12-15",
                "historical_symbol": "LATE",
                "available_at": "2014-12-15T23:59:59-05:00",
                "sector": "TECH",
            }
        )
    manifest = _manifest(tmp_path, data)

    with pytest.raises(activation.G5ControlActivationError, match="after first event cutoff"):
        activation.build_activation_contract(
            source_manifest=manifest,
            activate_dates=["2014-12-15"],
            output_contract=tmp_path / "active-late.json",
            replacement_exclusions_output=tmp_path / "remaining-late.json",
            base_contract=ROOT / "config/metadata_sources.public_progress.json",
            events_path=ROOT / "data/processed/historical_events.csv",
        )


def test_non_candidate_symbol_fails_closed(tmp_path: Path):
    data = tmp_path / "noncandidate.csv"
    fields = ["event_date", "historical_symbol", "available_at", "sector"]
    with data.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for symbol in ["ADBE", "LBMH", "NOT_A_CANONICAL_CONTROL"]:
            writer.writerow(
                {
                    "event_date": "2014-12-15",
                    "historical_symbol": symbol,
                    "available_at": "2014-12-15T08:00:00-05:00",
                    "sector": "TECH",
                }
            )
    manifest = _manifest(tmp_path, data)

    with pytest.raises(activation.G5ControlActivationError, match="canonical G5 candidate plan"):
        activation.build_activation_contract(
            source_manifest=manifest,
            activate_dates=["2014-12-15"],
            output_contract=tmp_path / "active-noncandidate.json",
            replacement_exclusions_output=tmp_path / "remaining-noncandidate.json",
            base_contract=ROOT / "config/metadata_sources.public_progress.json",
            events_path=ROOT / "data/processed/historical_events.csv",
        )


def test_activation_requires_at_least_three_canonical_candidate_symbols(tmp_path: Path):
    data = tmp_path / "two-candidates.csv"
    fields = ["event_date", "historical_symbol", "available_at", "sector"]
    with data.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for symbol in ["ADBE", "LBMH"]:
            writer.writerow(
                {
                    "event_date": "2014-12-15",
                    "historical_symbol": symbol,
                    "available_at": "2014-12-15T08:00:00-05:00",
                    "sector": "TECH",
                }
            )
    manifest = _manifest(tmp_path, data)

    with pytest.raises(activation.G5ControlActivationError, match="fewer than three canonical"):
        activation.build_activation_contract(
            source_manifest=manifest,
            activate_dates=["2014-12-15"],
            output_contract=tmp_path / "active-two.json",
            replacement_exclusions_output=tmp_path / "remaining-two.json",
            base_contract=ROOT / "config/metadata_sources.public_progress.json",
            events_path=ROOT / "data/processed/historical_events.csv",
        )
