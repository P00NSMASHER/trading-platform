from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import real_data_release_sprint as sprint


def _write_json(path: Path, obj: dict) -> None:
    path.write_text(json.dumps(obj, indent=2) + "\n", encoding="utf-8")


def test_freeze_real_repository_requirements(tmp_path: Path):
    out = tmp_path / "freeze"
    result = sprint.freeze_requirements(
        source_date_requirements=ROOT / "data/processed/coverage_plan_real/source_date_requirements.csv",
        event_exchange_resolutions=ROOT / "data/processed/authorized_input_real/event_exchange_resolutions.csv",
        outdir=out,
    )
    assert result["counts"]["core_equity_source_date_rows"] == 828
    assert result["counts"]["option_source_date_rows"] == 828
    assert result["counts"]["total_required_g2_source_date_rows"] == 1656
    assert result["counts"]["legacy_conditional_itch_market_date_rows"] == 414
    assert result["counts"]["g3_confirmed_nasdaq_event_rows"] == 80
    assert result["counts"]["g3_confirmed_nasdaq_itch_4_1_event_rows"] == 35
    assert result["counts"]["g3_confirmed_nasdaq_itch_5_0_event_rows"] == 45
    assert (out / "market_source_inventory.template.csv").exists()
    rows = list(csv.DictReader((out / "market_source_inventory.template.csv").open()))
    assert len(rows) == 1656
    assert {r["status"] for r in rows} == {"MISSING_SOURCE"}
    itch = list(csv.DictReader((out / "g2_itch_event_requirements.csv").open()))
    assert len(itch) == 80
    assert sum(r["source_family"] == "nasdaq_itch_4_1_decoded" for r in itch) == 35
    assert sum(r["source_family"] == "nasdaq_itch_5_0_decoded" for r in itch) == 45
    assert {r["format_version"] for r in itch} == {"ITCH-4.1", "ITCH-5.0"}


def test_refresh_coverage_uses_current_metadata_subgates(tmp_path: Path):
    frozen = tmp_path / "frozen"
    sprint.freeze_requirements(
        source_date_requirements=ROOT / "data/processed/coverage_plan_real/source_date_requirements.csv",
        event_exchange_resolutions=ROOT / "data/processed/authorized_input_real/event_exchange_resolutions.csv",
        outdir=frozen,
    )
    coverage = json.loads((ROOT / "data/processed/coverage_plan_real/coverage_summary.json").read_text())
    coverage_path = tmp_path / "coverage.json"
    _write_json(coverage_path, coverage)
    gates_path = tmp_path / "gates.csv"

    updated = sprint.refresh_coverage(
        coverage_summary_path=coverage_path,
        metadata_readiness_path=ROOT / "data/processed/authorized_input_real/metadata_readiness_summary.json",
        metadata_quality_path=ROOT / "data/processed/authorized_input_real/metadata_quality_summary.json",
        requirements_manifest_path=frozen / "requirements_manifest.json",
        unresolved_gates_path=gates_path,
    )
    assert updated["metadata_gate_overlay"]["G1_ANNOUNCEMENT_TIMES"] == "READY_WITH_REVIEWED_EXCLUSIONS"
    assert updated["metadata_gate_overlay"]["G3_PRIMARY_LISTING_HISTORY"] == "READY"
    assert updated["metadata_gate_overlay"]["G4_SHARES_OUTSTANDING"] == "READY_WITH_REVIEWED_EXCLUSIONS"
    assert updated["metadata_gate_overlay"]["G5_MATCHED_CONTROL_UNIVERSE"] == "READY_WITH_REVIEWED_EXCLUSIONS"
    assert "G2_REAL_MARKET_DATA" in updated["blocking_gates"]
    assert "G1_EXACT_TIMING_ANALYSIS" in updated["blocking_gates"]
    assert "G2_STABLE_SECURITY_IDENTITY" in updated["blocking_gates"]
    assert updated["security_identity_gate"]["baseline_identity_unverified_count"] == 3654
    assert "G5_MODEL_EVALUATION_CONTROLS" in updated["blocking_gates"]
    assert updated["g3_conditioned_itch_event_rows"] == 80
    assert updated["missing_exact_announcement_timestamps"] == 136


def test_status_never_labels_missing_real_sources_complete(tmp_path: Path):
    req = tmp_path / "req.json"
    coverage = tmp_path / "coverage.json"
    metadata = tmp_path / "metadata.json"
    quality = tmp_path / "quality.json"
    out = tmp_path / "status.json"

    _write_json(req, {
        "counts": {
            "core_equity_source_date_rows": 828,
            "option_source_date_rows": 828,
            "g3_confirmed_nasdaq_event_rows": 80,
        }
    })
    _write_json(coverage, {
        "contract_audit": {
            "real_authorized_required_rows_covered": 0,
            "ready_for_real_backfill": False,
        },
        "ready_for_non_synthetic_champion_challenger_comparison": False,
    })
    _write_json(metadata, {
        "event_count": 174,
        "announcement_exact_resolved": 0,
        "announcement_events_excluded": 174,
        "announcement_unresolved": 0,
        "control_dates_resolved": 0,
        "ready_g1_exact_timing_analysis": False,
        "ready_g5_model_evaluation_controls": False,
        "ready_for_non_synthetic_model_evaluation_metadata": False,
    })
    _write_json(quality, {
        "quality_cleared_for_non_synthetic_model_evaluation": False,
    })
    status = sprint.build_status(
        requirements_manifest_path=req,
        coverage_summary_path=coverage,
        metadata_readiness_path=metadata,
        metadata_quality_path=quality,
        outpath=out,
    )
    by_step = {x["step"]: x["status"] for x in status["steps"]}
    assert by_step[1] == "PASS"
    assert by_step[2] == "PASS"
    assert by_step[3] == "PASS"
    assert by_step[4] == "PASS"
    assert by_step[5] == "SOURCE_BLOCKED"
    assert by_step[6] == "PASS"
    assert by_step[7] == "SOURCE_BLOCKED"
    assert by_step[8] == "SOURCE_BLOCKED"
    assert by_step[9] == "SOURCE_BLOCKED"
    assert by_step[10] == "SOURCE_BLOCKED"
    assert by_step[11] == "DEPENDENCY_BLOCKED"
    assert by_step[12] == "DEPENDENCY_BLOCKED"
    assert status["all_12_genuinely_complete"] is False


