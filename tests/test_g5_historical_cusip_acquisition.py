from __future__ import annotations

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import g5_control_acquisition_planner as controls
import g5_external_acquisition_packet as packet
import g5_historical_cusip_acquisition as cusip


def _real_targets(tmp_path: Path) -> tuple[Path, Path]:
    control_dir = tmp_path / "controls"
    packet_dir = tmp_path / "packet"
    controls.build(
        events_path=ROOT / "data/processed/historical_events.csv",
        requirements_path=(
            ROOT / "data/processed/coverage_plan_real/source_date_requirements.csv"
        ),
        planning_universe_path=ROOT / "data/raw/hacked_earnings_jfe/SampleFirms.csv",
        output_dir=control_dir,
    )
    packet.build(
        control_candidates_path=control_dir / "g5_primary_candidate_symbol_dates.csv",
        events_path=ROOT / "data/processed/historical_events.csv",
        output_dir=packet_dir,
    )
    return (
        packet_dir / "g5_control_external_acquisition_targets.csv",
        packet_dir / "g5_treated_external_acquisition_targets.csv",
    )


def test_real_g5_cusip_queue_preserves_control_and_treated_targets(tmp_path: Path):
    control, treated = _real_targets(tmp_path)
    out = tmp_path / "cusip"
    summary = cusip.build(
        control_targets_path=control,
        treated_targets_path=treated,
        output_dir=out,
    )
    assert summary["request_count_by_target_kind"]["control"] > 0
    assert summary["request_count_by_target_kind"]["treated"] > 0
    assert summary["request_count"] == (
        summary["request_count_by_target_kind"]["control"]
        + summary["request_count_by_target_kind"]["treated"]
    )
    assert summary["canonical_g5_dates_resolved_change"] == 0
    rows = list(
        csv.DictReader(
            (out / "g5_historical_cusip_acquisition_queue.csv").open(
                encoding="utf-8"
            )
        )
    )
    assert len(rows) == summary["request_count"]
    assert len({row["request_id"] for row in rows}) == len(rows)
    assert all(row["required_event_dates"] for row in rows)
    assert all(row["status"] == "HISTORICAL_CUSIP_EVIDENCE_REQUIRED" for row in rows)


def test_queue_compresses_same_symbol_within_target_kind(tmp_path: Path):
    control = tmp_path / "control.csv"
    control.write_text(
        "event_date,candidate_symbol\n"
        "2015-01-01,AAA\n"
        "2015-02-01,AAA\n",
        encoding="utf-8",
    )
    treated = tmp_path / "treated.csv"
    treated.write_text(
        "event_date,historical_symbol\n"
        "2015-01-01,AAA\n",
        encoding="utf-8",
    )
    out = tmp_path / "out"
    summary = cusip.build(
        control_targets_path=control,
        treated_targets_path=treated,
        output_dir=out,
    )
    assert summary["request_count"] == 2
    rows = list(
        csv.DictReader(
            (out / "g5_historical_cusip_acquisition_queue.csv").open(
                encoding="utf-8"
            )
        )
    )
    control_row = next(row for row in rows if row["target_kind"] == "control")
    assert control_row["required_event_dates"] == "2015-01-01;2015-02-01"


def test_reviewed_cusip_requires_exact_nine_characters_and_date_coverage(tmp_path: Path):
    queue = tmp_path / "queue.csv"
    queue.write_text(
        "target_kind,historical_symbol,required_event_dates\n"
        "treated,AAA,2013-01-01;2015-01-01\n",
        encoding="utf-8",
    )
    reviewed = tmp_path / "reviewed.csv"
    reviewed.write_text(
        "target_kind,historical_symbol,cusip,valid_from,valid_through,"
        "source_reference,evidence_effective_at,review_status,research_use_only\n"
        "treated,AAA,12345678,2010-01-01,2016-01-01,SEC,"
        "2016-01-02T00:00:00Z,EXPLICIT_HISTORICAL_CUSIP_VERIFIED,1\n",
        encoding="utf-8",
    )
    try:
        cusip.stage_reviewed(
            acquisition_queue_path=queue,
            reviewed_evidence_path=reviewed,
            output_path=tmp_path / "out.csv",
        )
    except cusip.G5HistoricalCusipError as exc:
        assert "exactly 9" in str(exc)
    else:
        raise AssertionError("expected invalid CUSIP failure")

    reviewed.write_text(
        "target_kind,historical_symbol,cusip,valid_from,valid_through,"
        "source_reference,evidence_effective_at,review_status,research_use_only\n"
        "treated,AAA,123456789,2014-01-01,2016-01-01,SEC,"
        "2016-01-02T00:00:00Z,EXPLICIT_HISTORICAL_CUSIP_VERIFIED,1\n",
        encoding="utf-8",
    )
    try:
        cusip.stage_reviewed(
            acquisition_queue_path=queue,
            reviewed_evidence_path=reviewed,
            output_path=tmp_path / "out.csv",
        )
    except cusip.G5HistoricalCusipError as exc:
        assert "misses required dates" in str(exc)
    else:
        raise AssertionError("expected date coverage failure")


def test_unreviewed_or_fuzzy_cusip_cannot_stage(tmp_path: Path):
    queue = tmp_path / "queue.csv"
    queue.write_text(
        "target_kind,historical_symbol,required_event_dates\n"
        "control,AAA,2015-01-01\n",
        encoding="utf-8",
    )
    reviewed = tmp_path / "reviewed.csv"
    reviewed.write_text(
        "target_kind,historical_symbol,cusip,valid_from,valid_through,"
        "source_reference,evidence_effective_at,review_status,research_use_only\n"
        "control,AAA,123456789,2010-01-01,2020-01-01,ISSUER_NAME_GUESS,"
        "2026-01-01T00:00:00Z,FUZZY_NAME_MATCH,1\n",
        encoding="utf-8",
    )
    try:
        cusip.stage_reviewed(
            acquisition_queue_path=queue,
            reviewed_evidence_path=reviewed,
            output_path=tmp_path / "out.csv",
        )
    except cusip.G5HistoricalCusipError as exc:
        assert "review_status is not closing-authorized" in str(exc)
    else:
        raise AssertionError("expected review-status failure")


def test_explicit_historical_cusip_stages(tmp_path: Path):
    queue = tmp_path / "queue.csv"
    queue.write_text(
        "target_kind,historical_symbol,required_event_dates\n"
        "treated,AAA,2015-01-01\n",
        encoding="utf-8",
    )
    reviewed = tmp_path / "reviewed.csv"
    reviewed.write_text(
        "target_kind,historical_symbol,cusip,valid_from,valid_through,"
        "source_reference,evidence_effective_at,review_status,research_use_only\n"
        "treated,AAA,123456789,2010-01-01,2020-01-01,AUTHORIZED_MASTER,"
        "2020-01-02T00:00:00Z,EXPLICIT_HISTORICAL_CUSIP_VERIFIED,1\n",
        encoding="utf-8",
    )
    out = tmp_path / "out.csv"
    summary = cusip.stage_reviewed(
        acquisition_queue_path=queue,
        reviewed_evidence_path=reviewed,
        output_path=out,
    )
    assert summary["staged_verified_request_count"] == 1
    assert summary["remaining_request_count"] == 0
    rows = list(csv.DictReader(out.open(encoding="utf-8")))
    assert rows[0]["cusip"] == "123456789"
