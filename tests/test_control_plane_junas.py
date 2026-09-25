from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from control_plane import junas, registry, storage


def _manifest(tmp_path: Path, *, classification: str, extra: dict | None = None) -> Path:
    source = tmp_path / "document.txt"
    source.write_text("historical research document\n", encoding="utf-8")
    row = {
        "source_id": "doc-1",
        "path": source.name,
        "data_classification": classification,
        "record_kind": "unstructured_document",
        "source_family": "test_fixture",
        "license_reference": "fixture-reference",
    }
    row.update(extra or {})
    path = tmp_path / "junas.json"
    path.write_text(json.dumps({"schema_version": "1", "documents": [row]}), encoding="utf-8")
    return path


def _event_states(db_path: Path, information_id: str) -> list[str]:
    with registry.connect(db_path) as con:
        return [
            str(row["state_after"])
            for row in con.execute(
                "SELECT state_after FROM information_event WHERE information_id=? ORDER BY sequence",
                (information_id,),
            ).fetchall()
        ]


def test_junas_public_candidate_stops_at_publicity_pending(tmp_path: Path):
    manifest = _manifest(tmp_path, classification="public_official_data")
    control = tmp_path / "control"
    result = junas.ingest_manifest(manifest_path=manifest, control_dir=control)
    receipt = result["receipts"][0]

    assert receipt["state"] == "PUBLICITY_PENDING"
    assert receipt["decision"] == "PUBLICITY_PENDING"
    assert receipt["publicity_clearance_present"] is False
    assert receipt["model_plane_eligible"] is False
    assert receipt["downstream_export_created"] is False
    assert _event_states(control / "control.sqlite", receipt["information_id"]) == [
        "RECEIVED",
        "HOLDING",
        "PUBLICITY_PENDING",
    ]
    held = list((control / "holding" / receipt["holding_sha256"]).glob("original*"))
    assert len(held) == 1
    assert storage.sha256_file(held[0]) == receipt["holding_sha256"]
    assert not (control / "model").exists()
    assert not (control / "features").exists()
    assert not (control / "champion").exists()


def test_junas_unknown_classification_requires_review(tmp_path: Path):
    manifest = _manifest(tmp_path, classification="novel_document_classification")
    result = junas.ingest_manifest(manifest_path=manifest, control_dir=tmp_path / "control")
    receipt = result["receipts"][0]
    assert receipt["state"] == "REVIEW_REQUIRED"
    assert receipt["model_plane_eligible"] is False


def test_junas_prohibited_classification_is_quarantined(tmp_path: Path):
    manifest = _manifest(tmp_path, classification="unauthorized_private_data")
    control = tmp_path / "control"
    result = junas.ingest_manifest(manifest_path=manifest, control_dir=control)
    receipt = result["receipts"][0]
    assert receipt["state"] == "QUARANTINED"
    quarantined = list((control / "quarantine" / receipt["content_sha256"]).glob("original*"))
    assert len(quarantined) == 1
    assert storage.sha256_file(quarantined[0]) == receipt["content_sha256"]


def test_unstructured_holding_cannot_directly_enter_structured_or_model_path(tmp_path: Path):
    source = tmp_path / "document.txt"
    source.write_text("x", encoding="utf-8")
    control = tmp_path / "control"
    snapshot = storage.receive_to_holding(source, control)
    registered = registry.register_information(
        control / "control.sqlite",
        domain="unstructured",
        source_id="doc",
        content_sha256=snapshot.sha256,
        size_bytes=snapshot.size_bytes,
        source_contract_sha256="a" * 64,
        data_classification="public_official_data",
        record_kind="unstructured_document",
        source_family="test_fixture",
    )
    info_id = registered["information_id"]
    registry.append_event(control / "control.sqlite", info_id, "RECEIVED", "RECEIVED")
    registry.append_event(control / "control.sqlite", info_id, "HELD", "HOLDING")

    with pytest.raises(ValueError, match="only exit"):
        registry.append_event(control / "control.sqlite", info_id, "ADMITTED", "ADMITTED_STRUCTURED")


def test_junas_exact_reingest_is_idempotent(tmp_path: Path):
    manifest = _manifest(tmp_path, classification="public_research_replication")
    control = tmp_path / "control"
    first = junas.ingest_manifest(manifest_path=manifest, control_dir=control)
    second = junas.ingest_manifest(manifest_path=manifest, control_dir=control)
    first_receipt = first["receipts"][0]
    second_receipt = second["receipts"][0]

    assert second_receipt["information_id"] == first_receipt["information_id"]
    assert second_receipt["state"] == "PUBLICITY_PENDING"
    assert second_receipt["control_event_head"] == first_receipt["control_event_head"]
    with sqlite3.connect(control / "control.sqlite") as con:
        count = con.execute(
            "SELECT COUNT(*) FROM information_event WHERE information_id=?",
            (first_receipt["information_id"],),
        ).fetchone()[0]
    assert count == 3


def test_junas_authorized_reference_without_authorization_requires_review(tmp_path: Path):
    manifest = _manifest(
        tmp_path,
        classification="authorized_reference_data",
        extra={"authorized": False},
    )
    result = junas.ingest_manifest(manifest_path=manifest, control_dir=tmp_path / "control")
    assert result["receipts"][0]["state"] == "REVIEW_REQUIRED"
