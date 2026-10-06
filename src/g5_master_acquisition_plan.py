from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import g5_control_acquisition_planner as control_plan
import g5_control_history_requirements as control_history
import g5_control_identity_interval_requests as identity_intervals
import g5_control_identity_requirements as control_identity
import g5_control_identity_stocknames_lead_expansion as identity_leads
import g5_control_identity_stocknames_request as identity_stocknames
import g5_control_identity_evidence_stager as identity_stager
import g5_control_identity_readiness_preview as identity_readiness
import g5_control_market_vendor_bridge as market_bridge
import g5_control_shares_reconciliation as control_shares
import g5_external_source_queue as external_queue
import g5_external_acquisition_packet as external_packet
import g5_treated_metadata_requirements as treated_plan

SCHEMA_VERSION = "1"
DEFAULT_CANONICAL_G4_SHARES = Path(
    "data/processed/authorized_input_real/shares_outstanding_resolutions.csv"
)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def build(
    *,
    events_path: Path,
    frozen_market_requirements_path: Path,
    planning_universe_path: Path,
    canonical_g2_identity_manifest_path: Path,
    output_dir: Path,
    canonical_g4_shares_path: Path = DEFAULT_CANONICAL_G4_SHARES,
    identity_evidence_path: Path | None = None,
) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)

    control_dir = output_dir / "controls"
    treated_dir = output_dir / "treated"
    history_dir = output_dir / "control_history"
    external_dir = output_dir / "control_external_sources"
    external_packet_dir = output_dir / "external_acquisition_packet"
    identity_dir = output_dir / "control_identity"
    identity_interval_dir = output_dir / "control_identity_intervals"
    identity_lead_dir = output_dir / "control_identity_stocknames_leads"
    identity_stocknames_dir = output_dir / "control_identity_stocknames_request"
    identity_staging_dir = output_dir / "control_identity_evidence_staging"
    identity_readiness_dir = output_dir / "control_identity_readiness"
    market_bridge_dir = output_dir / "control_market_vendor_bridge"
    shares_dir = output_dir / "control_shares"

    control = control_plan.build(
        events_path=events_path,
        requirements_path=frozen_market_requirements_path,
        planning_universe_path=planning_universe_path,
        output_dir=control_dir,
    )
    treated = treated_plan.build(
        events_path=events_path,
        output_dir=treated_dir,
    )
    history = control_history.build(
        candidate_path=control_dir / "g5_primary_candidate_symbol_dates.csv",
        output_dir=history_dir,
        frozen_requirements_path=frozen_market_requirements_path,
    )
    external = external_queue.build(
        candidate_path=control_dir / "g5_primary_candidate_symbol_dates.csv",
        output_dir=external_dir,
    )
    external_acquisition = external_packet.build(
        control_requests_path=external_dir / "g5_external_source_requests.csv",
        treated_requests_path=(
            treated_dir / "g5_treated_external_lane_requests.csv"
        ),
        output_dir=external_packet_dir,
    )
    identity = control_identity.build(
        control_history_path=(
            history_dir / "g5_control_history_symbol_date_requirements.csv"
        ),
        primary_candidates_path=(
            control_dir / "g5_primary_candidate_symbol_dates.csv"
        ),
        samplefirms_path=planning_universe_path,
        canonical_g2_identity_manifest_path=canonical_g2_identity_manifest_path,
        output_dir=identity_dir,
    )

    intervals = identity_intervals.build(
        identity_queue_path=(
            identity_dir / "g5_control_identity_acquisition_queue.csv"
        ),
        output_dir=identity_interval_dir,
    )
    leads = identity_leads.build(
        identity_queue_path=(
            identity_dir / "g5_control_identity_acquisition_queue.csv"
        ),
        interval_requests_path=(
            identity_interval_dir / "g5_control_identity_interval_requests.csv"
        ),
        output_dir=identity_lead_dir,
    )
    stocknames = identity_stocknames.build(
        expanded_queue_path=(
            identity_lead_dir
            / "g5_control_identity_stocknames_expanded_ready_queue.csv"
        ),
        output_dir=identity_stocknames_dir,
    )
    identity_staging = None
    if identity_evidence_path is not None:
        identity_staging = identity_stager.build(
            identity_queue_path=(
                identity_dir / "g5_control_identity_acquisition_queue.csv"
            ),
            evidence_path=identity_evidence_path,
            output_dir=identity_staging_dir,
        )
        if int(identity_staging["counts"]["identity_queue_count"]) != int(
            identity["identity_acquisition_queue_count"]
        ):
            raise ValueError(
                "identity staging scope does not match the master identity queue"
            )
        if int(
            identity_staging["counts"]["canonical_g2_overlap_requirement_count"]
        ) != int(identity["canonical_g2_unverified_overlap_count"]):
            raise ValueError(
                "identity staging G2-overlap scope does not match the master identity plan"
            )

    staged_g5_only_path = None
    staging_receipt_path = None
    if identity_staging is not None:
        staged_g5_only_path = (
            identity_staging_dir / "g5_control_identity_staged_verified.csv"
        )
        staging_receipt_path = (
            identity_staging_dir
            / "g5_control_identity_evidence_staging_receipt.json"
        )

    identity_readiness_state = identity_readiness.build_preview(
        identity_requirements_path=(
            identity_dir / "g5_control_identity_requirements.csv"
        ),
        canonical_g2_identity_manifest_path=canonical_g2_identity_manifest_path,
        staged_g5_only_path=staged_g5_only_path,
        staging_receipt_path=staging_receipt_path,
        output_path=(
            identity_readiness_dir / "g5_control_identity_readiness_preview.csv"
        ),
        summary_path=(
            identity_readiness_dir / "g5_control_identity_readiness_summary.json"
        ),
    )
    if int(identity_readiness_state["identity_requirement_count"]) != int(
        identity["control_history_symbol_date_count"]
    ):
        raise ValueError(
            "identity readiness scope does not match the master control-history identity plan"
        )
    if int(identity_readiness_state["canonical_g2_verified_reuse_count"]) != int(
        identity["canonical_g2_verified_reuse_count"]
    ):
        raise ValueError(
            "identity readiness canonical G2 reuse count does not match the master identity plan"
        )
    expected_staged_g5_verified = (
        int(identity_staging["counts"]["g5_only_staged_verified_count"])
        if identity_staging is not None
        else 0
    )
    if int(identity_readiness_state["staged_g5_only_verified_count"]) != (
        expected_staged_g5_verified
    ):
        raise ValueError(
            "identity readiness staged G5 count does not match the evidence staging receipt"
        )
    expected_unresolved_identity = int(
        identity["identity_acquisition_queue_count"]
    ) - expected_staged_g5_verified
    if int(identity_readiness_state["unresolved_identity_requirement_count"]) != (
        expected_unresolved_identity
    ):
        raise ValueError(
            "identity readiness unresolved count does not reconcile to the acquisition queue"
        )

    market = market_bridge.build(
        g5_source_requirements_path=(
            history_dir / "g5_control_history_source_date_requirements.csv"
        ),
        frozen_g2_requirements_path=frozen_market_requirements_path,
        output_dir=market_bridge_dir,
    )
    shares = control_shares.build(
        control_history_path=(
            history_dir / "g5_control_history_symbol_date_requirements.csv"
        ),
        canonical_g4_shares_path=canonical_g4_shares_path,
        output_dir=shares_dir,
    )

    control_targets = int(control["primary_candidate_symbol_date_count"])
    treated_targets = int(treated["treated_target_count"])
    control_fields = int(control["primary_field_requirement_count"])
    treated_fields = int(treated["treated_field_requirement_count"])
    control_derived = int(control["primary_derived_field_requirement_count"])
    treated_derived = int(treated["treated_derived_field_requirement_count"])
    control_external = int(control["primary_external_field_requirement_count"])
    treated_external = int(treated["treated_external_field_requirement_count"])
    control_lanes = int(external["lane_request_count"])
    treated_lanes = int(treated["treated_external_lane_request_count"])

    if control_targets != 216:
        raise ValueError(
            f"expected exactly 216 primary control targets, got {control_targets}"
        )
    if treated_targets != 174:
        raise ValueError(
            f"expected exactly 174 treated targets, got {treated_targets}"
        )
    if control["primary_complete_event_date_count"] != 72:
        raise ValueError("primary control queue does not cover all 72 event dates")
    if control["residual_unfilled_symbol_date_slots"] != 0:
        raise ValueError("control acquisition plan still has structural gaps")
    if int(external_acquisition["control_lane_request_count"]) != control_lanes:
        raise ValueError(
            "external acquisition packet control scope does not match the control lane queue"
        )
    if int(external_acquisition["treated_lane_request_count"]) != treated_lanes:
        raise ValueError(
            "external acquisition packet treated scope does not match the treated lane queue"
        )
    if int(external_acquisition["total_lane_request_count"]) != (
        control_lanes + treated_lanes
    ):
        raise ValueError(
            "external acquisition packet total scope does not match master external lanes"
        )
    if int(external_acquisition["external_field_requirement_count"]) != (
        control_external + treated_external
    ):
        raise ValueError(
            "external acquisition packet field scope does not match master requirements"
        )
    if int(intervals["date_level_identity_requirement_count"]) != int(
        identity["identity_acquisition_queue_count"]
    ):
        raise ValueError("identity interval scope does not match the master identity queue")
    if int(leads["identity_queue_count"]) != int(
        identity["identity_acquisition_queue_count"]
    ):
        raise ValueError("Stocknames lead expansion does not match the identity queue")
    if (
        int(leads["expanded_stocknames_ready_request_count"])
        + int(leads["residual_symbol_discovery_request_count"])
        != int(identity["identity_acquisition_queue_count"])
    ):
        raise ValueError("Stocknames routing does not account for every identity gap")
    if int(stocknames["state"]["date_level_request_count"]) != int(
        leads["expanded_stocknames_ready_request_count"]
    ):
        raise ValueError("grouped Stocknames request does not reconcile to routed dates")
    if int(market["incremental_g5_pair_count"]) != sum(
        int(value) for value in history["additional_g5_market_pair_counts"].values()
    ):
        raise ValueError("market vendor bridge does not reconcile to incremental G5 pairs")
    if int(shares["required_shares_symbol_date_count"]) != int(
        history["shares_symbol_date_pair_count"]
    ):
        raise ValueError("shares reconciliation does not match the control-history plan")
    if (
        int(shares["canonical_g4_reuse_count"])
        + int(shares["incremental_g5_shares_acquisition_count"])
        != int(shares["required_shares_symbol_date_count"])
    ):
        raise ValueError("shares reconciliation does not account for every requirement")

    summary = {
        "schema_version": SCHEMA_VERSION,
        "purpose": (
            "One deterministic G5 acquisition plan joining treated-event requirements, "
            "the minimal three-per-date control queue, external metadata lanes, and the "
            "control-history market/shares expansion needed for genuine point-in-time matching."
        ),
        "research_use_only": True,
        "event_count": int(treated["event_count"]),
        "event_date_count": int(treated["event_date_count"]),
        "control_primary_target_count": control_targets,
        "control_reserve_target_count": int(
            control["reserve_candidate_symbol_date_count"]
        ),
        "treated_target_count": treated_targets,
        "total_matching_target_count": control_targets + treated_targets,
        "control_field_requirement_count": control_fields,
        "treated_field_requirement_count": treated_fields,
        "total_matching_field_requirement_count": control_fields + treated_fields,
        "control_derived_field_requirement_count": control_derived,
        "treated_derived_field_requirement_count": treated_derived,
        "total_derived_field_requirement_count": control_derived + treated_derived,
        "control_external_field_requirement_count": control_external,
        "treated_external_field_requirement_count": treated_external,
        "total_external_field_requirement_count": control_external + treated_external,
        "control_external_lane_request_count": control_lanes,
        "treated_external_lane_request_count": treated_lanes,
        "total_external_lane_request_count": control_lanes + treated_lanes,
        "external_acquisition_packet": {
            "control_lane_request_count": int(
                external_acquisition["control_lane_request_count"]
            ),
            "treated_lane_request_count": int(
                external_acquisition["treated_lane_request_count"]
            ),
            "total_lane_request_count": int(
                external_acquisition["total_lane_request_count"]
            ),
            "external_field_requirement_count": int(
                external_acquisition["external_field_requirement_count"]
            ),
            "grouped_lane_symbol_batch_count": int(
                external_acquisition["grouped_lane_symbol_batch_count"]
            ),
            "lane_counts": external_acquisition["lane_counts"],
        },
        "control_identity": {
            "history_symbol_date_count": int(
                identity["control_history_symbol_date_count"]
            ),
            "canonical_g2_verified_reuse_count": int(
                identity["canonical_g2_verified_reuse_count"]
            ),
            "canonical_g2_unverified_overlap_count": int(
                identity["canonical_g2_unverified_overlap_count"]
            ),
            "public_exact_mapping_available_requires_admission_count": int(
                identity[
                    "public_exact_mapping_available_requires_admission_count"
                ]
            ),
            "new_g5_identity_evidence_required_count": int(
                identity["new_g5_identity_evidence_required_count"]
            ),
            "ambiguous_public_mapping_count": int(
                identity["ambiguous_public_mapping_count"]
            ),
            "identity_acquisition_queue_count": int(
                identity["identity_acquisition_queue_count"]
            ),
            "primary_candidate_exact_sample_mapping": identity[
                "primary_candidate_exact_sample_mapping"
            ],
        },
        "control_identity_readiness": {
            "identity_requirement_count": int(
                identity_readiness_state["identity_requirement_count"]
            ),
            "canonical_g2_verified_reuse_count": int(
                identity_readiness_state["canonical_g2_verified_reuse_count"]
            ),
            "staged_g5_only_verified_count": int(
                identity_readiness_state["staged_g5_only_verified_count"]
            ),
            "preview_verified_count": int(
                identity_readiness_state["preview_verified_count"]
            ),
            "unresolved_canonical_g2_overlap_count": int(
                identity_readiness_state[
                    "unresolved_canonical_g2_overlap_count"
                ]
            ),
            "unresolved_g5_only_count": int(
                identity_readiness_state["unresolved_g5_only_count"]
            ),
            "unresolved_identity_requirement_count": int(
                identity_readiness_state["unresolved_identity_requirement_count"]
            ),
            "preview_full_history_identity_complete": bool(
                identity_readiness_state[
                    "preview_full_history_identity_complete"
                ]
            ),
        },
        "control_identity_routing": {
            "date_level_unresolved_count": int(
                intervals["date_level_identity_requirement_count"]
            ),
            "symbol_level_interval_request_count": int(
                intervals["symbol_level_interval_request_count"]
            ),
            "stocknames_routable_date_count": int(
                leads["expanded_stocknames_ready_request_count"]
            ),
            "residual_symbol_discovery_date_count": int(
                leads["residual_symbol_discovery_request_count"]
            ),
            "grouped_stocknames_request_count": int(
                stocknames["state"]["grouped_permno_symbol_request_count"]
            ),
        },
        "control_market_acquisition": {
            "incremental_pair_count": int(market["incremental_g5_pair_count"]),
            "incremental_pair_count_by_record_kind": market[
                "incremental_pair_count_by_record_kind"
            ],
            "route_symbol_date_pair_counts": market[
                "route_symbol_date_pair_counts"
            ],
        },
        "control_shares_acquisition": {
            "required_symbol_date_count": int(
                shares["required_shares_symbol_date_count"]
            ),
            "canonical_g4_reuse_count": int(
                shares["canonical_g4_reuse_count"]
            ),
            "incremental_acquisition_count": int(
                shares["incremental_g5_shares_acquisition_count"]
            ),
            "gap_reason_counts": shares["gap_reason_counts"],
        },
        "control_history": {
            "unique_symbol_date_pairs": int(
                history["unique_control_history_symbol_date_pairs"]
            ),
            "market_symbol_date_pair_counts": history[
                "market_symbol_date_pair_counts"
            ],
            "frozen_g2_overlap_pair_counts": history[
                "frozen_g2_overlap_pair_counts"
            ],
            "additional_g5_market_pair_counts": history[
                "additional_g5_market_pair_counts"
            ],
            "shares_symbol_date_pair_count": int(
                history["shares_symbol_date_pair_count"]
            ),
            "normalization_sessions": int(history["normalization_sessions"]),
            "daily_close_sessions": int(history["daily_close_sessions"]),
            "early_close_or_short_session_skips": int(
                history["early_close_or_short_session_skips"]
            ),
        },
        "structural_plan": {
            "dates_with_three_planned_controls": int(
                control["primary_complete_event_date_count"]
            ),
            "expansion_candidate_symbol_dates": int(
                control["planned_expansion_candidate_symbol_date_count"]
            ),
            "exact_date_expansion_candidate_symbol_dates": int(
                control["exact_date_expansion_candidate_symbol_date_count"]
            ),
            "prior_only_expansion_candidate_symbol_dates": int(
                control["prior_only_expansion_candidate_symbol_date_count"]
            ),
            "residual_unfilled_symbol_date_slots": int(
                control["residual_unfilled_symbol_date_slots"]
            ),
        },
        "dependencies": {
            "real_g2_market_data": True,
            "point_in_time_g4_shares": True,
            "stable_security_identity": True,
            "external_point_in_time_classification": True,
            "external_point_in_time_ownership": True,
            "external_point_in_time_analyst_coverage": True,
            "external_point_in_time_borrow_cost": True,
            "canonical_metadata_admission_and_quality_gate": True,
            "final_match_contamination_and_balance_checks": True,
        },
        "inputs": {
            "events": {
                "path": str(events_path),
                "sha256": _sha256(events_path),
            },
            "frozen_market_requirements": {
                "path": str(frozen_market_requirements_path),
                "sha256": _sha256(frozen_market_requirements_path),
            },
            "planning_universe": {
                "path": str(planning_universe_path),
                "sha256": _sha256(planning_universe_path),
            },
            "canonical_g2_identity_manifest": {
                "path": str(canonical_g2_identity_manifest_path),
                "sha256": _sha256(canonical_g2_identity_manifest_path),
            },
            "canonical_g4_shares": {
                "path": str(canonical_g4_shares_path),
                "sha256": _sha256(canonical_g4_shares_path),
            },
        },
        "component_outputs": {
            "controls": str(control_dir),
            "treated": str(treated_dir),
            "control_history": str(history_dir),
            "control_external_sources": str(external_dir),
            "external_acquisition_packet": str(external_packet_dir),
            "control_identity": str(identity_dir),
            "control_identity_intervals": str(identity_interval_dir),
            "control_identity_stocknames_leads": str(identity_lead_dir),
            "control_identity_stocknames_request": str(identity_stocknames_dir),
            "control_identity_readiness": str(identity_readiness_dir),
            "control_market_vendor_bridge": str(market_bridge_dir),
            "control_shares": str(shares_dir),
        },
        "g5_model_evaluation_controls_ready": False,
        "canonical_g5_dates_resolved_change": 0,
        "release_claimed": False,
        "policy": {
            "planning_rows_are_g5_evidence": False,
            "retrospective_labels_may_close_g5": False,
            "reviewed_exclusions_may_close_g5": False,
            "real_source_data_and_point_in_time_cutoffs_required": True,
        },
    }

    if identity_staging is not None:
        staging_counts = identity_staging["counts"]
        summary["control_identity_evidence_staging"] = {
            "input_evidence_row_count": int(
                staging_counts["input_evidence_row_count"]
            ),
            "g5_only_requirement_count": int(
                staging_counts["g5_only_requirement_count"]
            ),
            "g5_only_staged_verified_count": int(
                staging_counts["g5_only_staged_verified_count"]
            ),
            "g5_only_remaining_count": int(
                staging_counts["g5_only_remaining_count"]
            ),
            "canonical_g2_forward_evidence_row_count": int(
                staging_counts["g2_forward_evidence_row_count"]
            ),
            "g5_only_identity_staging_complete": bool(
                identity_staging["g5_only_identity_staging_complete"]
            ),
            "overall_g5_identity_ready_claimed": bool(
                identity_staging["overall_g5_identity_ready_claimed"]
            ),
            "coverage_promoted": bool(identity_staging["coverage_promoted"]),
            "output_sha256": identity_staging["output_sha256"],
        }
        summary["inputs"]["identity_evidence"] = {
            "path": str(identity_evidence_path),
            "sha256": _sha256(identity_evidence_path),
        }
        summary["component_outputs"]["control_identity_evidence_staging"] = str(
            identity_staging_dir
        )

    (output_dir / "g5_master_acquisition_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build the complete fail-closed G5 acquisition plan."
    )
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--frozen-market-requirements", type=Path, required=True)
    parser.add_argument("--planning-universe", type=Path, required=True)
    parser.add_argument("--canonical-g2-identity-manifest", type=Path, required=True)
    parser.add_argument(
        "--canonical-g4-shares",
        type=Path,
        default=DEFAULT_CANONICAL_G4_SHARES,
    )
    parser.add_argument(
        "--identity-evidence",
        type=Path,
        help=(
            "Optional authorized dated stable-ID evidence. When supplied, the G5-only "
            "identity stager runs inside the master plan without promoting canonical readiness."
        ),
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    result = build(
        events_path=args.events,
        frozen_market_requirements_path=args.frozen_market_requirements,
        planning_universe_path=args.planning_universe,
        canonical_g2_identity_manifest_path=args.canonical_g2_identity_manifest,
        canonical_g4_shares_path=args.canonical_g4_shares,
        identity_evidence_path=args.identity_evidence,
        output_dir=args.output_dir,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
