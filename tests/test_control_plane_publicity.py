from __future__ import annotations

import json
from pathlib import Path

import pytest

from control_plane import integrity, junas, publicity, registry, signature_trust, storage


def _pending(tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    source = root / "document.txt"
    source.write_text("historical public document\n", encoding="utf-8")
    control = root / "private_runtime" / "control"
    receipt = junas.ingest_document(
        source=source,
        control_dir=control,
        source_id="doc-1",
        source_contract_sha256="a" * 64,
        data_classification="public_official_data",
        policy_metadata={"license_reference": "https://example.invalid/public-release"},
    )
    assert receipt["state"] == "PUBLICITY_PENDING"
    evidence = root / "public-release-evidence.txt"
    evidence.write_text("archived primary public release\n", encoding="utf-8")
    claim = publicity.build_clearance(
        control_dir=control,
        information_id=receipt["information_id"],
        public_release_evidence=evidence,
        public_release_reference="https://example.invalid/public-release",
        public_release_timestamp_utc="2026-09-25T12:00:00Z",
    )
    claim_path = root / "private_runtime" / "clearance.json"
    publicity.write_clearance(claim_path, claim)
    signature = root / "private_runtime" / "clearance.json.sig"
    signature.write_bytes(b"fake-signature")
    trust_dir = tmp_path / "external-trust"
    trust_dir.mkdir()
    allowed = trust_dir / "allowed_signers"
    allowed.write_text("publicity-reviewer ssh-ed25519 AAAATEST\n", encoding="utf-8")
    return root, control, receipt, evidence, claim, claim_path, signature, allowed


def _good_signature(monkeypatch, calls: list | None = None):
    def run(args, **kwargs):
        if calls is not None:
            calls.append((args, kwargs))
        class Result:
            returncode = 0
            stdout = b"Good signature"
            stderr = b""
        return Result()
    monkeypatch.setattr(signature_trust.subprocess, "run", run)


def test_clearance_build_binds_exact_pending_subject(tmp_path: Path):
    _, control, receipt, evidence, claim, _, _, _ = _pending(tmp_path)
    assert claim["information_id"] == receipt["information_id"]
    assert claim["content_sha256"] == receipt["holding_sha256"]
    assert claim["holding_sha256"] == receipt["holding_sha256"]
    assert claim["preclearance_event_head"] == registry.event_head(control / "control.sqlite", receipt["information_id"])
    assert claim["public_release_evidence_sha256"] == storage.sha256_file(evidence)
    assert claim["signature_namespace"] == publicity.DEFAULT_NAMESPACE
    assert claim["model_plane_eligible"] is False


def test_direct_publicity_clearance_event_without_verification_is_rejected(tmp_path: Path):
    _, control, receipt, _, _, _, _, _ = _pending(tmp_path)
    with pytest.raises(ValueError, match="missing verification detail"):
        registry.append_event(
            control / "control.sqlite",
            receipt["information_id"],
            "PUBLICITY_CLEARED",
            "PUBLICITY_CLEARED",
            {},
        )
    assert registry.current_state(control / "control.sqlite", receipt["information_id"]) == "PUBLICITY_PENDING"


def test_allowed_signers_hash_checked_before_signature_verification(tmp_path: Path, monkeypatch):
    root, control, receipt, evidence, _, claim_path, signature, allowed = _pending(tmp_path)
    called = False
    def no_run(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("ssh-keygen must not run before the external trust hash matches")
    monkeypatch.setattr(signature_trust.subprocess, "run", no_run)
    with pytest.raises(ValueError, match="allowed-signers hash mismatch"):
        publicity.verify_and_apply_clearance(
            root=root,
            control_dir=control,
            clearance=claim_path,
            signature=signature,
            public_release_evidence=evidence,
            allowed_signers=allowed,
            expected_allowed_signers_sha256="0" * 64,
            identity="publicity-reviewer",
        )
    assert called is False
    assert registry.current_state(control / "control.sqlite", receipt["information_id"]) == "PUBLICITY_PENDING"


def test_bad_signature_cannot_clear_publicity(tmp_path: Path, monkeypatch):
    root, control, receipt, evidence, _, claim_path, signature, allowed = _pending(tmp_path)
    def bad_run(*args, **kwargs):
        class Result:
            returncode = 1
            stdout = b""
            stderr = b"bad signature"
        return Result()
    monkeypatch.setattr(signature_trust.subprocess, "run", bad_run)
    with pytest.raises(PermissionError, match="signature verification failed"):
        publicity.verify_and_apply_clearance(
            root=root,
            control_dir=control,
            clearance=claim_path,
            signature=signature,
            public_release_evidence=evidence,
            allowed_signers=allowed,
            expected_allowed_signers_sha256=storage.sha256_file(allowed),
            identity="publicity-reviewer",
        )
    assert registry.current_state(control / "control.sqlite", receipt["information_id"]) == "PUBLICITY_PENDING"


def test_verified_clearance_advances_and_archives_without_model_eligibility(tmp_path: Path, monkeypatch):
    root, control, receipt, evidence, _, claim_path, signature, allowed = _pending(tmp_path)
    calls = []
    _good_signature(monkeypatch, calls)
    result = publicity.verify_and_apply_clearance(
        root=root,
        control_dir=control,
        clearance=claim_path,
        signature=signature,
        public_release_evidence=evidence,
        allowed_signers=allowed,
        expected_allowed_signers_sha256=storage.sha256_file(allowed),
        identity="publicity-reviewer",
    )
    assert result["state"] == "PUBLICITY_CLEARED"
    assert result["signature_verified"] is True
    assert result["model_plane_eligible"] is False
    assert any("-Y" in args and "verify" in args for args, _ in calls)
    archived = control / "publicity_clearances" / result["clearance_sha256"]
    assert storage.sha256_file(archived / "clearance.json") == result["clearance_sha256"]
    assert (archived / "clearance.json.sig").read_bytes() == b"fake-signature"
    report = integrity.verify_control_plane(control / "control.sqlite", control)
    assert report["publicity_clearance_artifacts_valid"] is True
    assert report["ok"] is True
    assert not (control / "model").exists()
    assert not (control / "features").exists()


def test_signed_claim_for_different_bytes_is_rejected(tmp_path: Path, monkeypatch):
    root, control, receipt, evidence, claim, claim_path, signature, allowed = _pending(tmp_path)
    claim["content_sha256"] = "0" * 64
    publicity.write_clearance(claim_path, claim)
    _good_signature(monkeypatch)
    with pytest.raises(ValueError, match="content_sha256 does not match"):
        publicity.verify_and_apply_clearance(
            root=root,
            control_dir=control,
            clearance=claim_path,
            signature=signature,
            public_release_evidence=evidence,
            allowed_signers=allowed,
            expected_allowed_signers_sha256=storage.sha256_file(allowed),
            identity="publicity-reviewer",
        )
    assert registry.current_state(control / "control.sqlite", receipt["information_id"]) == "PUBLICITY_PENDING"


def test_public_release_evidence_hash_must_match_signed_claim(tmp_path: Path, monkeypatch):
    root, control, receipt, evidence, _, claim_path, signature, allowed = _pending(tmp_path)
    evidence.write_text("changed after clearance was built\n", encoding="utf-8")
    _good_signature(monkeypatch)
    with pytest.raises(ValueError, match="evidence hash does not match"):
        publicity.verify_and_apply_clearance(
            root=root,
            control_dir=control,
            clearance=claim_path,
            signature=signature,
            public_release_evidence=evidence,
            allowed_signers=allowed,
            expected_allowed_signers_sha256=storage.sha256_file(allowed),
            identity="publicity-reviewer",
        )
    assert registry.current_state(control / "control.sqlite", receipt["information_id"]) == "PUBLICITY_PENDING"


def test_clearance_replay_is_rejected_after_event_head_advances(tmp_path: Path, monkeypatch):
    root, control, receipt, evidence, _, claim_path, signature, allowed = _pending(tmp_path)
    _good_signature(monkeypatch)
    kwargs = dict(
        root=root,
        control_dir=control,
        clearance=claim_path,
        signature=signature,
        public_release_evidence=evidence,
        allowed_signers=allowed,
        expected_allowed_signers_sha256=storage.sha256_file(allowed),
        identity="publicity-reviewer",
    )
    publicity.verify_and_apply_clearance(**kwargs)
    with pytest.raises(ValueError, match="not currently PUBLICITY_PENDING"):
        publicity.verify_and_apply_clearance(**kwargs)
    assert registry.current_state(control / "control.sqlite", receipt["information_id"]) == "PUBLICITY_CLEARED"


def test_publicity_signing_key_must_be_outside_repository(tmp_path: Path, monkeypatch):
    root, _, _, _, _, claim_path, _, _ = _pending(tmp_path)
    key = root / "private-key"
    key.write_text("fake", encoding="utf-8")
    called = False
    def no_run(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("ssh-keygen must not run with a repository-local private key")
    monkeypatch.setattr(signature_trust.subprocess, "run", no_run)
    with pytest.raises(ValueError, match="outside the repository root"):
        publicity.sign_clearance(root=root, clearance=claim_path, private_key=key)
    assert called is False
