from __future__ import annotations

import csv
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import g5_control_acquisition_planner as acquisition
import g5_control_history_requirements as history
import g5_control_identity_interval_requests as intervals
import g5_control_identity_requirements as identity
import g5_control_identity_stocknames_handoff as direct_handoff
import g5_control_identity_stocknames_lead_expansion as expansion


QUEUE_HEADER = (
    "historical_symbol,trade_date,roles,identity_status,canonical_g2_overlap,"
    "canonical_permno,canonical_gvkey,samplefirms_permno,samplefirms_gvkey,"
    "samplefirms_exact_mapping_status,required_evidence,research_use_only\n"
)

INTERVAL_HEADER = (
    "request_id,historical_symbol,required_date_count,first_required_date,"
    "last_required_date,required_dates,source_statuses,canonical_permno_hint,"
    "samplefirms_permno_hint,primary_lane,secondary_lane,status,research_use_only\n"
)


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_symbol_level_lead_routes_no_hint_date_without_promoting_identity(tmp_path: Path):
    queue = _write(
        tmp_path / "queue.csv",
        QUEUE_HEADER
        + "AAA,2015-01-02,event_point,OVERLAPS_CANONICAL_G2_IDENTITY_QUEUE,"
        "CANONICAL_G2_UNVERIFIED,11111,1,,,NO_EXACT_DATE_MAPPING,"
        "DATED_STABLE_ID_CROSSWALK,1\n"
        + "AAA,2015-01-03,prior_close,NEW_G5_IDENTITY_EVIDENCE_REQUIRED,"
        "NONE,,,,,NO_EXACT_DATE_MAPPING,DATED_STABLE_ID_CROSSWALK,1\n"
        + "BBB,2015-01-04,event_point,NEW_G5_IDENTITY_EVIDENCE_REQUIRED,"
        "NONE,,,,,NO_EXACT_DATE_MAPPING,DATED_STABLE_ID_CROSSWALK,1\n",
    )
    interval = _write(
        tmp_path / "interval.csv",
        INTERVAL_HEADER
        + "G5ID-A,AAA,2,2015-01-02,2015-01-03,2015-01-02;2015-01-03,"
        "NEW_G5_IDENTITY_EVIDENCE_REQUIRED;OVERLAPS_CANONICAL_G2_IDENTITY_QUEUE,"
        "11111,,LICENSED_STABLE_ID_MASTER,AUTHORIZED_MARKET_SECURITY_MASTER,"
        "INTERVAL_EVIDENCE_REQUIRED,1\n"
        + "G5ID-B,BBB,1,2015-01-04,2015-01-04,2015-01-04,"
        "NEW_G5_IDENTITY_EVIDENCE_REQUIRED,,,LICENSED_STABLE_ID_MASTER,"
        "AUTHORIZED_MARKET_SECURITY_MASTER,INTERVAL_EVIDENCE_REQUIRED,1\n",
    )

    out = tmp_path / "out"
    summary = expansion.build(
        identity_queue_path=queue,
        interval_requests_path=interval,
        output_dir=out,
    )

    assert summary["identity_queue_count"] == 3
    assert summary["exact_date_ready_request_count"] == 1
    assert summary["symbol_level_lead_added_request_count"] == 1
    assert summary["expanded_stocknames_ready_request_count"] == 2
    assert summary["residual_symbol_discovery_request_count"] == 1
    assert summary["g5_dates_resolved_change"] == 0
    assert summary["release_claimed"] is False
    assert (
        summary["policy"]["symbol_level_permno_is_identity_evidence"]
        is False
    )
    assert summary["policy"]["cross_date_identity_continuity_assumed"] is False

    ready = list(
        csv.DictReader(
            (out / "g5_control_identity_stocknames_expanded_ready_queue.csv").open(
                encoding="utf-8"
            )
        )
    )
    by_date = {row["trade_date"]: row for row in ready}
    assert by_date["2015-01-02"]["hint_source"] == "CANONICAL_G2_PERMNO"
    assert by_date["2015-01-03"]["permno"] == "11111"
    assert by_date["2015-01-03"]["hint_source"] == (
        "SYMBOL_LEVEL_CANONICAL_PERMNO_ACQUISITION_LEAD"
    )


def test_symbol_level_samplefirms_lead_is_acquisition_only(tmp_path: Path):
    queue = _write(
        tmp_path / "queue.csv",
        QUEUE_HEADER
        + "AAA,2015-01-02,event_point,PUBLIC_EXACT_MAPPING_AVAILABLE_REQUIRES_ADMISSION,"
        "NONE,,,22222,2,UNIQUE_EXACT_DATE_MAPPING_AVAILABLE,"
        "ADMISSIBLE_DATE_SPECIFIC_STABLE_ID_EVIDENCE,1\n"
        + "AAA,2015-01-03,prior_close,NEW_G5_IDENTITY_EVIDENCE_REQUIRED,"
        "NONE,,,,,NO_EXACT_DATE_MAPPING,DATED_STABLE_ID_CROSSWALK,1\n",
    )
    interval = _write(
        tmp_path / "interval.csv",
        INTERVAL_HEADER
        + "G5ID-A,AAA,2,2015-01-02,2015-01-03,2015-01-02;2015-01-03,"
        "NEW_G5_IDENTITY_EVIDENCE_REQUIRED;"
        "PUBLIC_EXACT_MAPPING_AVAILABLE_REQUIRES_ADMISSION,,22222,"
        "LICENSED_STABLE_ID_MASTER,AUTHORIZED_MARKET_SECURITY_MASTER,"
        "INTERVAL_EVIDENCE_REQUIRED,1\n",
    )

    summary = expansion.build(
        identity_queue_path=queue,
        interval_requests_path=interval,
        output_dir=tmp_path / "out",
    )
    assert summary["symbol_level_samplefirms_lead_added_request_count"] == 1
    assert summary["residual_symbol_discovery_request_count"] == 0
    assert (
        summary["policy"]["authorized_stocknames_validation_still_required"]
        is True
    )


