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
    root = tmp_path / "repo"
    root.mkdir()
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
        root=root,
        attestation_path=att_path,
        signature=sig,
        allowed_signers=allowed,
        expected_allowed_signers_sha256=_sha(allowed),
        expected_drift_trust_root_sha256="1" * 64,
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
                "signature_namespace": ra.DEFAULT_NAMESPACE,
                "research_use_only": True,
                "prohibited_capabilities": [],
            },
            expected_drift_trust_root_sha256="1" * 64,
        )


def test_checkout_verification_rejects_wrong_signature_namespace(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(ra, "_require_clean_tracked_tree", lambda root: None)
    with pytest.raises(ValueError, match="signature_namespace"):
        ra.verify_attestation_against_checkout(
            root=tmp_path,
            attestation={
                "schema_version": "1",
                "signature_namespace": "other-purpose",
                "research_use_only": True,
                "prohibited_capabilities": [
                    "broker_connectivity",
                    "order_generation",
                    "trade_recommendations",
                    "position_sizing",
                    "expected_return_outputs",
                ],
            },
        )


def test_signing_key_must_be_outside_repository(tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    att = root / "attestation.json"
    att.write_text(
        json.dumps({"signature_namespace": ra.DEFAULT_NAMESPACE}) + "\n",
        encoding="utf-8",
    )
    key = root / "release_key"
    key.write_text("fake", encoding="utf-8")
    with pytest.raises(ValueError, match="outside the repository root"):
        ra.sign_attestation(
            root=root,
            attestation=att,
            private_key=key,
        )


def test_allowed_signers_must_be_outside_repository(tmp_path: Path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    att = root / "attestation.json"
    att.write_text(
        json.dumps({"signature_namespace": ra.DEFAULT_NAMESPACE}) + "\n",
        encoding="utf-8",
    )
    sig = root / "attestation.json.sig"
    sig.write_text("fake", encoding="utf-8")
    allowed = root / "allowed_signers"
    allowed.write_text("owner ssh-ed25519 AAAATEST\n", encoding="utf-8")

    with pytest.raises(ValueError, match="outside the repository root"):
        ra.verify_signed_attestation(
            root=root,
            attestation_path=att,
            signature=sig,
            allowed_signers=allowed,
            expected_allowed_signers_sha256=_sha(allowed),
            expected_drift_trust_root_sha256="1" * 64,
            identity="owner",
        )


def test_checkout_verification_requires_independent_drift_trust_root(tmp_path: Path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    monkeypatch.setattr(ra, "_require_clean_tracked_tree", lambda root: None)
    monkeypatch.setattr(ra, "_git", lambda root, *args: "abc123")
    monkeypatch.setattr(ra, "tracked_tree_sha256", lambda root: ("treehash", 1))

    files = {
        "RELEASE_MANIFEST.json": b"manifest",
        "SHA256SUMS": b"sums",
        "config/release_drift_allowlist.json": b"allowlist",
        "data/processed/model_demo/model_bundle.joblib": b"champion",
    }
    for rel, data in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

    attestation = {
        "schema_version": "1",
        "signature_namespace": ra.DEFAULT_NAMESPACE,
        "research_use_only": True,
        "prohibited_capabilities": [
            "broker_connectivity",
            "order_generation",
            "trade_recommendations",
            "position_sizing",
            "expected_return_outputs",
        ],
        "git_commit": "abc123",
        "tracked_tree_sha256": "treehash",
        "tracked_file_count": 1,
        "historical_release_manifest_sha256": _sha(root / "RELEASE_MANIFEST.json"),
        "sha256sums_sha256": _sha(root / "SHA256SUMS"),
        "drift_allowlist_sha256": _sha(root / "config/release_drift_allowlist.json"),
        "champion_sha256": _sha(root / "data/processed/model_demo/model_bundle.joblib"),
    }

    with pytest.raises(ValueError, match="independently recorded trust root"):
        ra.verify_attestation_against_checkout(
            root=root,
            attestation=attestation,
            expected_drift_trust_root_sha256="0" * 64,
        )
