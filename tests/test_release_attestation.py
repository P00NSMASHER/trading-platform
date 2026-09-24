from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import release_attestation as ra


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_tracked_tree_digest_changes_with_file_content(tmp_path: Path, monkeypatch):
    a = tmp_path / "a.txt"
    b = tmp_path / "b.txt"
    a.write_text("a\n", encoding="utf-8")
    b.write_text("b\n", encoding="utf-8")
    monkeypatch.setattr(ra, "tracked_paths", lambda root: ["a.txt", "b.txt"])
    first, count = ra.tracked_tree_sha256(tmp_path)
    assert count == 2
    b.write_text("changed\n", encoding="utf-8")
    second, count2 = ra.tracked_tree_sha256(tmp_path)
    assert count2 == 2
    assert second != first


def test_allowed_signers_hash_checked_before_ssh_verification(tmp_path: Path, monkeypatch):
    att = tmp_path / "attestation.json"
    att.write_text("{}\n", encoding="utf-8")
    sig = tmp_path / "attestation.json.sig"
    sig.write_text("fake", encoding="utf-8")
    allowed = tmp_path / "allowed_signers"
    allowed.write_text("owner ssh-ed25519 AAAATEST\n", encoding="utf-8")

    called = False

    def _no_run(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("ssh-keygen must not run when allowed-signers hash mismatches")

    monkeypatch.setattr(ra.subprocess, "run", _no_run)
    with pytest.raises(ValueError, match="allowed-signers hash mismatch"):
        ra._verify_ssh_signature(
            attestation=att,
            signature=sig,
            allowed_signers=allowed,
            expected_allowed_signers_sha256="0" * 64,
            identity="owner",
            namespace=ra.DEFAULT_NAMESPACE,
        )
    assert called is False


def test_signature_verification_precedes_checkout_acceptance(tmp_path: Path, monkeypatch):
    att_path = tmp_path / "attestation.json"
    att_path.write_text(json.dumps({"signature_namespace": ra.DEFAULT_NAMESPACE}) + "\n", encoding="utf-8")
    sig = tmp_path / "attestation.json.sig"
    sig.write_text("fake", encoding="utf-8")
    allowed = tmp_path / "allowed_signers"
    allowed.write_text("owner ssh-ed25519 AAAATEST\n", encoding="utf-8")

    calls = []

    def _fake_run(args, **kwargs):
        calls.append(args)
        class R:
            returncode = 0
            stdout = b"Good signature"
            stderr = b""
        return R()

    monkeypatch.setattr(ra.subprocess, "run", _fake_run)
    monkeypatch.setattr(
        ra,
        "verify_attestation_against_checkout",
        lambda **kwargs: {"ok": True, "research_use_only": True},
    )
    result = ra.verify_signed_attestation(
        root=tmp_path,
        attestation_path=att_path,
        signature=sig,
        allowed_signers=allowed,
        expected_allowed_signers_sha256=_sha(allowed),
        identity="owner",
    )
    assert result["ok"] is True
    assert result["signature_verified"] is True
    assert any("-Y" in cmd and "verify" in cmd for cmd in calls)


def test_checkout_verification_rejects_missing_policy_prohibitions(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(ra, "_require_clean_tracked_tree", lambda root: None)
    with pytest.raises(ValueError, match="prohibited capabilities"):
        ra.verify_attestation_against_checkout(
            root=tmp_path,
            attestation={
                "schema_version": "1",
                "research_use_only": True,
                "prohibited_capabilities": [],
            },
        )
