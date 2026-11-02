from __future__ import annotations

import csv
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import g5_control_acquisition_planner as acquisition
import g5_external_source_queue as external_queue
import g5_external_source_request_compressor as compressor


def _candidates(tmp_path: Path) -> Path:
    path = tmp_path / "candidates.csv"
    path.write_text(
        "event_date,candidate_symbol,latest_acceptable_effective_ts_utc\n"
        "2015-02-17,C1,2015-02-17T19:19:00Z\n"
        "2015-02-18,C1,2015-02-18T19:00:00Z\n"
        "2015-02-18,C2,2015-02-18T19:00:00Z\n",
        encoding="utf-8",
    )
    return path


def test_repeated_symbols_compress_by_lane_without_losing_points(tmp_path: Path):
    queue_dir = tmp_path / "queue"
    summary = external_queue.build(
        candidate_path=_candidates(tmp_path),
        output_dir=queue_dir,
    )
    compressed = compressor.build(
        external_request_path=queue_dir / "g5_external_source_requests.csv",
        output_dir=tmp_path / "compressed",
    )

    assert summary["lane_request_count"] == 12
    assert compressed["date_level_request_count"] == 12
    assert compressed["compressed_lane_symbol_request_count"] == 8
    assert compressed["request_reduction_count"] == 4
    assert compressed["exact_request_point_count_reconciled"] == 12
    assert compressed["compression_ratio"] < 1
    assert compressed["lane_input_counts"] == {
        "analyst": 3,
        "borrow": 3,
        "classification": 3,
        "ownership": 3,
    }
    assert compressed["lane_compressed_counts"] == {
        "analyst": 2,
        "borrow": 2,
        "classification": 2,
        "ownership": 2,
    }
    assert compressed["g5_dates_resolved_change"] == 0
    assert compressed["release_claimed"] is False

    rows = list(
        csv.DictReader(
            (
                tmp_path
                / "compressed/g5_external_source_compressed_requests.csv"
            ).open(encoding="utf-8")
        )
    )
    c1_classification = next(
        row
        for row in rows
        if row["lane"] == "classification"
        and row["candidate_symbol"] == "C1"
    )
    assert c1_classification["required_date_count"] == "2"
    assert c1_classification["first_event_date"] == "2015-02-17"
    assert c1_classification["last_event_date"] == "2015-02-18"
    assert c1_classification["request_points"] == (
        "2015-02-17@2015-02-17T19:19:00Z;"
        "2015-02-18@2015-02-18T19:00:00Z"
    )


def test_compressed_request_ids_are_deterministic(tmp_path: Path):
    queue_dir = tmp_path / "queue"
    external_queue.build(
        candidate_path=_candidates(tmp_path),
        output_dir=queue_dir,
    )
    out1 = tmp_path / "compressed1"
    out2 = tmp_path / "compressed2"
    compressor.build(
        external_request_path=queue_dir / "g5_external_source_requests.csv",
        output_dir=out1,
    )
    compressor.build(
        external_request_path=queue_dir / "g5_external_source_requests.csv",
        output_dir=out2,
    )

    rows1 = list(
        csv.DictReader(
            (out1 / "g5_external_source_compressed_requests.csv").open(
                encoding="utf-8"
            )
        )
    )
    rows2 = list(
        csv.DictReader(
            (out2 / "g5_external_source_compressed_requests.csv").open(
                encoding="utf-8"
            )
        )
    )
    assert [row["request_id"] for row in rows1] == [
        row["request_id"] for row in rows2
    ]
    assert len({row["request_id"] for row in rows1}) == len(rows1)
    assert all(row["request_id"].startswith("G5EXTC-") for row in rows1)


def test_inconsistent_lane_contract_for_same_symbol_fails_closed(tmp_path: Path):
    path = tmp_path / "requests.csv"
    path.write_text(
        "request_id,lane,event_date,candidate_symbol,"
        "latest_acceptable_effective_ts_utc,required_fields,preferred_routes,"
        "cost_profile,status,eligible_g5_evidence,research_use_only\n"
        "R1,ownership,2015-02-17,AAA,2015-02-17T19:00:00Z,"
        "institutional_ownership,ROUTE_A,PUBLIC_OR_AUTHORIZED,SOURCE_REQUIRED,0,1\n"
        "R2,ownership,2015-02-18,AAA,2015-02-18T19:00:00Z,"
        "institutional_ownership,ROUTE_B,PUBLIC_OR_AUTHORIZED,SOURCE_REQUIRED,0,1\n",
        encoding="utf-8",
    )

    with pytest.raises(
        compressor.G5ExternalSourceCompressionError,
        match="inconsistent preferred_routes",
    ):
        compressor.build(
            external_request_path=path,
            output_dir=tmp_path / "out",
        )


def test_duplicate_lane_date_symbol_fails_closed(tmp_path: Path):
    path = tmp_path / "requests.csv"
    path.write_text(
        "request_id,lane,event_date,candidate_symbol,"
        "latest_acceptable_effective_ts_utc,required_fields,preferred_routes,"
        "cost_profile,status,eligible_g5_evidence,research_use_only\n"
        "R1,borrow,2015-02-17,AAA,2015-02-17T19:00:00Z,"
        "borrow_cost,ROUTE_A,AUTHORIZED_LIKELY,SOURCE_REQUIRED,0,1\n"
        "R2,borrow,2015-02-17,AAA,2015-02-17T19:00:00Z,"
        "borrow_cost,ROUTE_A,AUTHORIZED_LIKELY,SOURCE_REQUIRED,0,1\n",
        encoding="utf-8",
    )

    with pytest.raises(
        compressor.G5ExternalSourceCompressionError,
        match="duplicate external lane/date/symbol request",
    ):
        compressor.build(
            external_request_path=path,
            output_dir=tmp_path / "out",
        )


def test_real_primary_control_external_requests_compress_without_scope_loss(
    tmp_path: Path,
):
    control_dir = tmp_path / "controls"
    queue_dir = tmp_path / "external"
    compressed_dir = tmp_path / "compressed"

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
    queue_summary = external_queue.build(
        candidate_path=control_dir / "g5_primary_candidate_symbol_dates.csv",
        output_dir=queue_dir,
    )
    summary = compressor.build(
        external_request_path=queue_dir / "g5_external_source_requests.csv",
        output_dir=compressed_dir,
    )

    assert queue_summary["lane_request_count"] == 864
    assert summary["date_level_request_count"] == 864
    assert summary["compressed_lane_symbol_request_count"] < 864
    assert summary["request_reduction_count"] > 0
    assert summary["exact_request_point_count_reconciled"] == 864
    assert sum(summary["lane_input_counts"].values()) == 864
    assert sum(summary["lane_compressed_counts"].values()) == (
        summary["compressed_lane_symbol_request_count"]
    )
    assert (
        summary["policy"]["exact_event_dates_and_cutoffs_preserved"]
        is True
    )
    assert (
        summary["policy"]["cross_date_metadata_continuity_assumed"]
        is False
    )
    assert summary["g5_dates_resolved_change"] == 0
    assert summary["release_claimed"] is False
