from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import coverage_planner
import evaluation_release_controller as erc
import historical_market_backfill as hmb
import metadata_population
import metadata_quality
import metadata_resolver

from control_plane import integrity as control_integrity
from control_plane import registry as control_registry
from control_plane import source_policy as control_source_policy
from control_plane import storage as control_storage

SCHEMA_VERSION = "0.21.0"
LEDGER_SCHEMA_VERSION = "1"
PROHIBITED_OUTPUTS = [
    "BUY", "SELL", "LONG/SHORT recommendation", "expected_return", "target_price",
    "position_size", "order", "execution_instruction",
]
GATE_IDS = [
    "G1_ANNOUNCEMENT_TIMES",
    "G2_REAL_MARKET_DATA",
    "G3_PRIMARY_LISTING_HISTORY",
    "G4_SHARES_OUTSTANDING",
    "G5_MATCHED_CONTROL_UNIVERSE",
    "G6_METADATA_QUALITY",
    "G7_TEMPORAL_FEATURE_INTEGRITY",
    "G8_HOLDOUT_ISOLATION",
    "G9_PROVENANCE",
    "G10_CHAMPION_IMMUTABILITY",
    "G11_NON_SYNTHETIC_RESEARCH_ONLY",
]
CREDENTIAL_KEY_FRAGMENTS = ("password", "secret", "api_key", "apikey", "credential", "access_token", "refresh_token")


class OrchestratorError(ValueError):
    pass


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _canonical_json(obj: object) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _json_hash(obj: object) -> str:
    return hashlib.sha256(_canonical_json(obj)).hexdigest()


