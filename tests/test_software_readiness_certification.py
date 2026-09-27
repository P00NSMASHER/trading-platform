from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import software_readiness_certification as cert


def test_current_repo_can_be_software_ready_while_real_data_is_pending(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        cert.hardening,
        "self_check",
        lambda cfg: {
            "ok": True,
            "audit_sha256": "a" * 64,
            "model_bundle": {"sha256": "0c8c16c9be734152c0018aa40e576fe4db9f4621359fafe521465890f9945616"},
        },
    )
    out = tmp_path / "cert.json"
    result = cert.certify(
        ROOT,
        runtime_config=Path("config/runtime.demo.toml"),
        output_path=out,
        run_tests=False,
    )
    assert result["software_ready"] is True
    assert result["real_data_validated"] is False
    assert result["overall_status"] == "SOFTWARE_READY_REAL_DATA_PENDING"
    assert result["real_data_state"]["coverage"]["required_source_date_rows"] == 1656
    assert result["real_data_state"]["coverage"]["covered_real_source_date_rows"] == 0
    assert result["semantics"]["automatic_promotion_permitted"] is False
    assert result["semantics"]["active_champion_modification_permitted"] is False
    assert out.exists()


def test_real_data_validation_requires_replay_release_not_only_coarse_metadata(tmp_path: Path):
    state = cert._real_data_state(ROOT)
    assert state["validated"] is False
    assert state["gates"]["G3_PRIMARY_LISTING_HISTORY"] is True
    assert state["gates"]["G4_SHARES_OUTSTANDING"] is True
    assert state["gates"]["G1_EXACT_TIMING_ANALYSIS"] is False
    assert state["gates"]["G2_REAL_MARKET_DATA"] is False
    assert state["gates"]["G5_MODEL_EVALUATION_CONTROLS"] is False
    assert state["gates"]["REAL_DATA_REPLAY"] is False
    assert state["gates"]["EVALUATION_RELEASE"] is False


def test_missing_required_software_forces_software_not_ready(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(cert, "REQUIRED_SOFTWARE", cert.REQUIRED_SOFTWARE + ("src/does-not-exist.py",))
    result = cert.certify(
        ROOT,
        runtime_config=Path("config/runtime.demo.toml"),
        output_path=tmp_path / "cert.json",
        run_tests=False,
    )
    assert result["software_ready"] is False
    assert result["overall_status"] == "SOFTWARE_NOT_READY"
    failure_ids = {x["check_id"] for x in result["software_failures"]}
    assert "SOFTWARE_COMPONENTS" in failure_ids


def test_failed_hostile_suite_forces_software_not_ready(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        cert,
        "run_hostile_suite",
        lambda root: {
            "ok": False,
            "returncode": 1,
            "passed_count": 99,
            "test_files": ["fixture"],
            "missing_test_files": [],
            "stdout_tail": "1 failed",
        },
    )
    result = cert.certify(
        ROOT,
        runtime_config=Path("config/runtime.demo.toml"),
        output_path=tmp_path / "cert.json",
        run_tests=True,
    )
    assert result["software_ready"] is False
    assert any(x["check_id"] == "HOSTILE_REGRESSION_SUITE" for x in result["software_failures"])


def test_hostile_suite_defines_all_required_categories():
    expected = {
        "temporal_and_point_in_time",
        "control_and_metadata_integrity",
        "model_and_release_isolation",
        "intake_and_replay_fail_closed",
        "control_plane_and_runtime_security",
    }
    assert set(cert.HOSTILE_TEST_GROUPS) == expected
    flattened = {p for group in cert.HOSTILE_TEST_GROUPS.values() for p in group}
    for required in (
        "tests/test_feature_engine.py",
        "tests/test_metadata_resolver.py",
        "tests/test_matched_control_generator.py",
        "tests/test_model_training_harness.py",
        "tests/test_evaluation_release_controller.py",
        "tests/test_real_data_replay.py",
        "tests/test_licensed_data_intake.py",
        "tests/test_control_plane_adversarial.py",
        "tests/test_deployment_hardening.py",
    ):
        assert required in flattened
