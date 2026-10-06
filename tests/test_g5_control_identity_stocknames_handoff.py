from __future__ import annotations

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import g5_control_acquisition_planner as acquisition
import g5_control_history_requirements as history
import g5_control_identity_requirements as identity
import g5_control_identity_stocknames_handoff as handoff
import g5_control_identity_symbol_permno_leads as symbol_leads
import security_identity_stocknames_adapter as stocknames


def _build_real(tmp_path: Path):
    control_dir = tmp_path / "controls"
    history_dir = tmp_path / "history"
    identity_dir = tmp_path / "identity"
    handoff_dir = tmp_path / "handoff"

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
    handoff_summary = handoff.build(
        identity_queue_path=(
            identity_dir / "g5_control_identity_acquisition_queue.csv"
        ),
        output_dir=handoff_dir,
    )
    return identity_summary, handoff_summary, handoff_dir


def test_real_handoff_reconciles_identity_queue(tmp_path: Path):
    identity_summary, summary, _out = _build_real(tmp_path)

    assert summary["identity_queue_count"] == (
        identity_summary["identity_acquisition_queue_count"]
    )
    assert (
        summary["stocknames_ready_request_count"]
        + summary["no_permno_hint_request_count"]
        == summary["identity_queue_count"]
    )
    assert summary["stocknames_ready_request_count"] > 0
    assert summary["no_permno_hint_request_count"] > 0
    assert summary["canonical_permno_hint_request_count"] > 0
    assert summary["samplefirms_permno_lead_request_count"] > 0
    assert summary["request_ids_unique"] is True
    assert summary["g5_dates_resolved_change"] == 0
    assert summary["release_claimed"] is False


def test_ready_queue_is_directly_compatible_with_stocknames_adapter(tmp_path: Path):
    q = tmp_path / "g5_identity_queue.csv"
    q.write_text(
        "historical_symbol,trade_date,roles,identity_status,canonical_g2_overlap,"
        "canonical_permno,canonical_gvkey,samplefirms_permno,samplefirms_gvkey,"
        "samplefirms_exact_mapping_status,required_evidence,research_use_only\n"
        "AAA,2015-01-02,event_point,OVERLAPS_CANONICAL_G2_IDENTITY_QUEUE,"
        "CANONICAL_G2_UNVERIFIED,12345,1,,,NO_EXACT_DATE_MAPPING,"
        "DATED_STABLE_ID_CROSSWALK,1\n"
        "BBB,2015-01-03,event_point,PUBLIC_EXACT_MAPPING_AVAILABLE_REQUIRES_ADMISSION,"
        "NONE,,,67890,2,UNIQUE_EXACT_DATE_MAPPING_AVAILABLE,"
        "ADMISSIBLE_DATE_SPECIFIC_STABLE_ID_EVIDENCE,1\n",
        encoding="utf-8",
    )

    out = tmp_path / "out"
    summary = handoff.build(identity_queue_path=q, output_dir=out)
    ready_rows = handoff._read_csv(
        out / "g5_control_identity_stocknames_ready_queue.csv"
    )[1]

    stock_rows = [
        {
            "permno": "12345",
            "ticker": "AAA",
            "namedt": "2010-01-01",
            "nameenddt": "2020-12-31",
        },
        {
            "permno": "67890",
            "ticker": "BBB",
            "namedt": "2010-01-01",
            "nameenddt": "2020-12-31",
        },
    ]
    evidence, receipt = stocknames.build_evidence(
        ready_rows,
        stock_rows,
        source_sha256="1" * 64,
        authorization_reference="AUTHORIZED-STOCKNAMES-TEST",
    )

    assert summary["stocknames_ready_request_count"] == 2
    assert summary["no_permno_hint_request_count"] == 0
    assert len(evidence) == 2
    assert receipt["all_queue_requests_evidence_ready"] is True
    assert {row["historical_symbol"] for row in evidence} == {"AAA", "BBB"}
    assert all(
        row["evidence_lane"] == "LICENSED_STABLE_ID_MASTER"
        for row in evidence
    )


def test_permno_hint_conflict_fails_closed(tmp_path: Path):
    q = tmp_path / "conflict.csv"
    q.write_text(
        "historical_symbol,trade_date,identity_status,canonical_permno,"
        "samplefirms_permno,research_use_only\n"
        "AAA,2015-01-02,OVERLAPS_CANONICAL_G2_IDENTITY_QUEUE,12345,67890,1\n",
        encoding="utf-8",
    )

    try:
        handoff.build(identity_queue_path=q, output_dir=tmp_path / "out")
    except ValueError as exc:
        assert "PERMNO hint conflict" in str(exc)
    else:
        raise AssertionError("expected PERMNO hint conflict rejection")


def test_rows_without_permno_hint_remain_separate_and_fail_closed(tmp_path: Path):
    q = tmp_path / "missing.csv"
    q.write_text(
        "historical_symbol,trade_date,identity_status,canonical_permno,"
        "samplefirms_permno,research_use_only\n"
        "AAA,2015-01-02,NEW_G5_IDENTITY_EVIDENCE_REQUIRED,,,1\n",
        encoding="utf-8",
    )

    out = tmp_path / "out"
    summary = handoff.build(identity_queue_path=q, output_dir=out)

    ready = list(
        csv.DictReader(
            (out / "g5_control_identity_stocknames_ready_queue.csv").open(
                encoding="utf-8"
            )
        )
    )
    missing = list(
        csv.DictReader(
            (out / "g5_control_identity_no_permno_hint.csv").open(
                encoding="utf-8"
            )
        )
    )
    assert ready == []
    assert len(missing) == 1
    assert summary["stocknames_ready_request_count"] == 0
    assert summary["no_permno_hint_request_count"] == 1
    assert summary["policy"]["rows_without_permno_hint_fail_closed"] is True


