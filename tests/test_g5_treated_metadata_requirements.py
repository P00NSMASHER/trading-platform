from __future__ import annotations

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import g5_treated_metadata_requirements as treated
from g5_control_acquisition_planner import DERIVED_FIELDS, EXTERNAL_FIELDS
from metadata_resolver import CONTROL_COVARIATES


def test_real_treated_requirement_counts_are_explicit(tmp_path: Path):
    summary = treated.build(
        events_path=ROOT / "data/processed/historical_events.csv",
        output_dir=tmp_path,
    )

    assert summary["event_count"] == 174
    assert summary["event_date_count"] == 72
    assert summary["required_field_count_per_event"] == len(CONTROL_COVARIATES) == 13
    assert summary["external_field_count_per_event"] == len(EXTERNAL_FIELDS) == 5
    assert summary["derived_field_count_per_event"] == len(DERIVED_FIELDS) == 8
    assert summary["treated_field_requirement_count"] == 174 * 13
    assert summary["treated_external_field_requirement_count"] == 174 * 5
    assert summary["treated_derived_field_requirement_count"] == 174 * 8
    assert summary["treated_external_lane_request_count"] == 174 * 4
    assert summary["g5_dates_resolved_change"] == 0
    assert summary["release_claimed"] is False


def test_real_requirements_preserve_event_specific_cutoffs(tmp_path: Path):
    treated.build(
        events_path=ROOT / "data/processed/historical_events.csv",
        output_dir=tmp_path,
    )

    fields = list(
        csv.DictReader(
            (tmp_path / "g5_treated_field_requirements.csv").open(encoding="utf-8")
        )
    )
    hon = [
        row
        for row in fields
        if row["event_id"] == "HEJFE-8D40B9782E1E6F33"
    ]
    assert len(hon) == 13
    assert {row["treated_symbol"] for row in hon} == {"HON"}
    assert {row["event_date"] for row in hon} == {"2012-01-26"}
    assert {
        row["latest_acceptable_effective_ts_utc"]
        for row in hon
    } == {"2012-01-26T20:53:00Z"}
    assert {row["eligible_g5_evidence"] for row in hon} == {"0"}
    assert {row["research_use_only"] for row in hon} == {"1"}


def test_each_event_gets_four_external_lane_requests(tmp_path: Path):
    treated.build(
        events_path=ROOT / "data/processed/historical_events.csv",
        output_dir=tmp_path,
    )

    rows = list(
        csv.DictReader(
            (tmp_path / "g5_treated_external_lane_requests.csv").open(encoding="utf-8")
        )
    )
    by_event = {}
    for row in rows:
        by_event.setdefault(row["event_id"], []).append(row)

    assert len(by_event) == 174
    assert all(len(event_rows) == 4 for event_rows in by_event.values())
    assert all(
        {row["lane"] for row in event_rows}
        == {"classification", "ownership", "analyst", "borrow"}
        for event_rows in by_event.values()
    )
    assert len({row["request_id"] for row in rows}) == len(rows)


def test_requirements_cover_exact_control_contract(tmp_path: Path):
    treated.build(
        events_path=ROOT / "data/processed/historical_events.csv",
        output_dir=tmp_path,
    )

    rows = list(
        csv.DictReader(
            (tmp_path / "g5_treated_field_requirements.csv").open(encoding="utf-8")
        )
    )
    first_event_id = rows[0]["event_id"]
    first = [row for row in rows if row["event_id"] == first_event_id]
    assert {row["field_name"] for row in first} == set(CONTROL_COVARIATES)
    assert {
        row["field_name"] for row in first if row["field_class"] == "external"
    } == EXTERNAL_FIELDS
    assert {
        row["field_name"] for row in first if row["field_class"] == "derived"
    } == DERIVED_FIELDS
