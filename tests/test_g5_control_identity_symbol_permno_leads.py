from __future__ import annotations

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import g5_control_acquisition_planner as acquisition
import g5_control_history_requirements as history
import g5_control_identity_requirements as identity
import g5_control_identity_symbol_permno_leads as leads


QUEUE_HEADER = (
    "historical_symbol,trade_date,identity_status,canonical_g2_overlap,"
    "canonical_permno,canonical_gvkey,samplefirms_permno,samplefirms_gvkey,"
    "samplefirms_exact_mapping_status,required_evidence,research_use_only\n"
)

SAMPLE_HEADER = "PERMNO,GVKEY,SYMBOL,date,Hacked,Actual,Soft\n"


def _queue(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "queue.csv"
    path.write_text(QUEUE_HEADER + body, encoding="utf-8")
    return path


def _samplefirms(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "SampleFirms.csv"
    path.write_text(SAMPLE_HEADER + body, encoding="utf-8")
    return path


def test_unique_same_symbol_history_emits_validation_lead_only(tmp_path: Path):
    queue = _queue(
        tmp_path,
        "AAA,2015-01-05,NEW_G5_IDENTITY_EVIDENCE_REQUIRED,NONE,,,,,"
        "NO_EXACT_DATE_MAPPING,DATED_STABLE_ID_CROSSWALK,1\n",
    )
    sample = _samplefirms(
        tmp_path,
        "12345,001111,AAA,2015-01-01,1,0,1\n"
        "12345,001111,AAA,2015-01-10,0,1,0\n",
    )

    out = tmp_path / "out"
    summary = leads.build(
        identity_queue_path=queue,
        samplefirms_path=sample,
        output_dir=out,
    )

    assert summary["eligible_no_hint_requirement_count"] == 1
    assert summary["symbol_level_permno_lead_count"] == 1
    assert summary["unresolved_no_hint_requirement_count"] == 0
    assert summary["g5_dates_resolved_change"] == 0
    assert summary["release_claimed"] is False
    assert summary["policy"]["retrospective_labels_used"] is False
    assert summary["policy"]["symbol_level_lead_is_identity_evidence"] is False
    assert summary["policy"]["authorized_dated_validation_still_required"] is True

    rows = list(
        csv.DictReader(
            (out / "g5_control_identity_symbol_permno_leads.csv").open(
                encoding="utf-8"
            )
        )
    )
    assert len(rows) == 1
    assert rows[0]["historical_symbol"] == "AAA"
    assert rows[0]["trade_date"] == "2015-01-05"
    assert rows[0]["permno"] == "12345"
    assert rows[0]["gvkey_hint"] == "001111"
    assert rows[0]["lead_source"] == "SAMPLEFIRMS_SAME_SYMBOL_UNIQUE_PERMNO_HISTORY"


def test_ambiguous_same_symbol_permno_history_stays_fail_closed(tmp_path: Path):
    queue = _queue(
        tmp_path,
        "BBB,2015-01-05,NEW_G5_IDENTITY_EVIDENCE_REQUIRED,NONE,,,,,"
        "NO_EXACT_DATE_MAPPING,DATED_STABLE_ID_CROSSWALK,1\n",
    )
    sample = _samplefirms(
        tmp_path,
        "11111,002222,BBB,2015-01-01,0,0,0\n"
        "22222,002222,BBB,2015-01-10,0,0,0\n",
    )

    out = tmp_path / "out"
    summary = leads.build(
        identity_queue_path=queue,
        samplefirms_path=sample,
        output_dir=out,
    )

    assert summary["symbol_level_permno_lead_count"] == 0
    assert summary["unresolved_no_hint_requirement_count"] == 1
    assert summary["ambiguous_symbol_level_permno_history_count"] == 1

    unresolved = list(
        csv.DictReader(
            (out / "g5_control_identity_symbol_permno_unresolved.csv").open(
                encoding="utf-8"
            )
        )
    )
    assert unresolved[0]["lead_status"] == "AMBIGUOUS_SYMBOL_LEVEL_PERMNO_HISTORY"


def test_existing_exact_or_canonical_hints_are_not_replanned(tmp_path: Path):
    queue = _queue(
        tmp_path,
        "AAA,2015-01-05,OVERLAPS_CANONICAL_G2_IDENTITY_QUEUE,"
        "CANONICAL_G2_UNVERIFIED,12345,001111,,,NO_EXACT_DATE_MAPPING,"
        "DATED_STABLE_ID_CROSSWALK,1\n"
        "BBB,2015-01-06,PUBLIC_EXACT_MAPPING_AVAILABLE_REQUIRES_ADMISSION,"
        "NONE,,,22222,002222,UNIQUE_EXACT_DATE_MAPPING_AVAILABLE,"
        "ADMISSIBLE_DATE_SPECIFIC_STABLE_ID_EVIDENCE,1\n",
    )
    sample = _samplefirms(
        tmp_path,
        "12345,001111,AAA,2015-01-01,0,0,0\n"
        "22222,002222,BBB,2015-01-01,0,0,0\n",
    )

    summary = leads.build(
        identity_queue_path=queue,
        samplefirms_path=sample,
        output_dir=tmp_path / "out",
    )
    assert summary["eligible_no_hint_requirement_count"] == 0
    assert summary["symbol_level_permno_lead_count"] == 0
    assert summary["unresolved_no_hint_requirement_count"] == 0


def test_real_g5_no_hint_queue_can_be_reduced_without_promoting_identity(
    tmp_path: Path,
):
    control_dir = tmp_path / "controls"
    history_dir = tmp_path / "history"
    identity_dir = tmp_path / "identity"
    lead_dir = tmp_path / "leads"

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
    summary = leads.build(
        identity_queue_path=identity_dir / "g5_control_identity_acquisition_queue.csv",
        samplefirms_path=ROOT / "data/raw/hacked_earnings_jfe/SampleFirms.csv",
        output_dir=lead_dir,
    )

    assert summary["eligible_no_hint_requirement_count"] > 0
    assert summary["symbol_level_permno_lead_count"] > 0
    assert (
        summary["symbol_level_permno_lead_count"]
        + summary["unresolved_no_hint_requirement_count"]
        == summary["eligible_no_hint_requirement_count"]
    )
    assert summary["eligible_no_hint_requirement_count"] < (
        identity_summary["identity_acquisition_queue_count"]
    )
    assert summary["g5_dates_resolved_change"] == 0
    assert summary["release_claimed"] is False
