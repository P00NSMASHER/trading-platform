from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import registry, source_policy, storage

SCHEMA_VERSION = "1"
LANE = "JUNAS"


def _sha256_file(path: Path) -> str:
    return storage.sha256_file(Path(path))


def _read_manifest(path: Path) -> dict:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("JUNAS manifest root must be an object")
    if str(raw.get("schema_version", "")) != SCHEMA_VERSION:
        raise ValueError(f"JUNAS manifest schema_version must equal {SCHEMA_VERSION!r}")
    documents = raw.get("documents")
    if not isinstance(documents, list) or not documents:
        raise ValueError("JUNAS manifest documents must be a non-empty list")
    return raw


def _required_text(row: dict, key: str) -> str:
    value = str(row.get(key, "")).strip()
    if not value:
        raise ValueError(f"JUNAS document requires {key}")
    return value


def ingest_document(
    *,
    source: Path,
    control_dir: Path,
    source_id: str,
    source_contract_sha256: str,
    data_classification: str,
    record_kind: str = "unstructured_document",
    source_family: str = "junas_document",
    policy_metadata: dict | None = None,
) -> dict:
    """Capture one unstructured document and stop before any model-plane use."""
    source = Path(source).resolve()
    control_dir = Path(control_dir).resolve()
    db_path = control_dir / "control.sqlite"
    snapshot = storage.receive_to_holding(source, control_dir)
    metadata = dict(policy_metadata or {})
    metadata["data_classification"] = str(data_classification).strip()

    registered = registry.register_information(
        db_path,
        domain="unstructured",
        source_id=str(source_id).strip(),
        content_sha256=snapshot.sha256,
        size_bytes=snapshot.size_bytes,
        source_contract_sha256=str(source_contract_sha256).strip(),
        data_classification=str(data_classification).strip(),
        record_kind=str(record_kind).strip(),
        source_family=str(source_family).strip(),
    )
    information_id = str(registered["information_id"])
    if registered["created"]:
        registry.append_event(
            db_path,
            information_id,
            "RECEIVED",
            "RECEIVED",
            {"lane": LANE, "source_path_fingerprint": snapshot.source_path_fingerprint},
        )
        registry.add_location(
            db_path,
            information_id,
            "SOURCE",
            snapshot.source_path_fingerprint,
            snapshot.sha256,
        )
        registry.append_event(db_path, information_id, "HELD", "HOLDING", {"lane": LANE})
        registry.add_location(
            db_path,
            information_id,
            "HOLDING",
            storage.path_fingerprint(snapshot.path),
            snapshot.sha256,
        )

    current = registry.current_state(db_path, information_id)
    decision = source_policy.evaluate_unstructured(metadata)
    if current == "HOLDING":
        if decision.decision == "QUARANTINE":
            quarantine_path = storage.quarantine_snapshot(snapshot, control_dir)
            registry.append_event(
                db_path,
                information_id,
                "QUARANTINED",
                "QUARANTINED",
                {"lane": LANE, "reason": decision.reason},
            )
            registry.add_location(
                db_path,
                information_id,
                "QUARANTINE",
                storage.path_fingerprint(quarantine_path),
                snapshot.sha256,
            )
        elif decision.decision == "REVIEW_REQUIRED":
            registry.append_event(
                db_path,
                information_id,
                "REVIEW_REQUIRED",
                "REVIEW_REQUIRED",
                {"lane": LANE, "reason": decision.reason},
            )
        elif decision.decision == "PUBLICITY_PENDING":
            registry.append_event(
                db_path,
                information_id,
                "PUBLICITY_PENDING",
                "PUBLICITY_PENDING",
                {"lane": LANE, "reason": decision.reason},
            )
        else:
            raise ValueError(f"unexpected JUNAS policy decision: {decision.decision!r}")
    elif current not in {"PUBLICITY_PENDING", "REVIEW_REQUIRED", "QUARANTINED"}:
        raise ValueError(f"unexpected JUNAS information state: {current!r}")

    state = registry.current_state(db_path, information_id)
    return {
        "schema_version": SCHEMA_VERSION,
        "lane": LANE,
        "information_id": information_id,
        "source_id": str(source_id).strip(),
        "content_sha256": snapshot.sha256,
        "holding_sha256": snapshot.sha256,
        "size_bytes": snapshot.size_bytes,
        "received_at_utc": registered["received_at_utc"],
        "source_path_fingerprint": snapshot.source_path_fingerprint,
        "data_classification": str(data_classification).strip(),
        "record_kind": str(record_kind).strip(),
        "source_family": str(source_family).strip(),
        "decision": decision.decision,
        "decision_reason": decision.reason,
        "state": state,
        "control_event_head": registry.event_head(db_path, information_id),
        "publicity_clearance_present": False,
        "model_plane_eligible": False,
        "downstream_export_created": False,
        "research_use_only": True,
    }


def ingest_manifest(*, manifest_path: Path, control_dir: Path) -> dict:
    manifest_path = Path(manifest_path).resolve()
    raw = _read_manifest(manifest_path)
    contract_sha256 = _sha256_file(manifest_path)
    receipts: list[dict] = []
    for row in raw["documents"]:
        if not isinstance(row, dict):
            raise ValueError("each JUNAS document entry must be an object")
        source_id = _required_text(row, "source_id")
        rel = Path(_required_text(row, "path"))
        source = rel if rel.is_absolute() else (manifest_path.parent / rel).resolve()
        classification = _required_text(row, "data_classification")
        record_kind = str(row.get("record_kind", "unstructured_document")).strip() or "unstructured_document"
        source_family = str(row.get("source_family", "junas_document")).strip() or "junas_document"
        policy_metadata = {
            "authorized": bool(row.get("authorized", False)),
            "license_reference": str(row.get("license_reference", "")).strip(),
            "source_reference": str(row.get("source_reference", "")).strip(),
        }
        receipts.append(
            ingest_document(
                source=source,
                control_dir=control_dir,
                source_id=source_id,
                source_contract_sha256=contract_sha256,
                data_classification=classification,
                record_kind=record_kind,
                source_family=source_family,
                policy_metadata=policy_metadata,
            )
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "lane": LANE,
        "manifest_sha256": contract_sha256,
        "document_count": len(receipts),
        "publicity_pending_count": sum(r["state"] == "PUBLICITY_PENDING" for r in receipts),
        "review_required_count": sum(r["state"] == "REVIEW_REQUIRED" for r in receipts),
        "quarantined_count": sum(r["state"] == "QUARANTINED" for r in receipts),
        "model_plane_eligible_count": 0,
        "research_use_only": True,
        "receipts": receipts,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="JUNAS fail-closed unstructured document intake")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--control-dir", type=Path, required=True)
    args = parser.parse_args()
    result = ingest_manifest(manifest_path=args.manifest, control_dir=args.control_dir)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
