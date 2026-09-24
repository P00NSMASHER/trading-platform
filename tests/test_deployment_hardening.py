from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import deployment_hardening as dh
from deployment_hardening import (
    backup_database,
    database_integrity_report,
    load_runtime_config,
    recovery_drill,
    restore_database,
    self_check,
    sha256_file,
    verify_model_bundle,
)

CONFIG = ROOT / "config" / "runtime.demo.toml"
MODEL = ROOT / "data" / "processed" / "model_demo" / "model_bundle.joblib"
DB = ROOT / "data" / "processed" / "case_demo" / "cases.sqlite"
EXPECTED_MODEL_SHA256 = "0c8c16c9be734152c0018aa40e576fe4db9f4621359fafe521465890f9945616"


def _write_config(tmp_path: Path, **policy_overrides) -> Path:
    policy = {
        "research_use_only": True,
        "allow_network_bind": False,
        "allow_execution_integration": False,
        "allow_trade_outputs": False,
    }
    policy.update(policy_overrides)
    p = tmp_path / "runtime.toml"
    p.write_text(
        f'''[paths]\ncase_db = "{DB}"\nmodel_bundle = "{MODEL}"\ntraining_manifest = "{ROOT / 'data/processed/model_demo/training_manifest.json'}"\nbackup_dir = "{tmp_path / 'backups'}"\nexport_dir = "{tmp_path / 'exports'}"\naudit_dir = "{tmp_path / 'audit'}"\n\n[dashboard]\nhost = "127.0.0.1"\nport = 8765\n\n[integrity]\nexpected_model_sha256 = "{EXPECTED_MODEL_SHA256}"\n\n[policy]\nresearch_use_only = {str(policy['research_use_only']).lower()}\nallow_network_bind = {str(policy['allow_network_bind']).lower()}\nallow_execution_integration = {str(policy['allow_execution_integration']).lower()}\nallow_trade_outputs = {str(policy['allow_trade_outputs']).lower()}\n''',
        encoding="utf-8",
    )
    return p


def test_runtime_config_loads_and_is_loopback_only():
    cfg = load_runtime_config(CONFIG)
    assert cfg.dashboard_host == "127.0.0.1"
    assert cfg.research_use_only is True
    assert cfg.allow_network_bind is False


@pytest.mark.parametrize(
    "override",
    [
        {"research_use_only": False},
        {"allow_network_bind": True},
        {"allow_execution_integration": True},
        {"allow_trade_outputs": True},
    ],
)
def test_runtime_policy_fails_closed(tmp_path: Path, override: dict):
    with pytest.raises(ValueError):
        load_runtime_config(_write_config(tmp_path, **override))


def test_model_bundle_verification_passes_and_has_no_trade_keys():
    r = verify_model_bundle(MODEL, expected_sha256=EXPECTED_MODEL_SHA256)
    assert r["ok"] is True
    assert r["hash_matches_expected"] is True
    assert r["deserialization_attempted"] is True
    assert r["prohibited_trade_keys_present"] == []
    assert r["research_use_only"] is True


def test_model_bundle_hash_is_checked_before_deserialization(tmp_path: Path, monkeypatch):
    tampered = tmp_path / "tampered.joblib"
    shutil.copy2(MODEL, tampered)
    with tampered.open("ab") as f:
        f.write(b"tampered")

    called = False

    def _should_not_load(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("joblib.load must not run for a hash mismatch")

    monkeypatch.setattr(dh.joblib, "load", _should_not_load)
    r = verify_model_bundle(tampered, expected_sha256=EXPECTED_MODEL_SHA256)
    assert r["ok"] is False
    assert r["hash_matches_expected"] is False
    assert r["deserialization_attempted"] is False
    assert "refusing to deserialize" in r["load_error"]
    assert called is False


def test_model_bundle_requires_trusted_expected_hash_before_deserialization(monkeypatch):
    called = False

    def _should_not_load(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("joblib.load must not run without a trusted hash")

    monkeypatch.setattr(dh.joblib, "load", _should_not_load)
    r = verify_model_bundle(MODEL)
    assert r["ok"] is False
    assert r["deserialization_attempted"] is False
    assert "required before model deserialization" in r["load_error"]
    assert called is False


def test_database_integrity_and_review_chain_pass():
    model = verify_model_bundle(MODEL, expected_sha256=EXPECTED_MODEL_SHA256)
    r = database_integrity_report(DB, model_sha256=model["sha256"])
    assert r["ok"] is True
    assert r["sqlite_integrity"] is True
    assert r["foreign_keys_clean"] is True
    assert r["review_chains_valid"] is True


def test_backup_and_restore_preserve_logical_fingerprint(tmp_path: Path):
    model = verify_model_bundle(MODEL, expected_sha256=EXPECTED_MODEL_SHA256)
    source = tmp_path / "source.sqlite"
    shutil.copy2(DB, source)
    backup = backup_database(source, tmp_path / "backups", model_sha256=model["sha256"])
    assert Path(backup["backup_path"]).exists()
    assert Path(backup["manifest_path"]).exists()
    restored = tmp_path / "restored.sqlite"
    rr = restore_database(
        Path(backup["backup_path"]),
        Path(backup["manifest_path"]),
        restored,
        model_sha256=model["sha256"],
    )
    assert rr["logical_fingerprint"] == backup["backup_logical_fingerprint"]
    assert database_integrity_report(restored, model_sha256=model["sha256"])["ok"] is True


def test_restore_rejects_corrupted_backup(tmp_path: Path):
    model = verify_model_bundle(MODEL, expected_sha256=EXPECTED_MODEL_SHA256)
    source = tmp_path / "source.sqlite"
    shutil.copy2(DB, source)
    backup = backup_database(source, tmp_path / "backups", model_sha256=model["sha256"])
    bp = Path(backup["backup_path"])
    bp.write_bytes(bp.read_bytes()[:512])
    with pytest.raises(ValueError, match="backup file hash mismatch"):
        restore_database(
            bp,
            Path(backup["manifest_path"]),
            tmp_path / "restored.sqlite",
            model_sha256=model["sha256"],
        )


def test_full_self_check_passes_and_has_audit_hash():
    r = self_check(load_runtime_config(CONFIG))
    assert r["ok"] is True
    assert len(r["audit_sha256"]) == 64
    assert r["case_database"]["review_chains_valid"] is True


def test_recovery_drill_detects_corruption_and_preserves_source():
    before = sha256_file(DB)
    r = recovery_drill(load_runtime_config(CONFIG))
    after = sha256_file(DB)
    assert r["ok"] is True
    assert r["deliberate_corruption_detected"] is True
    assert r["source_database_unchanged"] is True
    assert before == after


def test_lockfiles_pin_runtime_and_test_dependencies():
    runtime = (ROOT / "requirements.lock").read_text(encoding="utf-8")
    dev = (ROOT / "requirements-dev.lock").read_text(encoding="utf-8")
    for name in ("joblib", "numpy", "scipy", "scikit-learn", "threadpoolctl"):
        assert f"{name}==" in runtime
    assert "pytest==" in dev
