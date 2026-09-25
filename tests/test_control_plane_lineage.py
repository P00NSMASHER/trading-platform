from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from control_plane import integrity, junas, lineage, registry, storage


def _admitted_information(tmp_path: Path) -> tuple[Path, str]:
    control = tmp_path / "control"
    source = tmp_path / "root.csv"
    source.write_text("x\n1\n", encoding="utf-8")
    snapshot = storage.receive_to_holding(source, control)
    row = registry.register_information(
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
    info_id = row["information_id"]
    registry.append_event(control / "control.sqlite", info_id, "RECEIVED", "RECEIVED")
    registry.add_location(
        control / "control.sqlite",
        info_id,
        "HOLDING",
        storage.path_fingerprint(snapshot.path),
        snapshot.sha256,
    )
    registry.append_event(control / "control.sqlite", info_id, "HELD", "HOLDING")
    registry.append_event(control / "control.sqlite", info_id, "ADMITTED", "ADMITTED_STRUCTURED")
    return control, info_id


def _artifact(
    tmp_path: Path,
    control: Path,
    name: str,
    text: str,
    parents: list[dict],
) -> dict:
    source = tmp_path / name
    source.write_text(text, encoding="utf-8")
    return lineage.create_derived_artifact(
        source=source,
        control_dir=control,
        artifact_kind="controlled_text_derivative",
        transform_id=f"fixture:{name}",
        transform_version="1",
        parents=parents,
    )


def test_recursive_lineage_verifies_and_recovers_exact_bytes(tmp_path: Path):
    control, info_id = _admitted_information(tmp_path)
    first = _artifact(
        tmp_path,
        control,
        "first.txt",
        "first derivative\n",
        [{"kind": "information", "id": info_id}],
    )
    second = _artifact(
        tmp_path,
        control,
        "second.txt",
        "second derivative\n",
        [{"kind": "artifact", "id": first["artifact_id"]}],
    )

    proof = lineage.verify_recursive(control_dir=control, artifact_id=second["artifact_id"])
    assert proof["ok"] is True
    assert proof["depth"] == 2
    assert proof["artifact_ancestors"] == [first["artifact_id"]]
    assert [row["id"] for row in proof["information_roots"]] == [info_id]
    assert proof["model_plane_eligible"] is False

    destination = tmp_path / "recovered" / "second.txt"
    recovered = lineage.recover_artifact(
        control_dir=control,
        artifact_id=second["artifact_id"],
        destination=destination,
    )
    assert recovered["recursive_lineage_verified"] is True
    assert recovered["lineage_depth"] == 2
    assert destination.read_text(encoding="utf-8") == "second derivative\n"
    assert storage.sha256_file(destination) == second["content_sha256"]


def test_pending_unstructured_information_cannot_be_a_lineage_parent(tmp_path: Path):
    source = tmp_path / "document.txt"
    source.write_text("pending public document\n", encoding="utf-8")
    control = tmp_path / "control"
    receipt = junas.ingest_document(
        source=source,
        control_dir=control,
        source_id="pending-doc",
        source_contract_sha256="b" * 64,
        data_classification="public_official_data",
        policy_metadata={"license_reference": "fixture-reference"},
    )
    assert receipt["state"] == "PUBLICITY_PENDING"

    derived = tmp_path / "derived.txt"
    derived.write_text("derived\n", encoding="utf-8")
    with pytest.raises(ValueError, match="not lineage-eligible"):
        lineage.create_derived_artifact(
            source=derived,
            control_dir=control,
            artifact_kind="controlled_text_derivative",
            transform_id="fixture:pending",
            transform_version="1",
            parents=[{"kind": "information", "id": receipt["information_id"]}],
        )


def test_lineage_identity_is_idempotent_for_same_bytes_transform_and_parents(tmp_path: Path):
    control, info_id = _admitted_information(tmp_path)
    source = tmp_path / "same.txt"
    source.write_text("same derivative\n", encoding="utf-8")
    kwargs = dict(
        source=source,
        control_dir=control,
        artifact_kind="controlled_text_derivative",
        transform_id="fixture:same",
        transform_version="1",
        parents=[{"kind": "information", "id": info_id}],
    )
    first = lineage.create_derived_artifact(**kwargs)
    second = lineage.create_derived_artifact(**kwargs)
    assert second["artifact_id"] == first["artifact_id"]
    assert first["created"] is True
    assert second["created"] is False


def test_later_append_only_parent_event_does_not_erase_bound_historical_lineage(tmp_path: Path):
    control, info_id = _admitted_information(tmp_path)
    artifact = _artifact(
        tmp_path,
        control,
        "derived.txt",
        "derived\n",
        [{"kind": "information", "id": info_id}],
    )
    bound = registry.get_lineage_parents(control / "control.sqlite", artifact["artifact_id"])[0]
    registry.append_event(control / "control.sqlite", info_id, "NO_OP_REFERENCED", "ADMITTED_STRUCTURED")
    assert registry.event_head(control / "control.sqlite", info_id) != bound["parent_event_head"]
    proof = lineage.verify_recursive(control_dir=control, artifact_id=artifact["artifact_id"])
    assert proof["ok"] is True
    assert proof["information_roots"][0]["event_head"] == bound["parent_event_head"]


def test_tampered_ancestor_payload_blocks_descendant_recovery(tmp_path: Path):
    control, info_id = _admitted_information(tmp_path)
    first = _artifact(
        tmp_path,
        control,
        "first.txt",
        "first\n",
        [{"kind": "information", "id": info_id}],
    )
    second = _artifact(
        tmp_path,
        control,
        "second.txt",
        "second\n",
        [{"kind": "artifact", "id": first["artifact_id"]}],
    )
    payload = control / "lineage" / "artifacts" / first["artifact_id"] / "artifact.bin"
    payload.write_text("tampered\n", encoding="utf-8")

    destination = tmp_path / "should-not-exist.txt"
    with pytest.raises(ValueError, match="payload hash mismatch"):
        lineage.recover_artifact(
            control_dir=control,
            artifact_id=second["artifact_id"],
            destination=destination,
        )
    assert not destination.exists()


def test_tampered_manifest_is_detected_by_recursive_verifier_and_integrity(tmp_path: Path):
    control, info_id = _admitted_information(tmp_path)
    artifact = _artifact(
        tmp_path,
        control,
        "derived.txt",
        "derived\n",
        [{"kind": "information", "id": info_id}],
    )
    manifest = control / "lineage" / "artifacts" / artifact["artifact_id"] / "manifest.json"
    manifest.write_text("{}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="manifest hash mismatch"):
        lineage.verify_recursive(control_dir=control, artifact_id=artifact["artifact_id"])
    report = integrity.verify_control_plane(control / "control.sqlite", control)
    assert report["lineage_integrity"]["ok"] is False
    assert report["ok"] is False


def test_lineage_registry_rows_are_immutable(tmp_path: Path):
    control, info_id = _admitted_information(tmp_path)
    artifact = _artifact(
        tmp_path,
        control,
        "derived.txt",
        "derived\n",
        [{"kind": "information", "id": info_id}],
    )
    with sqlite3.connect(control / "control.sqlite") as con:
        with pytest.raises(sqlite3.IntegrityError):
            con.execute(
                "UPDATE lineage_artifact SET transform_version='2' WHERE artifact_id=?",
                (artifact["artifact_id"],),
            )
        with pytest.raises(sqlite3.IntegrityError):
            con.execute(
                "DELETE FROM lineage_parent WHERE child_artifact_id=?",
                (artifact["artifact_id"],),
            )


def test_recovery_refuses_overwrite_without_explicit_opt_in(tmp_path: Path):
    control, info_id = _admitted_information(tmp_path)
    artifact = _artifact(
        tmp_path,
        control,
        "derived.txt",
        "derived\n",
        [{"kind": "information", "id": info_id}],
    )
    destination = tmp_path / "existing.txt"
    destination.write_text("keep me\n", encoding="utf-8")
    with pytest.raises(FileExistsError, match="overwrite=True"):
        lineage.recover_artifact(
            control_dir=control,
            artifact_id=artifact["artifact_id"],
            destination=destination,
        )
    assert destination.read_text(encoding="utf-8") == "keep me\n"
