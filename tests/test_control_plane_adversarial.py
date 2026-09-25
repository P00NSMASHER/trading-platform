from __future__ import annotations

import csv
import json
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import secret_scan
import verify_release_drift as drift
import evaluation_release_controller as erc
from case_evidence import ingest_case
from control_plane import (
    account_surveillance,
    lineage,
    registry,
    release_authority,
    signature_trust,
    storage,
)
from private_dashboard import DashboardConfig

EXPECTED_CHAMPION_SHA256 = "0c8c16c9be734152c0018aa40e576fe4db9f4621359fafe521465890f9945616"
MODEL_DIR = ROOT / "data" / "processed" / "model_demo"
SCORES = MODEL_DIR / "holdout_scores.csv"
FEATURES = ROOT / "data" / "examples" / "model_training_feature_vectors.csv"
CONTROLS = ROOT / "data" / "examples" / "model_training_matched_controls.csv"
BUNDLE = MODEL_DIR / "model_bundle.joblib"
TRAINING_MANIFEST = MODEL_DIR / "training_manifest.json"


def _admitted_information(tmp_path: Path) -> tuple[Path, str]:
    control = tmp_path / "control"
    source = tmp_path / "root.csv"
    source.write_text("x\n1\n", encoding="utf-8")
    snapshot = storage.receive_to_holding(source, control)
    reg = registry.register_information(
        control / "control.sqlite",
        domain="metadata",
        source_id="root-source",
        content_sha256=snapshot.sha256,
        size_bytes=snapshot.size_bytes,
        source_contract_sha256="a" * 64,
        data_classification="synthetic_fixture",
        record_kind="announcement_timestamp",
        source_family="synthetic_fixture",
    )
    iid = reg["information_id"]
    registry.append_event(control / "control.sqlite", iid, "RECEIVED", "RECEIVED")
    registry.add_location(
        control / "control.sqlite",
        iid,
        "HOLDING",
        storage.path_fingerprint(snapshot.path),
        snapshot.sha256,
    )
    registry.append_event(control / "control.sqlite", iid, "HELD", "HOLDING")
    registry.append_event(control / "control.sqlite", iid, "ADMITTED", "ADMITTED_STRUCTURED")
    return control, iid


def _case_db(tmp_path: Path) -> Path:
    db = tmp_path / "cases.sqlite"
    ingest_case(
        db_path=db,
        case_id="CASE-H001",
        sample_id="H001:TREATED",
        scores_csv=SCORES,
        feature_vectors=FEATURES,
        model_bundle=BUNDLE,
        matched_controls=CONTROLS,
        training_manifest=TRAINING_MANIFEST,
    )
    return db


def test_attack_direct_unstructured_holding_to_admitted_is_rejected(tmp_path: Path):
    source = tmp_path / "document.txt"
    source.write_text("unstructured\n", encoding="utf-8")
    control = tmp_path / "control"
    snapshot = storage.receive_to_holding(source, control)
    reg = registry.register_information(
        control / "control.sqlite",
        domain="unstructured",
        source_id="doc",
        content_sha256=snapshot.sha256,
        size_bytes=snapshot.size_bytes,
        source_contract_sha256="b" * 64,
        data_classification="public_official_data",
        record_kind="unstructured_document",
        source_family="fixture",
    )
    iid = reg["information_id"]
    registry.append_event(control / "control.sqlite", iid, "RECEIVED", "RECEIVED")
    registry.append_event(control / "control.sqlite", iid, "HELD", "HOLDING")

    with pytest.raises(ValueError, match="only exit"):
        registry.append_event(
            control / "control.sqlite",
            iid,
            "ADMITTED",
            "ADMITTED_STRUCTURED",
        )
    assert registry.current_state(control / "control.sqlite", iid) == "HOLDING"


def test_attack_forged_publicity_clearance_event_is_rejected(tmp_path: Path):
    source = tmp_path / "document.txt"
    source.write_text("public candidate\n", encoding="utf-8")
    control = tmp_path / "control"
    snapshot = storage.receive_to_holding(source, control)
    reg = registry.register_information(
        control / "control.sqlite",
        domain="unstructured",
        source_id="doc",
        content_sha256=snapshot.sha256,
        size_bytes=snapshot.size_bytes,
        source_contract_sha256="c" * 64,
        data_classification="public_official_data",
        record_kind="unstructured_document",
        source_family="fixture",
    )
    iid = reg["information_id"]
    registry.append_event(control / "control.sqlite", iid, "RECEIVED", "RECEIVED")
    registry.append_event(control / "control.sqlite", iid, "HELD", "HOLDING")
    registry.append_event(control / "control.sqlite", iid, "PUBLICITY_PENDING", "PUBLICITY_PENDING")

    with pytest.raises(ValueError, match="missing verification detail"):
        registry.append_event(
            control / "control.sqlite",
            iid,
            "PUBLICITY_CLEARED",
            "PUBLICITY_CLEARED",
            {"clearance_signature_verified": True},
        )
    assert registry.current_state(control / "control.sqlite", iid) == "PUBLICITY_PENDING"


