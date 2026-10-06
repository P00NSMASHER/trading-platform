from __future__ import annotations

import csv
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import g5_treated_external_source_request_compressor as compressor
import g5_treated_metadata_requirements as treated


HEADER = (
    "request_id,event_id,lane,event_date,treated_symbol,"
    "latest_acceptable_effective_ts_utc,required_fields,status,"
    "eligible_g5_evidence,research_use_only\n"
)


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_repeated_treated_symbol_compresses_without_losing_event_points(
    tmp_path: Path,
):
    path = _write(
        tmp_path / "treated.csv",
        HEADER
        + "R1,E1,classification,2015-01-02,AAA,2015-01-02T19:00:00Z,"
        "sector;index_bucket,SOURCE_REQUIRED,0,1\n"
        + "R2,E2,classification,2015-01-03,AAA,2015-01-03T18:00:00Z,"
        "sector;index_bucket,SOURCE_REQUIRED,0,1\n"
        + "R3,E1,ownership,2015-01-02,AAA,2015-01-02T19:00:00Z,"
        "institutional_ownership,SOURCE_REQUIRED,0,1\n"
        + "R4,E3,classification,2015-01-03,BBB,2015-01-03T18:00:00Z,"
        "sector;index_bucket,SOURCE_REQUIRED,0,1\n",
    )

    out = tmp_path / "out"
    summary = compressor.build(
        treated_external_request_path=path,
        output_dir=out,
    )

    assert summary["date_level_request_count"] == 4
    assert summary["compressed_lane_symbol_request_count"] == 3
    assert summary["request_reduction_count"] == 1
    assert summary["exact_request_point_count_reconciled"] == 4
    assert summary["g5_dates_resolved_change"] == 0
    assert summary["release_claimed"] is False

    rows = list(
        csv.DictReader(
            (out / "g5_treated_external_compressed_requests.csv").open(
                encoding="utf-8"
            )
        )
    )
    row = next(
        item
        for item in rows
        if item["lane"] == "classification"
        and item["treated_symbol"] == "AAA"
    )
    assert row["required_event_count"] == "2"
    assert row["request_points"] == (
        "E1@2015-01-02@2015-01-02T19:00:00Z;"
        "E2@2015-01-03@2015-01-03T18:00:00Z"
    )
    assert "SEC_SIC" in row["preferred_routes"]
    assert row["cost_profile"] == "MIXED_PUBLIC_AND_AUTHORIZED"


def test_unknown_lane_or_wrong_required_fields_fail_closed(tmp_path: Path):
    unknown = _write(
        tmp_path / "unknown.csv",
        HEADER
        + "R1,E1,unknown,2015-01-02,AAA,2015-01-02T19:00:00Z,"
        "sector,SOURCE_REQUIRED,0,1\n",
    )
    with pytest.raises(
        compressor.G5TreatedExternalCompressionError,
        match="unknown lane",
    ):
        compressor.build(
            treated_external_request_path=unknown,
            output_dir=tmp_path / "out1",
        )

    wrong = _write(
        tmp_path / "wrong.csv",
        HEADER
        + "R2,E2,classification,2015-01-02,AAA,2015-01-02T19:00:00Z,"
        "sector,SOURCE_REQUIRED,0,1\n",
    )
    with pytest.raises(
        compressor.G5TreatedExternalCompressionError,
        match="required_fields disagree",
    ):
        compressor.build(
            treated_external_request_path=wrong,
            output_dir=tmp_path / "out2",
        )


def test_duplicate_event_lane_fails_closed(tmp_path: Path):
    path = _write(
        tmp_path / "duplicate.csv",
        HEADER
        + "R1,E1,borrow,2015-01-02,AAA,2015-01-02T19:00:00Z,"
        "borrow_cost,SOURCE_REQUIRED,0,1\n"
        + "R2,E1,borrow,2015-01-02,AAA,2015-01-02T19:00:00Z,"
        "borrow_cost,SOURCE_REQUIRED,0,1\n",
    )

    with pytest.raises(
        compressor.G5TreatedExternalCompressionError,
        match="duplicate treated event/lane request",
    ):
        compressor.build(
            treated_external_request_path=path,
            output_dir=tmp_path / "out",
        )


def test_real_treated_external_requests_compress_696_to_584(tmp_path: Path):
    treated_dir = tmp_path / "treated"
    compressed_dir = tmp_path / "compressed"

    treated_summary = treated.build(
        events_path=ROOT / "data/processed/historical_events.csv",
        output_dir=treated_dir,
    )
    summary = compressor.build(
        treated_external_request_path=(
            treated_dir / "g5_treated_external_lane_requests.csv"
        ),
        output_dir=compressed_dir,
    )

    assert treated_summary["treated_target_count"] == 174
    assert treated_summary["treated_external_lane_request_count"] == 696
    assert summary["date_level_request_count"] == 696
    assert summary["unique_treated_symbol_count"] == 146
    assert summary["compressed_lane_symbol_request_count"] == 584
    assert summary["request_reduction_count"] == 112
    assert summary["exact_request_point_count_reconciled"] == 696
    assert summary["lane_input_counts"] == {
        "analyst": 174,
        "borrow": 174,
        "classification": 174,
        "ownership": 174,
    }
    assert summary["lane_compressed_counts"] == {
        "analyst": 146,
        "borrow": 146,
        "classification": 146,
        "ownership": 146,
    }
    assert (
        summary["policy"]["exact_event_id_date_and_cutoff_preserved"]
        is True
    )
    assert (
        summary["policy"]["cross_event_metadata_continuity_assumed"]
        is False
    )
    assert summary["g5_dates_resolved_change"] == 0
    assert summary["release_claimed"] is False
