from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import g5_master_acquisition_plan as master


def _build(
    tmp_path: Path,
    *,
    identity_evidence_path: Path | None = None,
):
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
        identity_evidence_path=identity_evidence_path,
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

    readiness = summary["control_identity_readiness"]
    assert readiness["identity_requirement_count"] == identity[
        "history_symbol_date_count"
    ]
    assert readiness["canonical_g2_verified_reuse_count"] == identity[
        "canonical_g2_verified_reuse_count"
    ]
    assert readiness["staged_g5_only_verified_count"] == 0
    assert readiness["unresolved_canonical_g2_overlap_count"] == identity[
        "canonical_g2_unverified_overlap_count"
    ]
    assert readiness["unresolved_identity_requirement_count"] == identity[
        "identity_acquisition_queue_count"
    ]
    assert (
        readiness["unresolved_g5_only_count"]
        + readiness["unresolved_canonical_g2_overlap_count"]
        == readiness["unresolved_identity_requirement_count"]
    )
    assert readiness["preview_full_history_identity_complete"] is False

    routing = summary["control_identity_routing"]
    assert routing["date_level_unresolved_count"] == identity[
        "identity_acquisition_queue_count"
    ]
    assert routing["symbol_level_interval_request_count"] == 88
    assert routing["stocknames_routable_date_count"] == routing[
        "date_level_unresolved_count"
    ]
    assert routing["residual_symbol_discovery_date_count"] == 0
    assert routing["grouped_stocknames_request_count"] == 88

    structural = summary["structural_plan"]
    assert structural["dates_with_three_planned_controls"] == 72
    assert structural["expansion_candidate_symbol_dates"] == 52
    assert structural["exact_date_expansion_candidate_symbol_dates"] == 51
    assert structural["prior_only_expansion_candidate_symbol_dates"] == 1
    assert structural["residual_unfilled_symbol_date_slots"] == 0

    market = summary["control_market_acquisition"]
    assert market["incremental_pair_count"] == sum(
        summary["control_history"]["additional_g5_market_pair_counts"].values()
    )
    assert market["incremental_pair_count"] > 0

    shares = summary["control_shares_acquisition"]
    assert shares["required_symbol_date_count"] == summary[
        "control_history"
    ]["shares_symbol_date_pair_count"]
    assert (
        shares["canonical_g4_reuse_count"]
        + shares["incremental_acquisition_count"]
        == shares["required_symbol_date_count"]
    )
    assert shares["incremental_acquisition_count"] > 0

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
    assert (
        tmp_path
        / "control_identity_intervals/g5_control_identity_interval_requests.csv"
    ).exists()
    assert (
        tmp_path
        / "control_identity_stocknames_leads/"
        "g5_control_identity_stocknames_expanded_ready_queue.csv"
    ).exists()
    assert (
        tmp_path
        / "control_identity_stocknames_request/"
        "g5_control_identity_stocknames_request.csv"
    ).exists()
    assert (
        tmp_path
        / "control_identity_readiness/"
        "g5_control_identity_readiness_preview.csv"
    ).exists()
    assert (
        tmp_path
        / "control_identity_readiness/"
        "g5_control_identity_readiness_summary.json"
    ).exists()
    assert (
        tmp_path
        / "control_market_vendor_bridge/g5_control_market_vendor_bridge_summary.json"
    ).exists()
    assert (
        tmp_path
        / "control_shares/g5_control_shares_reconciliation_summary.json"
    ).exists()

    saved = json.loads(
        (tmp_path / "g5_master_acquisition_summary.json").read_text(
            encoding="utf-8"
        )
    )
    assert saved["total_matching_target_count"] == 390
    assert saved["policy"]["planning_rows_are_g5_evidence"] is False
    assert saved["policy"]["reviewed_exclusions_may_close_g5"] is False

def test_master_plan_optionally_stages_g5_only_identity_without_promoting_readiness(
    tmp_path: Path,
):
    baseline_dir = tmp_path / "baseline"
    _build(baseline_dir)

    queue_path = (
        baseline_dir
        / "control_identity/g5_control_identity_acquisition_queue.csv"
    )
    with queue_path.open(encoding="utf-8", newline="") as handle:
        queue_rows = list(csv.DictReader(handle))
    target = next(
        row for row in queue_rows if row["canonical_g2_overlap"] == "NONE"
    )

    permno = (
        target["canonical_permno"]
        or target["samplefirms_permno"]
        or "99999999"
    )
    evidence_path = tmp_path / "identity_evidence.csv"
    evidence_path.write_text(
        (
            "evidence_id,permno,historical_symbol,market_identifier,valid_from,"
            "valid_through,evidence_lane,source_reference,authorization_reference,"
            "research_use_only\n"
            f"G5-TEST-1,{permno},{target['historical_symbol']},"
            f"{target['historical_symbol']},{target['trade_date']},"
            f"{target['trade_date']},AUTHORIZED_MARKET_SECURITY_MASTER,"
            "authorized-fixture:G5-TEST-1,AUTHORIZED-TEST,1\n"
        ),
        encoding="utf-8",
    )

    staged_dir = tmp_path / "staged"
    summary = _build(
        staged_dir,
        identity_evidence_path=evidence_path,
    )
    staging = summary["control_identity_evidence_staging"]
    readiness = summary["control_identity_readiness"]
    identity = summary["control_identity"]

    assert staging["input_evidence_row_count"] == 1
    assert staging["g5_only_staged_verified_count"] == 1
    assert staging["g5_only_remaining_count"] == (
        staging["g5_only_requirement_count"] - 1
    )
    assert staging["canonical_g2_forward_evidence_row_count"] == 0
    assert staging["coverage_promoted"] is False
    assert staging["overall_g5_identity_ready_claimed"] is False

    assert readiness["staged_g5_only_verified_count"] == 1
    assert readiness["unresolved_canonical_g2_overlap_count"] == identity[
        "canonical_g2_unverified_overlap_count"
    ]
    assert readiness["unresolved_identity_requirement_count"] == (
        identity["identity_acquisition_queue_count"] - 1
    )
    assert readiness["preview_full_history_identity_complete"] is False

    assert summary["inputs"]["identity_evidence"]["sha256"] == master._sha256(
        evidence_path
    )
    staging_output = Path(
        summary["component_outputs"]["control_identity_evidence_staging"]
    )
    assert (
        staging_output / "g5_control_identity_evidence_staging_receipt.json"
    ).exists()
    readiness_output = Path(
        summary["component_outputs"]["control_identity_readiness"]
    )
    assert (
        readiness_output / "g5_control_identity_readiness_preview.csv"
    ).exists()
    assert (
        readiness_output / "g5_control_identity_readiness_summary.json"
    ).exists()

    assert summary["g5_model_evaluation_controls_ready"] is False
    assert summary["canonical_g5_dates_resolved_change"] == 0
    assert summary["release_claimed"] is False