def test_attack_lineage_parent_injection_is_detected(tmp_path: Path):
    control, iid = _admitted_information(tmp_path)
    source = tmp_path / "derived.txt"
    source.write_text("derived\n", encoding="utf-8")
    artifact = lineage.create_derived_artifact(
        source=source,
        control_dir=control,
        artifact_kind="fixture",
        transform_id="adversarial",
        transform_version="1",
        parents=[{"kind": "information", "id": iid}],
    )

    info = registry.get_information(control / "control.sqlite", iid)
    with sqlite3.connect(control / "control.sqlite") as con:
        con.execute(
            """INSERT INTO lineage_parent(
                child_artifact_id,parent_ordinal,parent_kind,parent_id,parent_event_head,parent_content_sha256
            ) VALUES (?,?,?,?,?,?)""",
            (
                artifact["artifact_id"],
                999,
                "information",
                iid,
                registry.event_head(control / "control.sqlite", iid),
                info["content_sha256"],
            ),
        )

    with pytest.raises(ValueError, match="manifest and registry disagree"):
        lineage.verify_recursive(control_dir=control, artifact_id=artifact["artifact_id"])
    assert lineage.verify_all(control_dir=control)["ok"] is False


def test_attack_tampered_ancestor_blocks_recovery_and_destination_is_untouched(tmp_path: Path):
    control, iid = _admitted_information(tmp_path)
    a_path = tmp_path / "a.txt"
    a_path.write_text("a\n", encoding="utf-8")
    a = lineage.create_derived_artifact(
        source=a_path,
        control_dir=control,
        artifact_kind="fixture",
        transform_id="a",
        transform_version="1",
        parents=[{"kind": "information", "id": iid}],
    )
    b_path = tmp_path / "b.txt"
    b_path.write_text("b\n", encoding="utf-8")
    b = lineage.create_derived_artifact(
        source=b_path,
        control_dir=control,
        artifact_kind="fixture",
        transform_id="b",
        transform_version="1",
        parents=[{"kind": "artifact", "id": a["artifact_id"]}],
    )
    ancestor = control / "lineage" / "artifacts" / a["artifact_id"] / "artifact.bin"
    ancestor.write_text("tampered\n", encoding="utf-8")
    destination = tmp_path / "destination.txt"
    destination.write_text("preserve\n", encoding="utf-8")

    with pytest.raises(ValueError, match="payload hash mismatch"):
        lineage.recover_artifact(
            control_dir=control,
            artifact_id=b["artifact_id"],
            destination=destination,
            overwrite=True,
        )
    assert destination.read_text(encoding="utf-8") == "preserve\n"


