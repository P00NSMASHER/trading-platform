from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import g5_control_acquisition_planner as acquisition
import g5_control_history_requirements as history
import g5_control_identity_requirements as identity


def _build_real(tmp_path: Path):
    control_dir = tmp_path / "controls"
    history_dir = tmp_path / "history"
    identity_dir = tmp_path / "identity"

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

    history_summary = history.build(
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
    return history_summary, identity_summary, identity_dir


def test_real_primary_control_identity_leads_are_truthfully_accounted(tmp_path: Path):
    _history, summary, _out = _build_real(tmp_path)

    assert summary["primary_candidate_symbol_date_count"] == 216
    exact = summary["primary_candidate_exact_sample_mapping"]
    assert exact == {
        "unique": 51,
        "ambiguous": 0,
        "missing": 165,
    }

    assert summary["g5_dates_resolved_change"] == 0
    assert summary["release_claimed"] is False
    assert summary["policy"]["samplefirms_retrospective_labels_used"] is False
    assert (
        summary["policy"][
            "samplefirms_exact_mapping_is_automatically_canonical_identity"
        ]
        is False
    )


def test_identity_history_count_reconciles_with_control_history_plan(tmp_path: Path):
    history_summary, summary, out = _build_real(tmp_path)

    assert summary["control_history_symbol_date_count"] == (
        history_summary["unique_control_history_symbol_date_pairs"]
    )

    status_total = sum(summary["status_counts"].values())
    assert status_total == summary["control_history_symbol_date_count"]

    assert summary["canonical_g2_verified_reuse_count"] > 0
    assert summary["canonical_g2_unverified_overlap_count"] > 0
    assert summary["new_g5_identity_evidence_required_count"] > 0
    assert summary["identity_acquisition_queue_count"] == (
        summary["control_history_symbol_date_count"]
        - summary["canonical_g2_verified_reuse_count"]
    )

    rows = list(
        csv.DictReader(
            (out / "g5_control_identity_requirements.csv").open(
                encoding="utf-8"
            )
        )
    )
    queue = list(
        csv.DictReader(
            (out / "g5_control_identity_acquisition_queue.csv").open(
                encoding="utf-8"
            )
        )
    )
    assert len(rows) == summary["control_history_symbol_date_count"]
    assert len(queue) == summary["identity_acquisition_queue_count"]
    assert all(
        row["identity_status"] != "REUSE_CANONICAL_G2_VERIFIED_IDENTITY"
        for row in queue
    )


def test_exact_samplefirms_mapping_never_uses_retrospective_labels(tmp_path: Path):
    _history, summary, out = _build_real(tmp_path)

    rows = list(
        csv.DictReader(
            (out / "g5_control_identity_requirements.csv").open(
                encoding="utf-8"
            )
        )
    )
    exact = [
        row
        for row in rows
        if row["samplefirms_exact_mapping_status"]
        == "UNIQUE_EXACT_DATE_MAPPING_AVAILABLE"
    ]
    assert exact
    assert all(row["samplefirms_permno"] for row in exact)
    assert all(
        row["identity_status"]
        in {
            "REUSE_CANONICAL_G2_VERIFIED_IDENTITY",
            "OVERLAPS_CANONICAL_G2_IDENTITY_QUEUE",
            "PUBLIC_EXACT_MAPPING_AVAILABLE_REQUIRES_ADMISSION",
        }
        for row in exact
    )

    saved = json.loads(
        (out / "g5_control_identity_requirement_summary.json").read_text(
            encoding="utf-8"
        )
    )
    assert saved["policy"]["samplefirms_retrospective_labels_used"] is False
    assert saved["policy"]["identity_requirements_are_g5_evidence"] is False
