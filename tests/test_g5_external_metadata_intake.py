from __future__ import annotations

import csv
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import g5_control_acquisition_planner as control_plan
import g5_external_metadata_intake as intake
import g5_treated_metadata_requirements as treated_plan


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _control_targets(tmp_path: Path) -> Path:
    path = tmp_path / "control_targets.csv"
    path.write_text(
        "event_date,candidate_symbol,latest_acceptable_effective_ts_utc,"
        "research_use_only\n"
        "2015-01-02,AAA,2015-01-02T16:00:00Z,1\n",
        encoding="utf-8",
    )
    return path


def _treated_targets(tmp_path: Path) -> Path:
    path = tmp_path / "treated_targets.csv"
    path.write_text(
        "event_id,event_date,candidate_symbol,latest_acceptable_effective_ts_utc,"
        "target_kind,eligible_g5_evidence,research_use_only\n"
        "EV1,2015-01-03,BBB,2015-01-03T16:00:00Z,treated,0,1\n",
        encoding="utf-8",
    )
    return path


def _source(
    tmp_path: Path,
    name: str,
    *,
    event_date: str,
    symbol: str,
    fields: dict[str, str],
    effective_ts: str = "2015-01-02T12:00:00Z",
) -> Path:
    path = tmp_path / f"{name}.csv"
    columns = [
        "event_date",
        "symbol",
        "effective_ts_utc",
        *fields,
    ]
    values = [
        event_date,
        symbol,
        effective_ts,
        *fields.values(),
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(columns)
        writer.writerow(values)
    return path


def _manifest(tmp_path: Path, specs: list[dict]) -> Path:
    path = tmp_path / "manifest.json"
    payload = {
        "schema_version": "1",
        "sources": specs,
    }
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _spec(
    path: Path,
    *,
    source_id: str,
    target_kind: str,
    lane: str,
) -> dict:
    return {
        "source_id": source_id,
        "target_kind": target_kind,
        "lane": lane,
        "path": path.name,
        "expected_sha256": _sha256(path),
        "authorization_reference": f"AUTHORIZED-{source_id}",
        "source_name": source_id,
    }


def test_complete_control_and_treated_external_metadata_reconcile(tmp_path: Path):
    control = _control_targets(tmp_path)
    treated = _treated_targets(tmp_path)

    sources = []
    for target_kind, event_date, symbol, effective in [
        ("control", "2015-01-02", "AAA", "2015-01-02T12:00:00Z"),
        ("treated", "2015-01-03", "BBB", "2015-01-03T12:00:00Z"),
    ]:
        lane_fields = {
            "classification": {"sector": "Tech", "index_bucket": "SP500"},
            "ownership": {"institutional_ownership": "0.61"},
            "analyst": {"analyst_coverage": "12"},
            "borrow": {"borrow_cost": "0.01"},
        }
        for lane, fields in lane_fields.items():
            source_id = f"{target_kind}-{lane}"
            path = _source(
                tmp_path,
                source_id,
                event_date=event_date,
                symbol=symbol,
                fields=fields,
                effective_ts=effective,
            )
            sources.append(
                _spec(
                    path,
                    source_id=source_id,
                    target_kind=target_kind,
                    lane=lane,
                )
            )

    manifest = _manifest(tmp_path, sources)
    out = tmp_path / "out"
    summary = intake.build(
        control_targets_path=control,
        treated_targets_path=treated,
        source_manifest_path=manifest,
        output_dir=out,
    )

    assert summary["control_target_count"] == 1
    assert summary["treated_target_count"] == 1
    assert summary["total_target_count"] == 2
    assert summary["external_field_requirement_count"] == 10
    assert summary["observed_nonconflicted_target_field_count"] == 10
    assert summary["missing_target_field_count"] == 0
    assert summary["normalized_source_count"] == 8
    assert summary["normalized_row_count"] == 8
    assert summary["externally_complete_control_target_count"] == 1
    assert summary["externally_complete_treated_target_count"] == 1
    assert summary["externally_complete_target_count"] == 2
    assert summary["external_gap_target_count"] == 0
    assert summary["all_external_metadata_complete"] is True
    assert summary["canonical_g5_readiness_changed"] is False
    assert summary["release_claimed"] is False

    combined = list(
        csv.DictReader(
            (out / "g5_external_metadata_normalized.csv").open(
                encoding="utf-8"
            )
        )
    )
    assert len(combined) == 8
    assert {row["target_kind"] for row in combined} == {
        "control",
        "treated",
    }
    treated_rows = [row for row in combined if row["target_kind"] == "treated"]
    assert treated_rows
    assert {row["event_id"] for row in treated_rows} == {"EV1"}


def test_partial_external_intake_reports_exact_missing_fields(tmp_path: Path):
    control = _control_targets(tmp_path)
    treated = _treated_targets(tmp_path)
    source = _source(
        tmp_path,
        "control-classification",
        event_date="2015-01-02",
        symbol="AAA",
        fields={"sector": "Tech", "index_bucket": "SP500"},
    )
    manifest = _manifest(
        tmp_path,
        [
            _spec(
                source,
                source_id="control-classification",
                target_kind="control",
                lane="classification",
            )
        ],
    )

    out = tmp_path / "out"
    summary = intake.build(
        control_targets_path=control,
        treated_targets_path=treated,
        source_manifest_path=manifest,
        output_dir=out,
    )

    assert summary["external_field_requirement_count"] == 10
    assert summary["observed_nonconflicted_target_field_count"] == 2
    assert summary["missing_target_field_count"] == 8
    assert summary["external_gap_target_count"] == 2
    assert summary["all_external_metadata_complete"] is False
    assert summary["missing_field_counts"] == {
        "analyst_coverage": 2,
        "borrow_cost": 2,
        "index_bucket": 1,
        "institutional_ownership": 2,
        "sector": 1,
    }


def test_equal_timestamp_external_conflict_fails_target_closed(tmp_path: Path):
    control = _control_targets(tmp_path)
    treated = _treated_targets(tmp_path)
    first = _source(
        tmp_path,
        "class-a",
        event_date="2015-01-02",
        symbol="AAA",
        fields={"sector": "Tech", "index_bucket": "SP500"},
    )
    second = _source(
        tmp_path,
        "class-b",
        event_date="2015-01-02",
        symbol="AAA",
        fields={"sector": "Health", "index_bucket": "SP500"},
    )
    manifest = _manifest(
        tmp_path,
        [
            _spec(
                first,
                source_id="class-a",
                target_kind="control",
                lane="classification",
            ),
            _spec(
                second,
                source_id="class-b",
                target_kind="control",
                lane="classification",
            ),
        ],
    )

    out = tmp_path / "out"
    summary = intake.build(
        control_targets_path=control,
        treated_targets_path=treated,
        source_manifest_path=manifest,
        output_dir=out,
    )
    assert summary["conflict_field_counts"] == {"sector": 1}
    assert summary["externally_complete_control_target_count"] == 0
    assert summary["all_external_metadata_complete"] is False

    gaps = list(
        csv.DictReader(
            (out / "g5_external_metadata_gaps.csv").open(
                encoding="utf-8"
            )
        )
    )
    control_gap = next(
        row for row in gaps
        if row["target_kind"] == "control"
    )
    assert control_gap["conflicted_fields"] == "sector"


def test_real_scope_is_390_targets_and_1950_external_fields(tmp_path: Path):
    control_dir = tmp_path / "controls"
    treated_dir = tmp_path / "treated"
    control_plan.build(
        events_path=ROOT / "data/processed/historical_events.csv",
        requirements_path=(
            ROOT / "data/processed/coverage_plan_real/source_date_requirements.csv"
        ),
        planning_universe_path=(
            ROOT / "data/raw/hacked_earnings_jfe/SampleFirms.csv"
        ),
        output_dir=control_dir,
    )
    treated_plan.build(
        events_path=ROOT / "data/processed/historical_events.csv",
        output_dir=treated_dir,
    )

    control_targets = (
        control_dir / "g5_primary_candidate_symbol_dates.csv"
    )
    treated_targets = treated_dir / "g5_treated_targets.csv"

    with control_targets.open(encoding="utf-8", newline="") as handle:
        first = next(csv.DictReader(handle))
    source = _source(
        tmp_path,
        "real-scope-probe",
        event_date=first["event_date"],
        symbol=first["candidate_symbol"],
        fields={"sector": "PROBE", "index_bucket": "PROBE"},
        effective_ts=first["latest_acceptable_effective_ts_utc"],
    )
    manifest = _manifest(
        tmp_path,
        [
            _spec(
                source,
                source_id="real-scope-probe",
                target_kind="control",
                lane="classification",
            )
        ],
    )

    summary = intake.build(
        control_targets_path=control_targets,
        treated_targets_path=treated_targets,
        source_manifest_path=manifest,
        output_dir=tmp_path / "intake",
    )

    assert summary["control_target_count"] == 216
    assert summary["treated_target_count"] == 174
    assert summary["total_target_count"] == 390
    assert summary["external_field_count_per_target"] == 5
    assert summary["external_field_requirement_count"] == 1950
    assert summary["observed_nonconflicted_target_field_count"] == 2
    assert summary["missing_target_field_count"] == 1948
    assert summary["external_gap_target_count"] == 390
    assert summary["all_external_metadata_complete"] is False
    assert summary["canonical_g5_readiness_changed"] is False
    assert summary["canonical_g5_dates_resolved_change"] == 0
    assert summary["release_claimed"] is False