def test_step9_reviewed_exclusions_never_count_as_exact_completion(tmp_path: Path):
    req = tmp_path / "req.json"
    coverage = tmp_path / "coverage.json"
    metadata = tmp_path / "metadata.json"
    quality = tmp_path / "quality.json"
    out = tmp_path / "status.json"

    _write_json(req, {
        "counts": {
            "core_equity_source_date_rows": 828,
            "option_source_date_rows": 828,
            "g3_confirmed_nasdaq_event_rows": 80,
        }
    })
    _write_json(coverage, {
        "contract_audit": {
            "real_authorized_required_rows_covered": 0,
            "ready_for_real_backfill": False,
        },
        "ready_for_non_synthetic_champion_challenger_comparison": False,
    })
    _write_json(metadata, {
        "event_count": 174,
        "announcement_exact_resolved": 33,
        "announcement_events_excluded": 141,
        "announcement_unresolved": 0,
        "control_dates_resolved": 0,
        "ready_g1_exact_timing_analysis": True,
        "ready_g5_model_evaluation_controls": False,
        "ready_for_non_synthetic_model_evaluation_metadata": False,
    })
    _write_json(quality, {
        "quality_cleared_for_non_synthetic_model_evaluation": False,
    })

    status = sprint.build_status(
        requirements_manifest_path=req,
        coverage_summary_path=coverage,
        metadata_readiness_path=metadata,
        metadata_quality_path=quality,
        outpath=out,
    )
    step9 = next(x for x in status["steps"] if x["step"] == 9)
    assert step9["status"] == "SOURCE_BLOCKED"
    assert step9["evidence"] == (
        "exact timestamps=33/174; reviewed fail-closed exclusions=141; "
        "exclusions do not satisfy Step 9"
    )


def test_committed_status_matches_current_authoritative_inputs(tmp_path: Path):
    generated = sprint.build_status(
        requirements_manifest_path=ROOT / "data/processed/real_data_release_sprint/requirements_manifest.json",
        coverage_summary_path=ROOT / "data/processed/coverage_plan_real/coverage_summary.json",
        metadata_readiness_path=ROOT / "data/processed/authorized_input_real/metadata_readiness_summary.json",
        metadata_quality_path=ROOT / "data/processed/authorized_input_real/metadata_quality_summary.json",
        outpath=tmp_path / "step_status.json",
    )
    committed = json.loads(
        (ROOT / "data/processed/real_data_release_sprint/step_status.json").read_text(encoding="utf-8")
    )
    assert generated == committed


def test_security_identity_gate_prevents_release_unlock_when_other_inputs_are_ready(tmp_path: Path, monkeypatch):
    identity = tmp_path / "identity.json"
    _write_json(identity, {
        "schema_version": "1",
        "state": {
            "event_count": 174,
            "event_date_identity_verified_count": 174,
            "required_symbol_date_count": 3828,
            "baseline_identity_unverified_count": 3654,
            "ready_for_non_synthetic_market_join": False,
        },
    })
    monkeypatch.setattr(sprint, "DEFAULT_SECURITY_IDENTITY_PATH", identity)
    monkeypatch.setattr(sprint, "_security_identity_status", lambda path=identity: {
        "ready_for_non_synthetic_market_join": False,
        "event_count": 174,
        "event_date_identity_verified_count": 174,
        "required_symbol_date_count": 3828,
        "baseline_identity_unverified_count": 3654,
        "sha256": sprint._sha256(identity),
    })
    req = tmp_path / "req.json"; coverage = tmp_path / "coverage.json"; metadata = tmp_path / "metadata.json"; quality = tmp_path / "quality.json"; out = tmp_path / "status.json"
    _write_json(req, {"counts": {"core_equity_source_date_rows": 828, "option_source_date_rows": 828, "g3_confirmed_nasdaq_event_rows": 80}})
    _write_json(coverage, {"event_count": 174, "unique_symbol_date_pairs": 3828, "contract_audit": {"real_authorized_required_rows_covered": 1656, "ready_for_real_backfill": True}, "ready_for_non_synthetic_champion_challenger_comparison": True})
    _write_json(metadata, {"event_count": 174, "announcement_exact_resolved": 174, "announcement_events_excluded": 0, "announcement_unresolved": 0, "control_dates_resolved": 72, "ready_g1_exact_timing_analysis": True, "ready_g5_model_evaluation_controls": True, "ready_for_non_synthetic_model_evaluation_metadata": True})
    _write_json(quality, {"quality_cleared_for_non_synthetic_model_evaluation": True})
    status = sprint.build_status(requirements_manifest_path=req, coverage_summary_path=coverage, metadata_readiness_path=metadata, metadata_quality_path=quality, outpath=out)
    by_step = {row["step"]: row for row in status["steps"]}
    assert by_step[11]["status"] == "DEPENDENCY_BLOCKED"
    assert by_step[12]["status"] == "DEPENDENCY_BLOCKED"
    assert "baseline identity unverified=3654/3828" in by_step[11]["evidence"]
