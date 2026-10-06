from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import g5_control_identity_gate as gate

REQ_HEADER = (
    "historical_symbol,trade_date,roles,identity_status,canonical_g2_overlap,"
    "canonical_permno,canonical_gvkey,samplefirms_permno,samplefirms_gvkey,"
    "samplefirms_exact_mapping_status,required_evidence,research_use_only\n"
)
STAGED_HEADER = (
    "historical_symbol,trade_date,permno,market_identifier,evidence_ids,"
    "source_references,authorization_references,research_use_only\n"
)


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _manifest(path: Path, verified: list[str]) -> Path:
    path.write_text(
        json.dumps(
            {
                "events": [
                    {
                        "historical_symbol": "AAA",
                        "permno": "11111",
                        "verified_required_dates": verified,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    return path


def _receipt(path: Path, staged: Path, staged_count: int) -> Path:
    path.write_text(
        json.dumps(
            {
                "research_use_only": True,
                "canonical_g2_write_performed": False,
                "canonical_g5_write_performed": False,
                "counts": {"g5_only_staged_verified_count": staged_count},
                "output_sha256": {"g5_only_staged_verified": _sha(staged)},
            }
        ),
        encoding="utf-8",
    )
    return path


def _requirements(tmp_path: Path) -> Path:
    return _write(
        tmp_path / "requirements.csv",
        REQ_HEADER
        + "AAA,2015-01-01,event_point,REUSE_CANONICAL_G2_VERIFIED_IDENTITY,"
        "CANONICAL_G2_VERIFIED,11111,1,,,NO_EXACT_DATE_MAPPING,,1\n"
        + "AAA,2015-01-02,prior_close,OVERLAPS_CANONICAL_G2_IDENTITY_QUEUE,"
        "CANONICAL_G2_UNVERIFIED,11111,1,,,NO_EXACT_DATE_MAPPING,"
        "DATED_STABLE_ID_CROSSWALK,1\n"
        + "BBB,2015-01-03,event_point,PUBLIC_EXACT_MAPPING_AVAILABLE_REQUIRES_ADMISSION,"
        "NONE,,,22222,2,UNIQUE_EXACT_DATE_MAPPING_AVAILABLE,"
        "ADMISSIBLE_DATE_SPECIFIC_STABLE_ID_EVIDENCE,1\n",
    )


def _staged(tmp_path: Path, permno: str = "22222") -> Path:
    return _write(
        tmp_path / "staged.csv",
        STAGED_HEADER
        + f"BBB,2015-01-03,{permno},BBB,E2,stocknames:sha,AUTHORIZED-TEST,1\n",
    )


def _build(tmp_path: Path, *, verified: list[str], staged_permno: str = "22222"):
    requirements = _requirements(tmp_path)
    manifest = _manifest(tmp_path / "g2.json", verified)
    staged = _staged(tmp_path, staged_permno)
    receipt = _receipt(tmp_path / "receipt.json", staged, 1)
    return gate.build(
        identity_requirements_path=requirements,
        canonical_g2_identity_manifest_path=manifest,
        g5_only_staged_verified_path=staged,
        g5_staging_receipt_path=receipt,
        output_path=tmp_path / "gate.json",
    )


def test_complete_g2_and_g5_identity_scope_is_ready(tmp_path: Path):
    result = _build(
        tmp_path, verified=["2015-01-01", "2015-01-02"]
    )
    assert result["ready_for_g5_control_identity"] is True
    assert result["state"]["required_symbol_date_count"] == 3
    assert result["state"]["verified_symbol_date_count"] == 3
    assert result["state"]["unresolved_symbol_date_count"] == 0
    assert result["state"]["g5_only_verified_count"] == 1
    assert result["release_claimed"] is False


def test_unpromoted_g2_overlap_keeps_gate_blocked(tmp_path: Path):
    result = _build(tmp_path, verified=["2015-01-01"])
    assert result["ready_for_g5_control_identity"] is False
    assert result["state"]["unresolved_symbol_date_count"] == 1
    assert result["state"]["unresolved_examples"] == ["AAA|2015-01-02"]


def test_staged_identity_must_be_hash_bound_to_receipt(tmp_path: Path):
    requirements = _requirements(tmp_path)
    manifest = _manifest(
        tmp_path / "g2.json", ["2015-01-01", "2015-01-02"]
    )
    staged = _staged(tmp_path)
    receipt = _receipt(tmp_path / "receipt.json", staged, 1)
    staged.write_text(staged.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(gate.G5ControlIdentityGateError, match="hash-bound"):
        gate.build(
            identity_requirements_path=requirements,
            canonical_g2_identity_manifest_path=manifest,
            g5_only_staged_verified_path=staged,
            g5_staging_receipt_path=receipt,
            output_path=tmp_path / "gate.json",
        )


def test_staged_identity_outside_g5_only_scope_fails_closed(tmp_path: Path):
    requirements = _requirements(tmp_path)
    manifest = _manifest(
        tmp_path / "g2.json", ["2015-01-01", "2015-01-02"]
    )
    staged = _write(
        tmp_path / "staged.csv",
        STAGED_HEADER
        + "BBB,2015-01-03,22222,BBB,E2,stocknames:b,AUTHORIZED-TEST,1\n"
        + "CCC,2015-01-04,33333,CCC,E3,stocknames:c,AUTHORIZED-TEST,1\n",
    )
    receipt = _receipt(tmp_path / "receipt.json", staged, 2)
    with pytest.raises(
        gate.G5ControlIdentityGateError, match="outside G5-only requirements"
    ):
        gate.build(
            identity_requirements_path=requirements,
            canonical_g2_identity_manifest_path=manifest,
            g5_only_staged_verified_path=staged,
            g5_staging_receipt_path=receipt,
            output_path=tmp_path / "gate.json",
        )


def test_staged_permno_must_match_existing_acquisition_hint(tmp_path: Path):
    with pytest.raises(gate.G5ControlIdentityGateError, match="acquisition hint"):
        _build(
            tmp_path,
            verified=["2015-01-01", "2015-01-02"],
            staged_permno="99999",
        )


def test_current_real_scope_remains_fail_closed_without_new_evidence(tmp_path: Path):
    import g5_control_acquisition_planner as acquisition
    import g5_control_history_requirements as history
    import g5_control_identity_requirements as identity

    control_dir = tmp_path / "controls"
    history_dir = tmp_path / "history"
    identity_dir = tmp_path / "identity"
    acquisition.build(
        events_path=ROOT / "data/processed/historical_events.csv",
        requirements_path=(
            ROOT / "data/processed/coverage_plan_real/source_date_requirements.csv"
        ),
        planning_universe_path=ROOT / "data/raw/hacked_earnings_jfe/SampleFirms.csv",
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
        primary_candidates_path=control_dir / "g5_primary_candidate_symbol_dates.csv",
        samplefirms_path=ROOT / "data/raw/hacked_earnings_jfe/SampleFirms.csv",
        canonical_g2_identity_manifest_path=(
            ROOT
            / "data/processed/security_identity_real/security_identity_manifest.json"
        ),
        output_dir=identity_dir,
    )

    staged = _write(tmp_path / "empty_staged.csv", STAGED_HEADER)
    receipt = _receipt(tmp_path / "receipt.json", staged, 0)
    result = gate.build(
        identity_requirements_path=(
            identity_dir / "g5_control_identity_requirements.csv"
        ),
        canonical_g2_identity_manifest_path=(
            ROOT
            / "data/processed/security_identity_real/security_identity_manifest.json"
        ),
        g5_only_staged_verified_path=staged,
        g5_staging_receipt_path=receipt,
        output_path=tmp_path / "gate.json",
    )
    state = result["state"]
    assert state["required_symbol_date_count"] == identity_summary[
        "control_history_symbol_date_count"
    ]
    assert state["unresolved_symbol_date_count"] == identity_summary[
        "identity_acquisition_queue_count"
    ]
    assert (
        state["canonical_g2_overlap_required_count"]
        + state["g5_only_required_count"]
        == identity_summary["identity_acquisition_queue_count"]
    )
    assert state["g5_only_required_count"] > 0
    assert state["canonical_g2_overlap_required_count"] > 0
    assert result["ready_for_g5_control_identity"] is False
