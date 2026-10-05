from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import g5_master_acquisition_plan as master


def _build(tmp_path: Path):
    return master.build(
        events_path=ROOT / "data/processed/historical_events.csv",
        frozen_market_requirements_path=(
            ROOT / "data/processed/coverage_plan_real/source_date_requirements.csv"
        ),
        planning_universe_path=(
            ROOT / "data/raw/hacked_earnings_jfe/SampleFirms.csv"
        ),
        canonical_g2_identity_manifest_path=(
            ROOT
            / "data/processed/security_identity_real/security_identity_manifest.json"
        ),
        output_dir=tmp_path,
    )


def test_real_master_plan_has_complete_structural_scope(tmp_path: Path):
    summary = _build(tmp_path)

    assert summary["event_count"] == 174
    assert summary["event_date_count"] == 72
    assert summary["control_primary_target_count"] == 216
    assert summary["control_reserve_target_count"] == 766
    assert summary["treated_target_count"] == 174
    assert summary["total_matching_target_count"] == 390

    assert summary["control_field_requirement_count"] == 2808
    assert summary["treated_field_requirement_count"] == 2262
    assert summary["total_matching_field_requirement_count"] == 5070

    assert summary["control_derived_field_requirement_count"] == 1728
    assert summary["treated_derived_field_requirement_count"] == 1392
    assert summary["total_derived_field_requirement_count"] == 3120

    assert summary["control_external_field_requirement_count"] == 1080
    assert summary["treated_external_field_requirement_count"] == 870
    assert summary["total_external_field_requirement_count"] == 1950

    assert summary["control_external_lane_request_count"] == 864
    assert summary["treated_external_lane_request_count"] == 696
    assert summary["total_external_lane_request_count"] == 1560

    identity = summary["control_identity"]
    assert identity["history_symbol_date_count"] == (
        summary["control_history"]["unique_symbol_date_pairs"]
    )
    assert identity["primary_candidate_exact_sample_mapping"] == {
        "unique": 51,
        "ambiguous": 0,
        "missing": 165,
    }
    assert identity["identity_acquisition_queue_count"] > 0
    assert (
        identity["canonical_g2_verified_reuse_count"]
        + identity["canonical_g2_unverified_overlap_count"]
    ) > 0
    assert identity["new_g5_identity_evidence_required_count"] > 0

    structural = summary["structural_plan"]
    assert structural["dates_with_three_planned_controls"] == 72
    assert structural["expansion_candidate_symbol_dates"] == 52
    assert structural["exact_date_expansion_candidate_symbol_dates"] == 51
    assert structural["prior_only_expansion_candidate_symbol_dates"] == 1
    assert structural["residual_unfilled_symbol_date_slots"] == 0

    assert summary["g5_model_evaluation_controls_ready"] is False
    assert summary["canonical_g5_dates_resolved_change"] == 0
    assert summary["release_claimed"] is False


def test_history_overlap_reconciles_for_every_market_kind(tmp_path: Path):
    summary = _build(tmp_path)
    history = summary["control_history"]

    assert history["normalization_sessions"] == 21
    assert history["daily_close_sessions"] == 22
    assert history["unique_symbol_date_pairs"] > 216
    assert history["shares_symbol_date_pair_count"] > 216

    for kind in (
        "equity_trade",
        "equity_quote",
        "option_trade",
        "option_quote",
    ):
        total = history["market_symbol_date_pair_counts"][kind]
        frozen = history["frozen_g2_overlap_pair_counts"][kind]
        additional = history["additional_g5_market_pair_counts"][kind]
        assert total == frozen + additional
        assert total > 216
        assert additional > 0


def test_master_plan_emits_all_component_outputs(tmp_path: Path):
    summary = _build(tmp_path)

    assert (tmp_path / "g5_master_acquisition_summary.json").exists()
    assert (
        tmp_path / "controls/g5_primary_candidate_symbol_dates.csv"
    ).exists()
    assert (
        tmp_path / "controls/g5_reserve_candidate_symbol_dates.csv"
    ).exists()
    assert (
        tmp_path / "treated/g5_treated_targets.csv"
    ).exists()
    assert (
        tmp_path
        / "control_history/g5_control_history_symbol_date_requirements.csv"
    ).exists()
    assert (
        tmp_path
        / "control_external_sources/g5_external_source_requests.csv"
    ).exists()
    assert (
        tmp_path
        / "control_identity/g5_control_identity_requirements.csv"
    ).exists()
    assert (
        tmp_path
        / "control_identity/g5_control_identity_acquisition_queue.csv"
    ).exists()

    saved = json.loads(
        (tmp_path / "g5_master_acquisition_summary.json").read_text(
            encoding="utf-8"
        )
    )
    assert saved["total_matching_target_count"] == 390
    assert saved["policy"]["planning_rows_are_g5_evidence"] is False
    assert saved["policy"]["reviewed_exclusions_may_close_g5"] is False
