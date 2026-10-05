from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import g5_control_acquisition_planner as control_plan
import g5_control_history_requirements as control_history
import g5_control_identity_requirements as control_identity
import g5_external_source_queue as external_queue
import g5_treated_metadata_requirements as treated_plan

SCHEMA_VERSION = "1"


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
) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)

    control_dir = output_dir / "controls"
    treated_dir = output_dir / "treated"
    history_dir = output_dir / "control_history"
    external_dir = output_dir / "control_external_sources"
    identity_dir = output_dir / "control_identity"

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
        },
        "component_outputs": {
            "controls": str(control_dir),
            "treated": str(treated_dir),
            "control_history": str(history_dir),
            "control_external_sources": str(external_dir),
            "control_identity": str(identity_dir),
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
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    result = build(
        events_path=args.events,
        frozen_market_requirements_path=args.frozen_market_requirements,
        planning_universe_path=args.planning_universe,
        canonical_g2_identity_manifest_path=args.canonical_g2_identity_manifest,
        output_dir=args.output_dir,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