def test_attack_repo_local_release_authority_private_key_is_rejected(tmp_path: Path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    claim = root / "authority.json"
    claim.write_text(
        json.dumps(
            {
                "schema_version": "1",
                "signature_namespace": release_authority.AUTHORITY_NAMESPACE,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    key = root / "release-key"
    key.write_text("fake", encoding="utf-8")
    called = False

    def no_run(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("ssh-keygen must not run for a repository-local key")

    monkeypatch.setattr(signature_trust.subprocess, "run", no_run)
    with pytest.raises(ValueError, match="outside the repository root"):
        release_authority.sign_claim(root=root, claim=claim, private_key=key)
    assert called is False


def test_attack_allowed_signer_hash_mismatch_stops_before_ssh(tmp_path: Path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    control = root / "private_runtime" / "control"
    control.mkdir(parents=True)
    allowed = tmp_path / "allowed_signers"
    allowed.write_text("reviewer ssh-ed25519 AAAATEST\n", encoding="utf-8")
    called = False

    def no_run(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("ssh-keygen must not run before trust-root validation")

    monkeypatch.setattr(signature_trust.subprocess, "run", no_run)
    with pytest.raises(ValueError, match="allowed-signers hash mismatch"):
        signature_trust.verify_bytes(
            root=root,
            control_dir=control,
            payload=b"claim",
            signature=b"signature",
            allowed_signers=allowed,
            expected_allowed_signers_sha256="0" * 64,
            identity="reviewer",
            namespace=release_authority.AUTHORITY_NAMESPACE,
        )
    assert called is False


def test_attack_legacy_g1_g11_release_cannot_bypass_signed_authority(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        erc,
        "assess_release",
        lambda **kwargs: {
            "evaluation_release_permitted": True,
            "champion_sha256": EXPECTED_CHAMPION_SHA256,
        },
    )
    called = False

    def no_train(**kwargs):
        nonlocal called
        called = True
        raise AssertionError("challenger execution must not occur")

    monkeypatch.setattr(erc.gch, "train_challenger", no_train)
    with pytest.raises(RuntimeError, match="signed release authority is required"):
        erc.run_if_released(
            release_kwargs={
                "champion_bundle": BUNDLE,
                "output_dir": tmp_path / "release",
            },
            evaluation_output_dir=tmp_path / "eval",
        )
    assert called is False


def test_attack_account_identity_columns_are_rejected_and_raw_key_is_not_persisted(tmp_path: Path):
    case_db = _case_db(tmp_path)
    raw_key = "RAW-ACCOUNT-KEY-DO-NOT-PERSIST"
    mapping = tmp_path / "bad.csv"
    with mapping.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=["account_key", "case_id", "research_use_only", "email"],
        )
        w.writeheader()
        w.writerow(
            {
                "account_key": raw_key,
                "case_id": "CASE-H001",
                "research_use_only": "true",
                "email": "redacted@example.invalid",
            }
        )
    with pytest.raises(ValueError, match="prohibited identity/trading columns"):
        account_surveillance.ingest_links(
            mapping_csv=mapping,
            case_db=case_db,
            account_db=tmp_path / "account.sqlite",
        )

    good = tmp_path / "good.csv"
    good.write_text(
        f"account_key,case_id,research_use_only\n{raw_key},CASE-H001,true\n",
        encoding="utf-8",
    )
    account_db = tmp_path / "account.sqlite"
    account_surveillance.ingest_links(
        mapping_csv=good,
        case_db=case_db,
        account_db=account_db,
    )
    assert raw_key.encode("utf-8") not in account_db.read_bytes()


def test_attack_dashboard_external_bind_is_rejected(tmp_path: Path):
    case_db = _case_db(tmp_path)
    with pytest.raises(ValueError, match="non-loopback"):
        DashboardConfig(case_db, host="0.0.0.0").validate()


def test_attack_secret_scan_detects_constructed_api_key_without_echoing_secret(tmp_path: Path):
    secret = "sk-" + ("Q" * 40)
    path = tmp_path / "candidate.txt"
    path.write_text("token=" + secret + "\n", encoding="utf-8")
    findings = secret_scan.scan_paths(tmp_path, [path])
    assert findings
    assert any(x.kind == "openai_api_key" for x in findings)
    assert secret not in json.dumps([x.__dict__ for x in findings])


def test_attack_release_drift_rejects_wrong_external_trust_root(tmp_path: Path):
    old = b"historical\n"
    (tmp_path / "old.txt").write_bytes(old)
    release = {"files": [{"path": "old.txt", "sha256": hashlib_sha(old), "size_bytes": len(old)}]}
    (tmp_path / "RELEASE_MANIFEST.json").write_text(json.dumps(release), encoding="utf-8")
    (tmp_path / "SHA256SUMS").write_text(f"{hashlib_sha(old)}  old.txt\n", encoding="utf-8")
    allow = tmp_path / "allow.json"
    allow.write_text(
        json.dumps(
            {
                "schema_version": "2",
                "intentional_release_modifications": {},
                "repository_additions": {},
            }
        ),
        encoding="utf-8",
    )
    result = drift.verify_release_drift(
        root=tmp_path,
        release_manifest=tmp_path / "RELEASE_MANIFEST.json",
        sha256sums=tmp_path / "SHA256SUMS",
        exceptions=allow,
        expected_exceptions_sha256="0" * 64,
        tracked_paths={"old.txt"},
    )
    assert result["ok"] is False
    assert result["trust_root_authenticated"] is False


def hashlib_sha(data: bytes) -> str:
    import hashlib
    return hashlib.sha256(data).hexdigest()


def test_frozen_champion_matches_recorded_sha256():
    assert storage.sha256_file(BUNDLE) == EXPECTED_CHAMPION_SHA256
