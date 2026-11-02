from __future__ import annotations

import csv
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import g5_control_acquisition_planner as control_plan
import g5_external_acquisition_packet as packet
import g5_external_source_queue as control_external
import g5_treated_metadata_requirements as treated_plan


CONTROL_HEADER = (
    "request_id,lane,event_date,candidate_symbol,latest_acceptable_effective_ts_utc,"
    "required_fields,preferred_routes,cost_profile,status,eligible_g5_evidence,"
    "research_use_only\n"
)
TREATED_HEADER = (
    "request_id,event_id,lane,event_date,treated_symbol,"
    "latest_acceptable_effective_ts_utc,required_fields,status,"
    "eligible_g5_evidence,research_use_only\n"
)


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def _control_rows(tmp_path: Path, *, bad_routes: bool = False) -> Path:
    rows = []
    for lane, spec in control_external.LANES.items():
        routes = ";".join(spec["preferred_routes"])
        if bad_routes and lane == "classification":
            routes = "WRONG"
        rows.append(
            ",".join(
                [
                    f"C-{lane}",
                    lane,
                    "2015-01-02",
                    "AAA",
                    "2015-01-02T20:59:59Z",
                    ";".join(spec["fields"]),
                    routes,
                    spec["cost_profile"],
                    "SOURCE_REQUIRED",
                    "0",
                    "1",
                ]
            )
        )
    return _write(tmp_path / "controls.csv", CONTROL_HEADER + "\n".join(rows) + "\n")


def _treated_rows(tmp_path: Path, *, symbol: str = "AAA") -> Path:
    rows = []
    for lane, fields in treated_plan.EXTERNAL_LANES.items():
        rows.append(
            ",".join(
                [
                    f"T-{lane}",
                    "EV1",
                    lane,
                    "2015-01-03",
                    symbol,
                    "2015-01-03T20:59:59Z",
                    ";".join(fields),
                    "SOURCE_REQUIRED",
                    "0",
                    "1",
                ]
            )
        )
    return _write(tmp_path / "treated.csv", TREATED_HEADER + "\n".join(rows) + "\n")


def test_packet_unifies_control_and_treated_requests_without_promoting_values(
    tmp_path: Path,
):
    out = tmp_path / "out"
    summary = packet.build(
        control_requests_path=_control_rows(tmp_path),
        treated_requests_path=_treated_rows(tmp_path),
        output_dir=out,
    )

    assert summary["control_target_count"] == 1
    assert summary["treated_target_count"] == 1
    assert summary["total_target_count"] == 2
    assert summary["control_lane_request_count"] == 4
    assert summary["treated_lane_request_count"] == 4
    assert summary["total_lane_request_count"] == 8
    assert summary["external_field_requirement_count"] == 10
    assert summary["lane_counts"] == {
        "classification": 2,
        "ownership": 2,
        "analyst": 2,
        "borrow": 2,
    }
    assert summary["grouped_lane_symbol_batch_count"] == 4
    assert summary["g5_dates_resolved_change"] == 0
    assert summary["release_claimed"] is False
    assert summary["policy"]["request_rows_are_g5_evidence"] is False
    assert summary["policy"]["every_target_cutoff_is_preserved"] is True

    batches = list(
        csv.DictReader(
            (out / "g5_external_acquisition_batches.csv").open(encoding="utf-8")
        )
    )
    assert len(batches) == 4
    assert all(row["target_request_count"] == "2" for row in batches)
    assert all("CONTROL:-:2015-01-02:" in row["request_scope"] for row in batches)
    assert all("TREATED:EV1:2015-01-03:" in row["request_scope"] for row in batches)


def test_control_route_drift_fails_closed(tmp_path: Path):
    with pytest.raises(
        packet.G5ExternalAcquisitionPacketError,
        match="preferred_routes disagree",
    ):
        packet.build(
            control_requests_path=_control_rows(tmp_path, bad_routes=True),
            treated_requests_path=_treated_rows(tmp_path),
            output_dir=tmp_path / "out",
        )


def test_batching_does_not_require_same_symbol_across_target_types(tmp_path: Path):
    out = tmp_path / "out"
    summary = packet.build(
        control_requests_path=_control_rows(tmp_path),
        treated_requests_path=_treated_rows(tmp_path, symbol="BBB"),
        output_dir=out,
    )
    assert summary["total_lane_request_count"] == 8
    assert summary["grouped_lane_symbol_batch_count"] == 8


def test_real_packet_conserves_complete_g5_external_workload(tmp_path: Path):
    control_dir = tmp_path / "controls"
    control_external_dir = tmp_path / "control_external"
    treated_dir = tmp_path / "treated"
    packet_dir = tmp_path / "packet"

    control_plan.build(
        events_path=ROOT / "data/processed/historical_events.csv",
        requirements_path=(
            ROOT / "data/processed/coverage_plan_real/source_date_requirements.csv"
        ),
        planning_universe_path=ROOT / "data/raw/hacked_earnings_jfe/SampleFirms.csv",
        output_dir=control_dir,
    )
    control_summary = control_external.build(
        candidate_path=control_dir / "g5_primary_candidate_symbol_dates.csv",
        output_dir=control_external_dir,
    )
    treated_summary = treated_plan.build(
        events_path=ROOT / "data/processed/historical_events.csv",
        output_dir=treated_dir,
    )
    summary = packet.build(
        control_requests_path=(
            control_external_dir / "g5_external_source_requests.csv"
        ),
        treated_requests_path=(
            treated_dir / "g5_treated_external_lane_requests.csv"
        ),
        output_dir=packet_dir,
    )

    assert summary["control_target_count"] == 216
    assert summary["treated_target_count"] == 174
    assert summary["total_target_count"] == 390
    assert summary["control_lane_request_count"] == 864
    assert summary["treated_lane_request_count"] == 696
    assert summary["total_lane_request_count"] == 1560
    assert summary["external_field_requirement_count"] == 1950
    assert summary["lane_counts"] == {
        "classification": 390,
        "ownership": 390,
        "analyst": 390,
        "borrow": 390,
    }
    assert summary["control_lane_request_count"] == control_summary["lane_request_count"]
    assert summary["treated_lane_request_count"] == (
        treated_summary["treated_external_lane_request_count"]
    )
    assert 0 < summary["grouped_lane_symbol_batch_count"] <= 1560
    assert summary["g5_dates_resolved_change"] == 0
    assert summary["release_claimed"] is False
