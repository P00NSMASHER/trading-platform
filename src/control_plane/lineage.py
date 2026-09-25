from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from . import registry, storage

SCHEMA_VERSION = "1"
ALLOWED_INFORMATION_PARENT_STATES = {"ADMITTED_STRUCTURED", "PUBLICITY_CLEARED"}


def _canonical(obj: object) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _required(value: object, *, label: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{label} is required")
    return text


def _private_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    try:
        path.chmod(0o700)
    except OSError:
        pass


def _private_file(path: Path) -> None:
    try:
        path.chmod(0o600)
    except OSError:
        pass


def _information_event(db_path: Path, information_id: str, event_hash: str) -> dict:
    with registry.connect(db_path) as con:
        row = con.execute(
            "SELECT * FROM information_event WHERE information_id=? AND event_hash=?",
            (information_id, event_hash),
        ).fetchone()
    if row is None:
        raise ValueError("lineage information parent event head is missing")
    return dict(row)


def _holding_path(control_dir: Path, digest: str) -> Path:
    root = Path(control_dir).resolve() / "holding" / digest
    valid = [
        p for p in root.glob("original*")
        if p.is_file() and not p.is_symlink() and storage.sha256_file(p) == digest
    ]
    if len(valid) != 1:
        raise ValueError(f"information parent HOLDING snapshot is missing or ambiguous for {digest}")
    return valid[0]


def _verify_publicity_artifact(control_dir: Path, event: dict) -> None:
    detail = json.loads(str(event.get("detail_json", "{}")))
    if not isinstance(detail, dict):
        raise ValueError("PUBLICITY_CLEARED event detail is invalid")
    digest = str(detail.get("clearance_sha256", "")).strip()
    if len(digest) != 64:
        raise ValueError("PUBLICITY_CLEARED lineage root lacks clearance_sha256")
    root = Path(control_dir).resolve() / "publicity_clearances" / digest
    claim = root / "clearance.json"
    signature = root / "clearance.json.sig"
    if (
        not claim.is_file()
        or claim.is_symlink()
        or storage.sha256_file(claim) != digest
        or not signature.is_file()
        or signature.is_symlink()
        or signature.stat().st_size <= 0
    ):
        raise ValueError("PUBLICITY_CLEARED lineage root lacks its verified clearance archive")


def _verify_information_parent(
    *,
    db_path: Path,
    control_dir: Path,
    information_id: str,
    event_head: str,
    expected_content_sha256: str,
) -> dict:
    info = registry.get_information(db_path, information_id)
    if not registry.verify_event_chain(db_path, information_id):
        raise ValueError(f"information parent event chain is invalid: {information_id}")
    event = _information_event(db_path, information_id, event_head)
    state = str(event["state_after"])
    if state not in ALLOWED_INFORMATION_PARENT_STATES:
        raise ValueError(
            f"information parent is not lineage-eligible at bound event head: {information_id} state={state}"
        )
    if str(info["content_sha256"]) != str(expected_content_sha256):
        raise ValueError("information parent content SHA-256 differs from bound lineage record")
    _holding_path(control_dir, str(info["content_sha256"]))
    if state == "PUBLICITY_CLEARED":
        _verify_publicity_artifact(control_dir, event)
    if registry.current_state(db_path, information_id) in {"QUARANTINED", "REVIEW_REQUIRED"}:
        raise ValueError("information parent is currently held or quarantined")
    return {
        "kind": "information",
        "id": information_id,
        "event_head": event_head,
        "state_at_event_head": state,
        "content_sha256": str(info["content_sha256"]),
    }


def _artifact_dir(control_dir: Path, artifact_id: str) -> Path:
    return Path(control_dir).resolve() / "lineage" / "artifacts" / artifact_id


def _manifest_bytes(manifest: dict[str, Any]) -> bytes:
    return (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _artifact_identity(
    *,
    content_sha256: str,
    artifact_kind: str,
    transform_id: str,
    transform_version: str,
    parents: list[dict],
) -> str:
    payload = {
        "content_sha256": content_sha256,
        "artifact_kind": artifact_kind,
        "transform_id": transform_id,
        "transform_version": transform_version,
        "parents": parents,
    }
    return "artifact_" + hashlib.sha256(_canonical(payload)).hexdigest()


def _write_archive(
    *,
    source: Path,
    control_dir: Path,
    artifact_id: str,
    content_sha256: str,
    manifest: dict[str, Any],
) -> str:
    root = _artifact_dir(control_dir, artifact_id)
    tmp_root = Path(control_dir).resolve() / "_tmp"
    _private_dir(root); _private_dir(tmp_root)
    payload = root / "artifact.bin"
    manifest_path = root / "manifest.json"
    manifest_bytes = _manifest_bytes(manifest)
    manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()

    if payload.exists():
        if payload.is_symlink() or storage.sha256_file(payload) != content_sha256:
            raise ValueError("existing lineage artifact payload does not match expected hash")
    else:
        fd, tmp_name = tempfile.mkstemp(prefix="lineage-payload-", dir=tmp_root)
        tmp = Path(tmp_name)
        try:
            with source.open("rb") as src, os.fdopen(fd, "wb") as dst:
                shutil.copyfileobj(src, dst, length=1024 * 1024)
                dst.flush(); os.fsync(dst.fileno())
            if storage.sha256_file(tmp) != content_sha256:
                raise ValueError("lineage payload changed while archiving")
            os.replace(tmp, payload); _private_file(payload)
        finally:
            tmp.unlink(missing_ok=True)

    if manifest_path.exists():
        if manifest_path.is_symlink() or manifest_path.read_bytes() != manifest_bytes:
            raise ValueError("existing lineage manifest differs for deterministic artifact identity")
    else:
        fd, tmp_name = tempfile.mkstemp(prefix="lineage-manifest-", dir=tmp_root)
        tmp = Path(tmp_name)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(manifest_bytes); f.flush(); os.fsync(f.fileno())
            os.replace(tmp, manifest_path); _private_file(manifest_path)
        finally:
            tmp.unlink(missing_ok=True)

    return manifest_sha256


def create_derived_artifact(
    *,
    source: Path,
    control_dir: Path,
    artifact_kind: str,
    transform_id: str,
    transform_version: str,
    parents: list[dict],
) -> dict:
    """Archive a research-only derived artifact with exact recursive ancestry."""
    source = Path(source).resolve()
    control_dir = Path(control_dir).resolve()
    if not source.is_file() or source.is_symlink():
        raise ValueError("derived artifact source must be a regular non-symlink file")
    artifact_kind = _required(artifact_kind, label="artifact_kind")
    transform_id = _required(transform_id, label="transform_id")
    transform_version = _required(transform_version, label="transform_version")
    if not isinstance(parents, list) or not parents:
        raise ValueError("derived artifact requires at least one lineage parent")

    db_path = control_dir / "control.sqlite"
    registry.init_db(db_path)
    bound_parents: list[dict] = []
    for ordinal, parent in enumerate(parents):
        if not isinstance(parent, dict):
            raise ValueError("lineage parent must be an object")
        kind = str(parent.get("kind", "")).strip()
        parent_id = _required(parent.get("id"), label="lineage parent id")
        if kind == "information":
            info = registry.get_information(db_path, parent_id)
            event_head = registry.event_head(db_path, parent_id)
            proof = _verify_information_parent(
                db_path=db_path,
                control_dir=control_dir,
                information_id=parent_id,
                event_head=event_head,
                expected_content_sha256=str(info["content_sha256"]),
            )
            bound_parents.append({
                "parent_ordinal": ordinal,
                "parent_kind": "information",
                "parent_id": parent_id,
                "parent_event_head": event_head,
                "parent_content_sha256": proof["content_sha256"],
            })
        elif kind == "artifact":
            proof = verify_recursive(control_dir=control_dir, artifact_id=parent_id)
            bound_parents.append({
                "parent_ordinal": ordinal,
                "parent_kind": "artifact",
                "parent_id": parent_id,
                "parent_event_head": "",
                "parent_content_sha256": proof["content_sha256"],
            })
        else:
            raise ValueError("lineage parent kind must be 'information' or 'artifact'")

    content_sha256 = storage.sha256_file(source)
    size_bytes = source.stat().st_size
    artifact_id = _artifact_identity(
        content_sha256=content_sha256,
        artifact_kind=artifact_kind,
        transform_id=transform_id,
        transform_version=transform_version,
        parents=bound_parents,
    )
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "artifact_id": artifact_id,
        "content_sha256": content_sha256,
        "size_bytes": size_bytes,
        "artifact_kind": artifact_kind,
        "transform_id": transform_id,
        "transform_version": transform_version,
        "parents": bound_parents,
        "research_use_only": True,
        "model_plane_eligible": False,
    }
    manifest_sha256 = _write_archive(
        source=source,
        control_dir=control_dir,
        artifact_id=artifact_id,
        content_sha256=content_sha256,
        manifest=manifest,
    )
    registered = registry.register_lineage_artifact(
        db_path,
        artifact_id=artifact_id,
        content_sha256=content_sha256,
        size_bytes=size_bytes,
        artifact_kind=artifact_kind,
        transform_id=transform_id,
        transform_version=transform_version,
        lineage_manifest_sha256=manifest_sha256,
        parents=bound_parents,
    )
    return {
        **manifest,
        "lineage_manifest_sha256": manifest_sha256,
        "created": registered["created"],
        "created_at_utc": registered["created_at_utc"],
    }


def _verify_recursive(
    *,
    control_dir: Path,
    artifact_id: str,
    visiting: set[str],
    memo: dict[str, dict],
) -> dict:
    if artifact_id in memo:
        return memo[artifact_id]
    if artifact_id in visiting:
        raise ValueError(f"lineage cycle detected at {artifact_id}")
    visiting.add(artifact_id)
    db_path = Path(control_dir).resolve() / "control.sqlite"
    row = registry.get_lineage_artifact(db_path, artifact_id)
    parents = registry.get_lineage_parents(db_path, artifact_id)
    root = _artifact_dir(control_dir, artifact_id)
    payload = root / "artifact.bin"
    manifest_path = root / "manifest.json"
    if not payload.is_file() or payload.is_symlink():
        raise ValueError(f"lineage artifact payload missing: {artifact_id}")
    if storage.sha256_file(payload) != str(row["content_sha256"]):
        raise ValueError(f"lineage artifact payload hash mismatch: {artifact_id}")
    if payload.stat().st_size != int(row["size_bytes"]):
        raise ValueError(f"lineage artifact payload size mismatch: {artifact_id}")
    if not manifest_path.is_file() or manifest_path.is_symlink():
        raise ValueError(f"lineage artifact manifest missing: {artifact_id}")
    manifest_bytes = manifest_path.read_bytes()
    if hashlib.sha256(manifest_bytes).hexdigest() != str(row["lineage_manifest_sha256"]):
        raise ValueError(f"lineage artifact manifest hash mismatch: {artifact_id}")
    try:
        manifest = json.loads(manifest_bytes.decode("utf-8"))
    except Exception as exc:
        raise ValueError(f"lineage artifact manifest is invalid JSON: {artifact_id}") from exc
    expected_manifest = {
        "schema_version": SCHEMA_VERSION,
        "artifact_id": artifact_id,
        "content_sha256": str(row["content_sha256"]),
        "size_bytes": int(row["size_bytes"]),
        "artifact_kind": str(row["artifact_kind"]),
        "transform_id": str(row["transform_id"]),
        "transform_version": str(row["transform_version"]),
        "parents": parents,
        "research_use_only": True,
        "model_plane_eligible": False,
    }
    if manifest != expected_manifest:
        raise ValueError(f"lineage manifest and registry disagree: {artifact_id}")

    roots: list[dict] = []
    descendants: list[str] = []
    max_parent_depth = 0
    for parent in parents:
        if parent["parent_kind"] == "information":
            proof = _verify_information_parent(
                db_path=db_path,
                control_dir=control_dir,
                information_id=str(parent["parent_id"]),
                event_head=str(parent["parent_event_head"]),
                expected_content_sha256=str(parent["parent_content_sha256"]),
            )
            roots.append(proof)
        elif parent["parent_kind"] == "artifact":
            proof = _verify_recursive(
                control_dir=control_dir,
                artifact_id=str(parent["parent_id"]),
                visiting=visiting,
                memo=memo,
            )
            if proof["content_sha256"] != str(parent["parent_content_sha256"]):
                raise ValueError("artifact parent content SHA-256 differs from bound lineage record")
            roots.extend(proof["information_roots"])
            descendants.append(str(parent["parent_id"]))
            descendants.extend(proof["artifact_ancestors"])
            max_parent_depth = max(max_parent_depth, int(proof["depth"]))
        else:
            raise ValueError("unsupported lineage parent kind in registry")

    visiting.remove(artifact_id)
    unique_roots = {r["id"]: r for r in roots}
    result = {
        "ok": True,
        "artifact_id": artifact_id,
        "content_sha256": str(row["content_sha256"]),
        "lineage_manifest_sha256": str(row["lineage_manifest_sha256"]),
        "information_roots": [unique_roots[k] for k in sorted(unique_roots)],
        "artifact_ancestors": sorted(set(descendants)),
        "depth": 1 + max_parent_depth,
        "research_use_only": True,
        "model_plane_eligible": False,
    }
    memo[artifact_id] = result
    return result


def verify_recursive(*, control_dir: Path, artifact_id: str) -> dict:
    return _verify_recursive(
        control_dir=Path(control_dir).resolve(),
        artifact_id=artifact_id,
        visiting=set(),
        memo={},
    )


def verify_all(*, control_dir: Path) -> dict:
    control_dir = Path(control_dir).resolve()
    db_path = control_dir / "control.sqlite"
    registry.init_db(db_path)
    with registry.connect(db_path) as con:
        ids = [str(r["artifact_id"]) for r in con.execute("SELECT artifact_id FROM lineage_artifact ORDER BY artifact_id").fetchall()]
    errors: list[dict] = []
    for artifact_id in ids:
        try:
            verify_recursive(control_dir=control_dir, artifact_id=artifact_id)
        except Exception as exc:
            errors.append({"artifact_id": artifact_id, "error": f"{type(exc).__name__}: {exc}"})
    return {"ok": not errors, "artifact_count": len(ids), "errors": errors}


def recover_artifact(
    *,
    control_dir: Path,
    artifact_id: str,
    destination: Path,
    overwrite: bool = False,
) -> dict:
    """Recover one derived artifact only after its complete ancestry verifies."""
    control_dir = Path(control_dir).resolve()
    proof = verify_recursive(control_dir=control_dir, artifact_id=artifact_id)
    source = _artifact_dir(control_dir, artifact_id) / "artifact.bin"
    destination = Path(destination).resolve()
    if destination.exists() and not overwrite:
        raise FileExistsError(f"destination exists: {destination}; pass overwrite=True explicitly")
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        destination.parent.chmod(0o700)
    except OSError:
        pass
    fd, tmp_name = tempfile.mkstemp(prefix=f".{destination.name}.recover-", dir=destination.parent)
    tmp = Path(tmp_name)
    try:
        with source.open("rb") as src, os.fdopen(fd, "wb") as dst:
            shutil.copyfileobj(src, dst, length=1024 * 1024)
            dst.flush(); os.fsync(dst.fileno())
        if storage.sha256_file(tmp) != proof["content_sha256"]:
            raise RuntimeError("recovered artifact hash mismatch before atomic placement")
        os.replace(tmp, destination); _private_file(destination)
    finally:
        tmp.unlink(missing_ok=True)
    if storage.sha256_file(destination) != proof["content_sha256"]:
        raise RuntimeError("recovered artifact hash mismatch after placement")
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_id": artifact_id,
        "destination": str(destination),
        "destination_sha256": proof["content_sha256"],
        "recursive_lineage_verified": True,
        "information_root_count": len(proof["information_roots"]),
        "artifact_ancestor_count": len(proof["artifact_ancestors"]),
        "lineage_depth": proof["depth"],
        "research_use_only": True,
        "model_plane_eligible": False,
    }