def test_interval_scope_must_exactly_match_date_level_queue(tmp_path: Path):
    queue = _write(
        tmp_path / "queue.csv",
        QUEUE_HEADER
        + "AAA,2015-01-02,event_point,NEW_G5_IDENTITY_EVIDENCE_REQUIRED,"
        "NONE,,,,,NO_EXACT_DATE_MAPPING,DATED_STABLE_ID_CROSSWALK,1\n",
    )
    interval = _write(
        tmp_path / "interval.csv",
        INTERVAL_HEADER
        + "G5ID-A,AAA,1,2015-01-03,2015-01-03,2015-01-03,"
        "NEW_G5_IDENTITY_EVIDENCE_REQUIRED,,,LICENSED_STABLE_ID_MASTER,"
        "AUTHORIZED_MARKET_SECURITY_MASTER,INTERVAL_EVIDENCE_REQUIRED,1\n",
    )
    with pytest.raises(ValueError, match="scope mismatch"):
        expansion.build(
            identity_queue_path=queue,
            interval_requests_path=interval,
            output_dir=tmp_path / "out",
        )


def test_date_level_and_symbol_level_hint_conflict_fails_closed(tmp_path: Path):
    queue = _write(
        tmp_path / "queue.csv",
        QUEUE_HEADER
        + "AAA,2015-01-02,event_point,OVERLAPS_CANONICAL_G2_IDENTITY_QUEUE,"
        "CANONICAL_G2_UNVERIFIED,11111,1,,,NO_EXACT_DATE_MAPPING,"
        "DATED_STABLE_ID_CROSSWALK,1\n",
    )
    interval = _write(
        tmp_path / "interval.csv",
        INTERVAL_HEADER
        + "G5ID-A,AAA,1,2015-01-02,2015-01-02,2015-01-02,"
        "OVERLAPS_CANONICAL_G2_IDENTITY_QUEUE,22222,,"
        "LICENSED_STABLE_ID_MASTER,AUTHORIZED_MARKET_SECURITY_MASTER,"
        "INTERVAL_EVIDENCE_REQUIRED,1\n",
    )
    with pytest.raises(ValueError, match="date/symbol-level PERMNO hint conflict"):
        expansion.build(
            identity_queue_path=queue,
            interval_requests_path=interval,
            output_dir=tmp_path / "out",
        )


def _build_real(tmp_path: Path):
    control_dir = tmp_path / "controls"
    history_dir = tmp_path / "history"
    identity_dir = tmp_path / "identity"
    interval_dir = tmp_path / "interval"
    direct_dir = tmp_path / "direct"
    expanded_dir = tmp_path / "expanded"

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
    history.build(
        candidate_path=control_dir / "g5_primary_candidate_symbol_dates.csv",
        output_dir=history_dir,
        frozen_requirements_path=(
            ROOT / "data/processed/coverage_plan_real/source_date_requirements.csv"
        ),
    )
    identity_summary = identity.build(
        control_history_path=(
            history_dir / "g5_control_history_symbol_date_requirements.csv"
        ),
        primary_candidates_path=(
            control_dir / "g5_primary_candidate_symbol_dates.csv"
        ),
        samplefirms_path=(
            ROOT / "data/raw/hacked_earnings_jfe/SampleFirms.csv"
        ),
        canonical_g2_identity_manifest_path=(
            ROOT
            / "data/processed/security_identity_real/security_identity_manifest.json"
        ),
        output_dir=identity_dir,
    )
    interval_summary = intervals.build(
        identity_queue_path=identity_dir / "g5_control_identity_acquisition_queue.csv",
        output_dir=interval_dir,
    )
    direct_summary = direct_handoff.build(
        identity_queue_path=identity_dir / "g5_control_identity_acquisition_queue.csv",
        output_dir=direct_dir,
    )
    expanded_summary = expansion.build(
        identity_queue_path=identity_dir / "g5_control_identity_acquisition_queue.csv",
        interval_requests_path=interval_dir / "g5_control_identity_interval_requests.csv",
        output_dir=expanded_dir,
    )
    return identity_summary, interval_summary, direct_summary, expanded_summary


def test_real_expansion_preserves_scope_and_never_reduces_ready_requests(tmp_path: Path):
    identity_summary, interval_summary, direct, expanded = _build_real(tmp_path)

    assert expanded["identity_queue_count"] == (
        identity_summary["identity_acquisition_queue_count"]
    )
    assert expanded["symbol_level_request_count"] == (
        interval_summary["symbol_level_interval_request_count"]
    )
    assert expanded["exact_date_ready_request_count"] == (
        direct["stocknames_ready_request_count"]
    )
    assert expanded["expanded_stocknames_ready_request_count"] >= (
        direct["stocknames_ready_request_count"]
    )
    assert (
        expanded["expanded_stocknames_ready_request_count"]
        + expanded["residual_symbol_discovery_request_count"]
        == expanded["identity_queue_count"]
    )
    assert expanded["symbol_level_lead_added_request_count"] == (
        expanded["expanded_stocknames_ready_request_count"]
        - expanded["exact_date_ready_request_count"]
    )
    assert expanded["request_ids_unique"] is True
    assert expanded["policy"]["handoff_rows_are_g5_evidence"] is False
    assert expanded["g5_dates_resolved_change"] == 0
    assert expanded["release_claimed"] is False