def test_symbol_level_permno_lead_can_fill_only_a_no_hint_row(tmp_path: Path):
    q = tmp_path / "missing.csv"
    q.write_text(
        "historical_symbol,trade_date,identity_status,canonical_permno,"
        "samplefirms_permno,research_use_only\n"
        "AAA,2015-01-02,NEW_G5_IDENTITY_EVIDENCE_REQUIRED,,,1\n",
        encoding="utf-8",
    )
    lead = tmp_path / "leads.csv"
    lead.write_text(
        "request_id,historical_symbol,trade_date,permno,gvkey_hint,lead_source,"
        "identity_status,research_use_only\n"
        "G5SIDLEAD-TEST,AAA,2015-01-02,12345,001111,"
        "SAMPLEFIRMS_SAME_SYMBOL_UNIQUE_PERMNO_HISTORY,"
        "NEW_G5_IDENTITY_EVIDENCE_REQUIRED,1\n",
        encoding="utf-8",
    )

    out = tmp_path / "out"
    summary = handoff.build(
        identity_queue_path=q,
        output_dir=out,
        symbol_permno_leads_path=lead,
    )

    ready = list(
        csv.DictReader(
            (out / "g5_control_identity_stocknames_ready_queue.csv").open(
                encoding="utf-8"
            )
        )
    )
    assert len(ready) == 1
    assert ready[0]["permno"] == "12345"
    assert (
        ready[0]["hint_source"]
        == "SAMPLEFIRMS_SAME_SYMBOL_UNIQUE_PERMNO_HISTORY_LEAD"
    )
    assert summary["symbol_level_permno_lead_request_count"] == 1
    assert summary["no_permno_hint_request_count"] == 0
    assert summary["policy"]["symbol_level_permno_lead_is_identity_evidence"] is False
    assert summary["g5_dates_resolved_change"] == 0
    assert summary["release_claimed"] is False


def test_symbol_level_lead_cannot_override_existing_stronger_hint(tmp_path: Path):
    q = tmp_path / "hinted.csv"
    q.write_text(
        "historical_symbol,trade_date,identity_status,canonical_permno,"
        "samplefirms_permno,research_use_only\n"
        "AAA,2015-01-02,OVERLAPS_CANONICAL_G2_IDENTITY_QUEUE,12345,,1\n",
        encoding="utf-8",
    )
    lead = tmp_path / "leads.csv"
    lead.write_text(
        "request_id,historical_symbol,trade_date,permno,gvkey_hint,lead_source,"
        "identity_status,research_use_only\n"
        "G5SIDLEAD-TEST,AAA,2015-01-02,12345,001111,"
        "SAMPLEFIRMS_SAME_SYMBOL_UNIQUE_PERMNO_HISTORY,"
        "OVERLAPS_CANONICAL_G2_IDENTITY_QUEUE,1\n",
        encoding="utf-8",
    )

    try:
        handoff.build(
            identity_queue_path=q,
            output_dir=tmp_path / "out",
            symbol_permno_leads_path=lead,
        )
    except ValueError as exc:
        assert "out of scope for already-hinted row" in str(exc)
    else:
        raise AssertionError("expected stronger-hint protection")


def test_real_symbol_permno_leads_reduce_no_hint_stocknames_queue(tmp_path: Path):
    control_dir = tmp_path / "controls"
    history_dir = tmp_path / "history"
    identity_dir = tmp_path / "identity"
    leads_dir = tmp_path / "leads"
    baseline_dir = tmp_path / "baseline"
    enriched_dir = tmp_path / "enriched"

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
    identity.build(
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
    identity_queue = identity_dir / "g5_control_identity_acquisition_queue.csv"

    baseline = handoff.build(
        identity_queue_path=identity_queue,
        output_dir=baseline_dir,
    )
    lead_summary = symbol_leads.build(
        identity_queue_path=identity_queue,
        samplefirms_path=ROOT / "data/raw/hacked_earnings_jfe/SampleFirms.csv",
        output_dir=leads_dir,
    )
    enriched = handoff.build(
        identity_queue_path=identity_queue,
        output_dir=enriched_dir,
        symbol_permno_leads_path=(
            leads_dir / "g5_control_identity_symbol_permno_leads.csv"
        ),
    )

    assert lead_summary["symbol_level_permno_lead_count"] > 0
    assert enriched["symbol_level_permno_lead_request_count"] == (
        lead_summary["symbol_level_permno_lead_count"]
    )
    assert enriched["stocknames_ready_request_count"] > (
        baseline["stocknames_ready_request_count"]
    )
    assert enriched["no_permno_hint_request_count"] < (
        baseline["no_permno_hint_request_count"]
    )
    assert (
        enriched["stocknames_ready_request_count"]
        + enriched["no_permno_hint_request_count"]
        == enriched["identity_queue_count"]
    )
    assert enriched["g5_dates_resolved_change"] == 0
    assert enriched["release_claimed"] is False
