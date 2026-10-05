from __future__ import annotations

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import g5_control_acquisition_planner as acquisition
import g5_external_master_acquisition as master


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_small_control_and_treated_queue_unifies_all_four_lanes(tmp_path: Path):
    candidates = _write(
        tmp_path / "candidates.csv",
        "event_date,candidate_symbol,latest_acceptable_effective_ts_utc\n"
        "2015-01-02,AAA,2015-01-02T15:00:00Z\n",
    )
    events = _write(
        tmp_path / "events.csv",
        "event_id,historical_symbol,first_documented_illicit_trade_ts\n"
        "E1,BBB,2015-01-02T14:30:00-05:00\n",
    )

    summary = master.build(
        control_candidates_path=candidates,
        events_path=events,
        output_dir=tmp_path / "out",
    )

    assert summary["control_target_count"] == 1
    assert summary["treated_target_count"] == 1
    assert summary["total_matching_target_count"] == 2
    assert summary["control_lane_request_count"] == 4
    assert summary["treated_lane_request_count"] == 4
    assert summary["total_lane_request_count"] == 8
    assert summary["external_field_requirement_count"] == 10
    assert summary["lane_counts"] == {
        "analyst": 2,
        "borrow": 2,
        "classification": 2,
        "ownership": 2,
    }
    assert summary["lane_field_requirement_counts"] == {
        "analyst": 2,
        "borrow": 2,
        "classification": 4,
        "ownership": 2,
    }
    assert summary["policy"]["request_rows_are_g5_evidence"] is False
    assert summary["policy"]["purchase_authorized"] is False
    assert summary["policy"]["data_fetch_performed"] is False
    assert summary["g5_dates_resolved_change"] == 0
    assert summary["release_claimed"] is False

    rows = list(
        csv.DictReader(
            (tmp_path / "out" / "g5_external_master_requests.csv").open(
                encoding="utf-8"
            )
        )
    )
    assert len(rows) == 8
    assert {row["target_kind"] for row in rows} == {"control", "treated"}
    assert {row["lane"] for row in rows} == {
        "classification",
        "ownership",
        "analyst",
        "borrow",
    }
    assert all(row["eligible_g5_evidence"] == "0" for row in rows)
    assert all(row["research_use_only"] == "1" for row in rows)


def test_real_external_master_queue_locks_390_targets_and_1950_fields(tmp_path: Path):
    control_dir = tmp_path / "controls"
    acquisition.build(
        events_path=ROOT / "data/processed/historical_events.csv",
        requirements_path=(
            ROOT / "data/processed/coverage_plan_real/source_date_requirements.csv"
        ),
        planning_universe_path=(
            ROOT / "data/raw/hacked_earnings_jfe/SampleFirms.csv"
        ),
        output_dir=control_dir,
    )

    summary = master.build(
        control_candidates_path=(
            control_dir / "g5_primary_candidate_symbol_dates.csv"
        ),
        events_path=ROOT / "data/processed/historical_events.csv",
        output_dir=tmp_path / "master",
    )

    assert summary["control_target_count"] == 216
    assert summary["treated_target_count"] == 174
    assert summary["total_matching_target_count"] == 390
    assert summary["control_lane_request_count"] == 864
    assert summary["treated_lane_request_count"] == 696
    assert summary["total_lane_request_count"] == 1560
    assert summary["external_field_requirement_count"] == 1950
    assert summary["lane_counts"] == {
        "analyst": 390,
        "borrow": 390,
        "classification": 390,
        "ownership": 390,
    }
    assert summary["lane_field_requirement_counts"] == {
        "analyst": 390,
        "borrow": 390,
        "classification": 780,
        "ownership": 390,
    }
    assert summary["policy"]["source_hash_required_before_intake"] is True
    assert summary["policy"]["authorization_reference_required_before_intake"] is True
    assert (
        summary["policy"]["effective_timestamp_must_not_exceed_target_cutoff"]
        is True
    )
    assert summary["policy"]["retrospective_or_post_event_values_may_not_close_g5"] is True
    assert summary["policy"]["request_rows_are_g5_evidence"] is False
    assert summary["g5_dates_resolved_change"] == 0
    assert summary["release_claimed"] is False


def test_control_and_treated_request_ids_are_globally_unique(tmp_path: Path):
    candidates = _write(
        tmp_path / "candidates.csv",
        "event_date,candidate_symbol,latest_acceptable_effective_ts_utc\n"
        "2015-01-02,AAA,2015-01-02T15:00:00Z\n",
    )
    events = _write(
        tmp_path / "events.csv",
        "event_id,historical_symbol,first_documented_illicit_trade_ts\n"
        "E1,BBB,2015-01-02T14:30:00-05:00\n",
    )
    master.build(
        control_candidates_path=candidates,
        events_path=events,
        output_dir=tmp_path / "out",
    )
    rows = list(
        csv.DictReader(
            (tmp_path / "out" / "g5_external_master_requests.csv").open(
                encoding="utf-8"
            )
        )
    )
    ids = [row["request_id"] for row in rows]
    assert len(ids) == len(set(ids))