def _write_json(path: Path, obj: object, *, mode: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if mode is not None:
        try:
            os.chmod(path, mode)
        except OSError:
            pass


def _read_json(path: Path) -> dict:
    obj = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        raise OrchestratorError(f"JSON root must be an object: {path}")
    return obj


def _walk_keys(obj: Any, prefix: str = "") -> list[str]:
    bad: list[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            key = str(k).lower()
            where = f"{prefix}.{k}" if prefix else str(k)
            if any(fragment in key for fragment in CREDENTIAL_KEY_FRAGMENTS):
                bad.append(where)
            bad.extend(_walk_keys(v, where))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            bad.extend(_walk_keys(v, f"{prefix}[{i}]"))
    return bad


def load_batch_manifest(path: Path) -> dict:
    raw = _read_json(path)
    if raw.get("schema_version") != "1":
        raise OrchestratorError("batch manifest schema_version must equal '1'")
    bad = _walk_keys(raw)
    if bad:
        raise OrchestratorError(f"credential-like fields are prohibited in batch manifests: {bad}")
    for domain in ("metadata", "market"):
        block = raw.get(domain)
        if block is None:
            continue
        if not isinstance(block, dict):
            raise OrchestratorError(f"{domain} block must be an object")
        if not str(block.get("source_contract", "")).strip():
            raise OrchestratorError(f"{domain}.source_contract is required when the block is present")
        ids = block.get("source_ids")
        if ids is not None and (not isinstance(ids, list) or not all(isinstance(x, str) and x.strip() for x in ids)):
            raise OrchestratorError(f"{domain}.source_ids must be a list of non-blank strings")
    if not raw.get("metadata") and not raw.get("market"):
        raise OrchestratorError("batch manifest must contain metadata and/or market inputs")
    return raw


def _resolve_from_root(root: Path, value: str) -> Path:
    p = Path(value)
    return p if p.is_absolute() else (root / p).resolve()


def _safe_id(value: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in value)


def _validate_path_component(value: str, *, label: str) -> str:
    value = str(value).strip()
    if not value or len(value) > 128 or value in {".", ".."} or _safe_id(value) != value:
        raise OrchestratorError(f"{label} must contain only letters, numbers, '-' or '_' and be at most 128 characters")
    return value


def _contained_child(root: Path, component: str, *, label: str) -> Path:
    root = Path(root).resolve()
    child = (root / component).resolve()
    try:
        child.relative_to(root)
    except ValueError as exc:
        raise OrchestratorError(f"{label} resolves outside the configured output directory") from exc
    return child


def _source_gates(domain: str, source: dict) -> list[str]:
    if domain == "market":
        return ["G2_REAL_MARKET_DATA"]
    kind = str(source.get("record_kind", ""))
    if kind == "announcement_timestamp":
        return ["G1_ANNOUNCEMENT_TIMES", "G6_METADATA_QUALITY"]
    if kind == "security_master":
        return ["G3_PRIMARY_LISTING_HISTORY", "G4_SHARES_OUTSTANDING", "G6_METADATA_QUALITY"]
    if kind == "shares_outstanding":
        return ["G4_SHARES_OUTSTANDING", "G6_METADATA_QUALITY"]
    if kind == "control_universe":
        return ["G5_MATCHED_CONTROL_UNIVERSE", "G6_METADATA_QUALITY"]
    return ["G6_METADATA_QUALITY"]


def _load_contract_rows(contract: Path) -> tuple[dict, dict[str, dict]]:
    raw = _read_json(contract)
    rows = raw.get("sources", [])
    if not isinstance(rows, list):
        raise OrchestratorError(f"sources must be a list: {contract}")
    by_id: dict[str, dict] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise OrchestratorError(f"source rows must be objects: {contract}")
        sid = str(row.get("source_id", "")).strip()
        if not sid or sid in by_id:
            raise OrchestratorError(f"source_id must be unique/non-blank in {contract}")
        by_id[sid] = row
    return raw, by_id


def _selected_source_ids(contract: Path, requested: list[str] | None) -> list[str]:
    _, by_id = _load_contract_rows(contract)
    if requested is None:
        return sorted(by_id)
    missing = sorted(set(requested) - set(by_id))
    if missing:
        raise OrchestratorError(f"source_ids not found in {contract}: {missing}")
    return list(requested)


def _resolve_market_source_path(contract: Path, source: dict) -> Path:
    p = Path(str(source.get("path", "")))
    return p if p.is_absolute() else (contract.parent / p).resolve()


def _resolve_metadata_source_path(contract: Path, source: dict) -> Path:
    p = Path(str(source.get("path", "")))
    return p if p.is_absolute() else (contract.parent.parent / p).resolve()


def _controlled_source_contract(*, runtime_dir: Path, domain: str, source_id: str, source: dict, holding_path: Path) -> tuple[Path, dict]:
    row = dict(source); row["path"] = str(Path(holding_path).resolve())
    contract_dir = runtime_dir / "control" / "contracts"; contract_dir.mkdir(parents=True, exist_ok=True)
    try: os.chmod(contract_dir, 0o700)
    except OSError: pass
    path = contract_dir / f"{domain}-{_safe_id(source_id)}.json"
    _write_json(path, {"schema_version": "1", "purpose": "Controlled HOLDING snapshot contract", "sources": [row]}, mode=0o600)
    return path, row


def _prepare_controlled_source(*, runtime_dir: Path, domain: str, contract: Path, source_id: str, source: dict) -> dict:
    original_path = _resolve_metadata_source_path(contract, source) if domain == "metadata" else _resolve_market_source_path(contract, source)
    control_dir = runtime_dir / "control"; db_path = control_dir / "control.sqlite"
    snapshot = control_storage.receive_to_holding(original_path, control_dir)
    registered = control_registry.register_information(
        db_path, domain=domain, source_id=source_id, content_sha256=snapshot.sha256, size_bytes=snapshot.size_bytes,
        source_contract_sha256=_sha256(contract), data_classification=str(source.get("data_classification", "")),
        record_kind=str(source.get("record_kind", "")), source_family=str(source.get("source_family", "")),
    )
    info_id = registered["information_id"]
    if registered["created"]:
        control_registry.append_event(db_path, info_id, "RECEIVED", "RECEIVED", {"source_path_fingerprint": snapshot.source_path_fingerprint})
        control_registry.add_location(db_path, info_id, "SOURCE", snapshot.source_path_fingerprint, snapshot.sha256)
        control_registry.append_event(db_path, info_id, "HELD", "HOLDING")
        control_registry.add_location(db_path, info_id, "HOLDING", control_storage.path_fingerprint(snapshot.path), snapshot.sha256)
    policy = control_source_policy.evaluate(source)
    controlled_contract, controlled_row = _controlled_source_contract(runtime_dir=runtime_dir, domain=domain, source_id=source_id, source=source, holding_path=snapshot.path)
    return {"information_id": info_id, "snapshot": snapshot, "policy": policy, "controlled_contract": controlled_contract,
            "controlled_row": controlled_row, "received_at_utc": registered["received_at_utc"]}


def _empty_market_contract() -> dict:
    return {"schema_version": "1", "purpose": "Step 21 cumulative authorized market inputs", "sources": []}


def _ensure_runtime(runtime_dir: Path) -> tuple[Path, Path]:
    metadata_runtime = runtime_dir / "metadata"
    market_runtime = runtime_dir / "market"
    control_runtime = runtime_dir / "control"
    for d in (runtime_dir, metadata_runtime, market_runtime, control_runtime, runtime_dir / "current"):
        d.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(d, 0o700)
        except OSError:
            pass
    meta_active = metadata_runtime / "active_metadata_sources.json"
    if not meta_active.exists():
        _write_json(meta_active, {"schema_version": "1", "purpose": "Step 21 cumulative metadata inputs", "sources": []}, mode=0o600)
    market_active = market_runtime / "active_market_sources.json"
    if not market_active.exists():
        _write_json(market_active, _empty_market_contract(), mode=0o600)
    control_registry.init_db(control_runtime / "control.sqlite")
    return meta_active, market_active


def _validate_and_stage_market_source(*, contract: Path, source: dict, market_runtime: Path) -> tuple[dict, dict, bool]:
    source_id = str(source.get("source_id", "")).strip()
    src_path = _resolve_market_source_path(contract, source)
    if not src_path.exists() or not src_path.is_file():
        raise FileNotFoundError(f"market source file missing for {source_id}: {src_path}")

    candidate = dict(source)
    candidate["path"] = str(src_path)
    validate_path = market_runtime / "_validate_single_market_source.json"
    _write_json(validate_path, {"schema_version": "1", "sources": [candidate]}, mode=0o600)
    specs, _ = hmb.load_contract(validate_path)
    if len(specs) != 1:
        raise OrchestratorError(f"market source validation failed for {source_id}")
    spec = specs[0]
    sha = _sha256(src_path)

    active_path = market_runtime / "active_market_sources.json"
    active = _read_json(active_path)
    by_id = {str(x.get("source_id")): x for x in active.get("sources", [])}
    current = by_id.get(source_id)
    if current:
        cp = Path(str(current.get("path", "")))
        if cp.exists() and _sha256(cp) == sha:
            receipt = {
                "source_id": source_id, "status": "NO_OP", "sha256": sha, "source_path": str(src_path),
                "data_classification": spec.data_classification, "record_kind": spec.record_kind,
                "source_family": spec.source_family, "trade_date": spec.trade_date,
                "license_reference": spec.license_reference,
            }
            return current, receipt, True

    dest_dir = market_runtime / "staged" / _safe_id(source_id)
    dest_dir.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(dest_dir, 0o700)
    except OSError:
        pass
    suffix = "".join(src_path.suffixes[-2:]) if src_path.suffix == ".gz" else src_path.suffix
    dest = dest_dir / f"{sha}{suffix or '.csv'}"
    if not dest.exists():
        shutil.copy2(src_path, dest)
    try:
        os.chmod(dest, 0o600)
    except OSError:
        pass
    if _sha256(dest) != sha:
        raise OrchestratorError(f"staged market source hash mismatch: {source_id}")

    staged = dict(candidate)
    staged["path"] = str(dest.resolve())
    by_id[source_id] = staged
    active_new = _empty_market_contract()
    active_new["sources"] = [by_id[k] for k in sorted(by_id)]
    _write_json(active_path, active_new, mode=0o600)
    receipt = {
        "source_id": source_id, "status": "IMPORTED", "sha256": sha, "source_path": str(src_path),
        "staged_path": str(dest), "size_bytes": src_path.stat().st_size,
        "data_classification": spec.data_classification, "record_kind": spec.record_kind,
        "source_family": spec.source_family, "trade_date": spec.trade_date,
        "license_reference": spec.license_reference,
    }
    return staged, receipt, False


def _empty_market_manifest(contract: Path, events: Path) -> dict:
    return {
        "schema_version": hmb.SCHEMA_VERSION,
        "purpose": "Step 21 empty authorized historical market-data state; fail-closed until market sources are imported.",
        "contract_sha256": _sha256(contract),
        "historical_events_sha256": _sha256(events),
        "source_count": 0,
        "source_contracts": [],
        "outputs": {},
        "non_synthetic_comparison_readiness": {
            "eligible_for_real_feature_backfill": False,
            "eligible_for_champion_challenger_unlock": False,
            "reasons": ["no_active_market_sources"],
        },
        "prohibited_outputs": PROHIBITED_OUTPUTS,
        "research_use_only": True,
    }


def _gate_state(checks_path: Path) -> dict[str, bool]:
    rows: list[dict[str, str]] = []
    with checks_path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    out: dict[str, bool] = {}
    for gate in GATE_IDS:
        if gate == "G9_PROVENANCE":
            relevant = [r for r in rows if str(r.get("gate_id", "")).startswith("G9_")]
        else:
            relevant = [r for r in rows if r.get("gate_id") == gate]
        out[gate] = bool(relevant) and all(str(r.get("passed", "")).lower() == "true" for r in relevant)
    return out


def _gate_transitions(before: dict[str, bool], after: dict[str, bool]) -> dict:
    closed = [g for g in GATE_IDS if not before.get(g, False) and after.get(g, False)]
    opened = [g for g in GATE_IDS if before.get(g, False) and not after.get(g, False)]
    unchanged = [g for g in GATE_IDS if before.get(g, False) == after.get(g, False)]
    return {"closed_gates": closed, "opened_gates": opened, "unchanged_gates": unchanged}


def _ledger_entries(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def verify_ledger(path: Path) -> dict:
    prev = ""
    entries = _ledger_entries(path)
    for i, row in enumerate(entries):
        if row.get("previous_receipt_hash", "") != prev:
            return {"valid": False, "entry_count": len(entries), "error": f"previous hash mismatch at index {i}"}
        payload = dict(row)
        stored = str(payload.pop("receipt_hash", ""))
        calc = _json_hash(payload)
        if stored != calc:
            return {"valid": False, "entry_count": len(entries), "error": f"receipt hash mismatch at index {i}"}
        prev = stored
    return {"valid": True, "entry_count": len(entries), "head_hash": prev}


def _append_ledger(path: Path, receipt: dict) -> dict:
    audit = verify_ledger(path)
    if not audit["valid"]:
        raise OrchestratorError(f"Step 21 ledger invalid: {audit.get('error')}")
    payload = dict(receipt)
    payload["previous_receipt_hash"] = audit.get("head_hash", "")
    payload["receipt_hash"] = _json_hash(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, sort_keys=True) + "\n")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return payload


def _refresh_all(*, root: Path, runtime_dir: Path, expected_champion_sha256: str) -> dict:
    meta_active, market_active = _ensure_runtime(runtime_dir)
    current = runtime_dir / "current"
    events = root / "data/processed/historical_events.csv"
    symbol_dates = root / "data/processed/coverage_plan_real/symbol_date_requirements.csv"

    resolver_dir = current / "metadata_resolver"
    shutil.rmtree(resolver_dir, ignore_errors=True)
    readiness = metadata_resolver.build(events, symbol_dates, meta_active, resolver_dir)
    quality_dir = current / "metadata_quality"
    shutil.rmtree(quality_dir, ignore_errors=True)
    quality = metadata_quality.build(events_path=events, symbol_dates_path=symbol_dates, contract_path=meta_active,
                                     resolver_dir=resolver_dir, outdir=quality_dir)

    coverage_dir = current / "coverage"
    shutil.rmtree(coverage_dir, ignore_errors=True)
    coverage = coverage_planner.build(events, coverage_dir, contract_path=market_active)

    market_obj = _read_json(market_active)
    market_dir = current / "market_backfill"
    shutil.rmtree(market_dir, ignore_errors=True)
    market_dir.mkdir(parents=True, exist_ok=True)
    if market_obj.get("sources"):
        market_manifest = hmb.build(market_active, events, market_dir, pre_minutes=30, post_minutes=30)
    else:
        market_manifest = _empty_market_manifest(market_active, events)
        _write_json(market_dir / "historical_market_backfill_manifest.json", market_manifest, mode=0o600)

    release_dir = current / "evaluation_release"
    shutil.rmtree(release_dir, ignore_errors=True)
    assessment = erc.assess_release(
        coverage_summary=coverage_dir / "coverage_summary.json",
        market_backfill_manifest=market_dir / "historical_market_backfill_manifest.json",
        market_contract=market_active,
        historical_events=events,
        metadata_readiness=resolver_dir / "metadata_readiness_summary.json",
        metadata_quality=quality_dir / "metadata_quality_summary.json",
        matched_controls=root / "data/examples/model_training_matched_controls.csv",
        base_features=root / "data/examples/model_training_feature_vectors.csv",
        graph_features=root / "data/examples/model_training_graph_features.csv",
        champion_bundle=root / "data/processed/model_demo/model_bundle.joblib",
        champion_training_manifest=root / "data/processed/model_demo/training_manifest.json",
        challenger_manifest=root / "data/processed/graph_challenger_demo/challenger_manifest.json",
        challenger_cv_audit=root / "data/processed/graph_challenger_demo/cv_split_audit.json",
        output_dir=release_dir,
        expected_champion_sha256=expected_champion_sha256,
        holdout_start_year=2015,
    )
    gates = _gate_state(release_dir / "evaluation_release_checks.csv")
    return {
        "readiness": readiness,
        "quality": quality,
        "coverage": coverage,
        "market_manifest": market_manifest,
        "assessment": assessment,
        "gate_state": gates,
        "paths": {
            "metadata_readiness": str(resolver_dir / "metadata_readiness_summary.json"),
            "metadata_quality": str(quality_dir / "metadata_quality_summary.json"),
            "coverage_summary": str(coverage_dir / "coverage_summary.json"),
            "market_backfill_manifest": str(market_dir / "historical_market_backfill_manifest.json"),
            "evaluation_release_assessment": str(release_dir / "evaluation_release_assessment.json"),
            "evaluation_release_checks": str(release_dir / "evaluation_release_checks.csv"),
            "release_token": str(release_dir / "evaluation_release_token.json") if (release_dir / "evaluation_release_token.json").exists() else "",
        },
    }


def _copy_report_file(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def orchestrate_batch(*, root: Path, batch_manifest: Path, runtime_dir: Path, outdir: Path,
                      expected_champion_sha256: str) -> dict:
    root = root.resolve()
    runtime_dir = runtime_dir.resolve()
    outdir = outdir.resolve()
    manifest = load_batch_manifest(batch_manifest)
    batch_id = str(manifest.get("batch_id", "")).strip() or f"batch-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    batch_id = _validate_path_component(batch_id, label="batch_id")
    batch_dir = _contained_child(outdir, batch_id, label="batch_id")
    batch_dir.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(batch_dir, 0o700)
    except OSError:
        pass
    meta_active, market_active = _ensure_runtime(runtime_dir)
    ledger_path = runtime_dir / "authorized_input_ingestion_ledger.jsonl"

    champion = root / "data/processed/model_demo/model_bundle.joblib"
    champion_before = _sha256(champion)
    if champion_before != expected_champion_sha256:
        raise OrchestratorError(f"frozen champion hash mismatch before ingestion: {champion_before}")

    current = _refresh_all(root=root, runtime_dir=runtime_dir, expected_champion_sha256=expected_champion_sha256)
    batch_start_gate_state = dict(current["gate_state"])
    file_receipts: list[dict] = []

    work_items: list[tuple[str, Path, str, dict]] = []
    for domain in ("metadata", "market"):
        block = manifest.get(domain)
        if not block:
            continue
        contract = _resolve_from_root(root, str(block["source_contract"]))
        if not contract.exists():
            raise FileNotFoundError(f"{domain} source contract missing: {contract}")
        raw, by_id = _load_contract_rows(contract)
        source_ids = _selected_source_ids(contract, block.get("source_ids"))
        for sid in source_ids:
            work_items.append((domain, contract, sid, by_id[sid]))

    for ordinal, (domain, contract, source_id, source_row) in enumerate(work_items, 1):
        before = dict(current["gate_state"])
        imported_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        controlled = _prepare_controlled_source(runtime_dir=runtime_dir, domain=domain, contract=contract, source_id=source_id, source=source_row)
        info_id = str(controlled["information_id"]); snapshot = controlled["snapshot"]; policy = controlled["policy"]
        controlled_contract = Path(controlled["controlled_contract"]); controlled_row = controlled["controlled_row"]
        db_path = runtime_dir / "control" / "control.sqlite"

        if policy.decision != "ADMIT_STRUCTURED":
            if policy.decision == "QUARANTINE":
                quarantine_path = control_storage.quarantine_snapshot(snapshot, runtime_dir / "control")
                if control_registry.current_state(db_path, info_id) != "QUARANTINED":
                    control_registry.append_event(db_path, info_id, "QUARANTINED", "QUARANTINED", {"reason": policy.reason})
                    control_registry.add_location(db_path, info_id, "QUARANTINE", control_storage.path_fingerprint(quarantine_path), snapshot.sha256)
                import_status = "QUARANTINED"
            else:
                if control_registry.current_state(db_path, info_id) != "REVIEW_REQUIRED":
                    control_registry.append_event(db_path, info_id, "REVIEW_REQUIRED", "REVIEW_REQUIRED", {"reason": policy.reason})
                import_status = "REVIEW_REQUIRED"
            after = dict(before); transitions = _gate_transitions(before, after)
            receipt = {
                "ledger_schema_version": LEDGER_SCHEMA_VERSION, "step_schema_version": SCHEMA_VERSION,
                "batch_id": batch_id, "ordinal": ordinal, "domain": domain, "source_contract": str(contract),
                "source_contract_sha256": _sha256(contract), "source_id": source_id, "source_sha256": snapshot.sha256,
                "holding_sha256": snapshot.sha256, "size_bytes": snapshot.size_bytes,
                "data_classification": source_row.get("data_classification", ""), "record_kind": source_row.get("record_kind", ""),
                "source_family": source_row.get("source_family", ""), "trade_date": source_row.get("trade_date", ""),
                "license_reference": source_row.get("license_reference", ""), "import_status": import_status,
                "imported_at_utc": imported_at, "potential_gates": _source_gates(domain, source_row),
                "before_gate_state": before, "after_gate_state": after, **transitions,
                "evaluation_release_permitted_after": bool(current["assessment"].get("evaluation_release_permitted")),
                "information_id": info_id, "control_state": control_registry.current_state(db_path, info_id),
                "source_policy_decision": policy.decision, "source_policy_reason": policy.reason,
                "received_at_utc": controlled["received_at_utc"], "source_path_fingerprint": snapshot.source_path_fingerprint,
                "control_event_head": control_registry.event_head(db_path, info_id),
                "research_use_only": True, "prohibited_outputs": PROHIBITED_OUTPUTS,
            }
            ledger_receipt = _append_ledger(ledger_path, receipt); receipt["receipt_hash"] = ledger_receipt["receipt_hash"]; file_receipts.append(receipt)
            continue

        try:
            if domain == "metadata":
                metadata_population.validate_source_file(controlled_contract, controlled_row)
                result = metadata_population.populate_batch(
                    events=root / "data/processed/historical_events.csv",
                    symbol_dates=root / "data/processed/coverage_plan_real/symbol_date_requirements.csv",
                    source_contract=controlled_contract, runtime_dir=runtime_dir / "metadata",
                    outdir=batch_dir / "metadata_population", source_ids=[source_id],
                    batch_id=f"{batch_id}-metadata-{ordinal:04d}-{_safe_id(source_id)}",
                )
                no_op = result.get("status") == "NO_OP"
                if no_op:
                    validation = metadata_population.validate_source_file(controlled_contract, controlled_row)
                    source_receipt = {"source_id":source_id,"status":"NO_OP","sha256":validation["sha256"],
                        "source_path":validation["path"],"size_bytes":validation["size_bytes"],
                        "data_classification":source_row.get("data_classification",""),"record_kind":source_row.get("record_kind",""),
                        "source_family":source_row.get("source_family",""),"license_reference":source_row.get("license_reference","")}
                else:
                    srcs=result.get("batch_receipt",{}).get("sources",[])
                    if len(srcs)!=1: raise OrchestratorError(f"unexpected metadata population receipt for {source_id}")
                    source_receipt=dict(srcs[0])|{"status":"IMPORTED"}
            else:
                hmb.load_contract(controlled_contract)
                _, source_receipt, no_op = _validate_and_stage_market_source(contract=controlled_contract, source=controlled_row, market_runtime=runtime_dir / "market")
            if no_op:
                control_registry.append_event(db_path, info_id, "NO_OP_REFERENCED", "ADMITTED_STRUCTURED")
            elif control_registry.current_state(db_path, info_id) != "ADMITTED_STRUCTURED":
                control_registry.append_event(db_path, info_id, "ADMITTED", "ADMITTED_STRUCTURED")
        except Exception as exc:
            control_registry.append_event(db_path, info_id, "IMPORT_FAILED", "IMPORT_FAILED", {"error_type": type(exc).__name__})
            raise

        current = _refresh_all(root=root, runtime_dir=runtime_dir, expected_champion_sha256=expected_champion_sha256)
        after = dict(current["gate_state"]); transitions = _gate_transitions(before, after)
        receipt = {
            "ledger_schema_version": LEDGER_SCHEMA_VERSION, "step_schema_version": SCHEMA_VERSION,
            "batch_id": batch_id, "ordinal": ordinal, "domain": domain, "source_contract": str(contract),
            "source_contract_sha256": _sha256(contract), "source_id": source_id,
            "source_sha256": source_receipt.get("sha256", ""), "size_bytes": source_receipt.get("size_bytes", 0),
            "data_classification": source_receipt.get("data_classification", source_row.get("data_classification", "")),
            "record_kind": source_receipt.get("record_kind", source_row.get("record_kind", "")),
            "source_family": source_receipt.get("source_family", source_row.get("source_family", "")),
            "trade_date": source_receipt.get("trade_date", source_row.get("trade_date", "")),
            "license_reference": source_receipt.get("license_reference", source_row.get("license_reference", "")),
            "import_status": "NO_OP" if no_op else "IMPORTED", "imported_at_utc": imported_at,
            "potential_gates": _source_gates(domain, source_row), "before_gate_state": before, "after_gate_state": after, **transitions,
            "evaluation_release_permitted_after": bool(current["assessment"].get("evaluation_release_permitted")),
            "information_id": info_id, "control_state": control_registry.current_state(db_path, info_id),
            "source_policy_decision": policy.decision, "source_policy_reason": policy.reason,
            "received_at_utc": controlled["received_at_utc"], "holding_sha256": snapshot.sha256,
            "source_path_fingerprint": snapshot.source_path_fingerprint, "control_event_head": control_registry.event_head(db_path, info_id),
            "research_use_only": True, "prohibited_outputs": PROHIBITED_OUTPUTS,
        }
        ledger_receipt = _append_ledger(ledger_path, receipt); receipt["receipt_hash"] = ledger_receipt["receipt_hash"]; file_receipts.append(receipt)

    champion_after = _sha256(champion)
    if champion_after != champion_before:
        raise AssertionError("frozen champion changed during Step 21 ingestion")

    final_gate_state = dict(current["gate_state"])
    batch_transition = _gate_transitions(batch_start_gate_state, final_gate_state)
    gate_map_rows = []
    for r in file_receipts:
        gate_map_rows.append({
            "ordinal": r["ordinal"], "domain": r["domain"], "source_id": r["source_id"],
            "source_sha256": r["source_sha256"], "data_classification": r["data_classification"],
            "record_kind": r["record_kind"], "source_family": r["source_family"], "trade_date": r["trade_date"],
            "import_status": r["import_status"], "potential_gates": ";".join(r["potential_gates"]),
            "closed_gates": ";".join(r["closed_gates"]), "opened_gates": ";".join(r["opened_gates"]),
            "evaluation_release_permitted_after": int(bool(r["evaluation_release_permitted_after"])),
            "research_use_only": 1,
        })
    gate_map_path = batch_dir / "imported_file_gate_map.csv"
    with gate_map_path.open("w", newline="", encoding="utf-8") as f:
        fields = list(gate_map_rows[0].keys()) if gate_map_rows else ["source_id"]
        w = csv.DictWriter(f, fieldnames=fields); w.writeheader(); w.writerows(gate_map_rows)

    # Copy only derived/audit artifacts. Raw staged input files remain private in runtime_dir/staged.
    current_paths = current["paths"]
    report_files = {
        "metadata_readiness_summary.json": Path(current_paths["metadata_readiness"]),
        "metadata_quality_summary.json": Path(current_paths["metadata_quality"]),
        "coverage_summary.json": Path(current_paths["coverage_summary"]),
        "historical_market_backfill_manifest.json": Path(current_paths["market_backfill_manifest"]),
        "evaluation_release_assessment.json": Path(current_paths["evaluation_release_assessment"]),
        "evaluation_release_checks.csv": Path(current_paths["evaluation_release_checks"]),
    }
    for name, src in report_files.items():
        _copy_report_file(src, batch_dir / name)
    token_src = Path(current_paths["release_token"]) if current_paths["release_token"] else None
    if token_src and token_src.exists():
        _copy_report_file(token_src, batch_dir / "evaluation_release_token.json")

    summary = {
        "schema_version": SCHEMA_VERSION,
        "batch_id": batch_id,
        "purpose": "Authorized-input ingestion orchestrator for offline historical MNPI/informed-trading surveillance research; no trading outputs.",
        "source_file_count": len(file_receipts),
        "imported_file_count": sum(r["import_status"] == "IMPORTED" for r in file_receipts),
        "no_op_file_count": sum(r["import_status"] == "NO_OP" for r in file_receipts),
        "batch_start_gate_state": batch_start_gate_state,
        "batch_end_gate_state": final_gate_state,
        "batch_gate_transitions": batch_transition,
        "evaluation_release_permitted": bool(current["assessment"].get("evaluation_release_permitted")),
        "evaluation_release_token_issued": bool((batch_dir / "evaluation_release_token.json").exists()),
        "blocking_failures": current["assessment"].get("blocking_failures", []),
        "champion_sha256_before": champion_before,
        "champion_sha256_after": champion_after,
        "champion_unchanged": champion_before == champion_after,
        "ledger": verify_ledger(ledger_path),
        "control_plane_integrity": control_integrity.verify_control_plane(
            runtime_dir / "control" / "control.sqlite", runtime_dir / "control", [meta_active, market_active]
        ),
        "raw_input_files_copied_to_report_bundle": False,
        "external_fetch_or_purchase_performed": False,
        "broker_or_execution_integration_present": False,
        "research_use_only": True,
        "prohibited_outputs": PROHIBITED_OUTPUTS,
        "file_receipts": file_receipts,
    }
    _write_json(batch_dir / "authorized_input_batch_summary.json", summary, mode=0o600)
    _write_json(outdir / "authorized_input_ingestion_status.json", summary, mode=0o600)
    return summary | {"batch_dir": str(batch_dir), "gate_map_path": str(gate_map_path)}


def assess_current(*, root: Path, runtime_dir: Path, outdir: Path, expected_champion_sha256: str) -> dict:
    _ensure_runtime(runtime_dir)
    current = _refresh_all(root=root.resolve(), runtime_dir=runtime_dir.resolve(), expected_champion_sha256=expected_champion_sha256)
    outdir.mkdir(parents=True, exist_ok=True)
    summary = {
        "schema_version": SCHEMA_VERSION,
        "purpose": "Current Step 21 ingestion/readiness state without importing external inputs.",
        "gate_state": current["gate_state"],
        "evaluation_release_permitted": current["assessment"].get("evaluation_release_permitted", False),
        "blocking_failures": current["assessment"].get("blocking_failures", []),
        "release_token_issued": bool(current["paths"]["release_token"]),
        "ledger": verify_ledger(runtime_dir / "authorized_input_ingestion_ledger.jsonl"),
        "control_plane_integrity": control_integrity.verify_control_plane(
            runtime_dir / "control" / "control.sqlite", runtime_dir / "control",
            [runtime_dir / "metadata" / "active_metadata_sources.json", runtime_dir / "market" / "active_market_sources.json"],
        ),
        "research_use_only": True,
        "external_fetch_or_purchase_performed": False,
        "prohibited_outputs": PROHIBITED_OUTPUTS,
    }
    _write_json(outdir / "authorized_input_current_assessment.json", summary, mode=0o600)
    return summary


def main() -> None:
    ap = argparse.ArgumentParser(description="Authorized-input ingestion orchestrator for the private historical surveillance prototype")
    sub = ap.add_subparsers(dest="command", required=True)
    run = sub.add_parser("ingest")
    run.add_argument("--root", type=Path, required=True)
    run.add_argument("--batch-manifest", type=Path, required=True)
    run.add_argument("--runtime-dir", type=Path, required=True)
    run.add_argument("--outdir", type=Path, required=True)
    run.add_argument("--expected-champion-sha256", required=True)
    cur = sub.add_parser("assess-current")
    cur.add_argument("--root", type=Path, required=True)
    cur.add_argument("--runtime-dir", type=Path, required=True)
    cur.add_argument("--outdir", type=Path, required=True)
    cur.add_argument("--expected-champion-sha256", required=True)
    ver = sub.add_parser("verify-ledger")
    ver.add_argument("--runtime-dir", type=Path, required=True)
    a = ap.parse_args()
    if a.command == "verify-ledger":
        print(json.dumps(verify_ledger(a.runtime_dir / "authorized_input_ingestion_ledger.jsonl"), indent=2, sort_keys=True)); return
    if a.command == "assess-current":
        result = assess_current(root=a.root, runtime_dir=a.runtime_dir, outdir=a.outdir, expected_champion_sha256=a.expected_champion_sha256)
    else:
        result = orchestrate_batch(root=a.root, batch_manifest=a.batch_manifest, runtime_dir=a.runtime_dir,
                                   outdir=a.outdir, expected_champion_sha256=a.expected_champion_sha256)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
