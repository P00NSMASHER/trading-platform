from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import metadata_resolver
import metadata_quality

SCHEMA_VERSION = "0.19.0"
LEDGER_SCHEMA_VERSION = "1"

NUMERIC_PROGRESS_FIELDS = [
    "announcement_exact_resolved",
    "announcement_proxy_only",
    "event_exchange_resolved",
    "event_exchange_nasdaq",
    "shares_symbol_dates_resolved",
    "control_dates_resolved",
    "control_dates_partial",
]
GATE_FIELDS = [
    "ready_g1_announcement_times",
    "ready_g3_primary_listing_history",
    "ready_g4_shares_outstanding",
    "ready_g5_matched_control_universe",
    "ready_for_step15_real_backfill_metadata",
    "ready_for_non_synthetic_model_evaluation_metadata",
    "quality_gate_clear",
    "quality_cleared_for_non_synthetic_model_evaluation",
]
PROHIBITED_OUTPUTS = metadata_resolver.PROHIBITED_OUTPUTS


class PopulationError(ValueError):
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


def _read_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, obj: object, *, mode: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)
    if mode is not None:
        try:
            os.chmod(path, mode)
        except OSError:
            pass


def _write_csv(path: Path, rows: Iterable[dict]) -> None:
    rows = list(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)


def _load_contract_raw(path: Path) -> dict:
    raw = json.loads(path.read_text(encoding="utf-8"))
    # Reuse the strict resolver validation, including prohibited source classes.
    metadata_resolver.load_contract(path)
    return raw


def _resolve_source_path(contract_path: Path, source: dict) -> Path:
    p = Path(str(source.get("path", "")))
    if not p.is_absolute():
        p = (contract_path.parent.parent / p).resolve()
    return p


def _required_columns(source: dict) -> list[str]:
    kind = source.get("record_kind")
    family = source.get("source_family")
    if kind == "announcement_timestamp":
        return ["historical_symbol", "event_date", "public_announcement_ts"]
    if kind == "security_master":
        # A Daily TAQ Master-style row can close exchange, shares, or both.
        return ["historical_symbol", "effective_date"]
    if kind == "shares_outstanding":
        req = ["historical_symbol", "fact_date", "shares_outstanding"]
        if family == "sec_xbrl_companyfacts":
            req.append("available_at")
        return req
    if kind == "control_universe":
        return ["historical_symbol", "event_date"]
    return []


def _mapped_column(source: dict, canonical: str) -> str:
    return str(source.get("column_map", {}).get(canonical, canonical))


def validate_source_file(contract_path: Path, source: dict) -> dict:
    if not source.get("enabled", True):
        return {"source_id": source.get("source_id", ""), "status": "disabled"}
    classification = str(source.get("data_classification", ""))
    if classification == "authorized_reference_data":
        if not source.get("authorized", False):
            raise PopulationError(f"{source.get('source_id')}: authorized_reference_data requires authorized=true")
        if not str(source.get("license_reference", "")).strip():
            raise PopulationError(f"{source.get('source_id')}: license_reference is required")
    elif classification in {"public_official_data", "public_research_replication"}:
        if not str(source.get("license_reference", "")).strip():
            raise PopulationError(f"{source.get('source_id')}: public source reference is required in license_reference")

    p = _resolve_source_path(contract_path, source)
    if not p.exists() or not p.is_file():
        raise FileNotFoundError(f"{source.get('source_id')}: source file not found: {p}")

    delimiter = metadata_resolver._delim(str(source.get("delimiter", ",")))
    encoding = str(source.get("encoding", "utf-8"))
    with p.open(newline="", encoding=encoding) as f:
        reader = csv.DictReader(f, delimiter=delimiter)
        header = reader.fieldnames or []
        first = next(reader, None)
    aliases = {
        "historical_symbol": ["historical_symbol", "symbol"],
        "event_date": ["event_date", "trade_date"],
        "effective_date": ["effective_date", "trade_date"],
        "public_announcement_ts": ["public_announcement_ts", "timestamp"],
        "shares_outstanding": ["shares_outstanding", "shares_outstanding_millions"],
        "fact_date": ["fact_date", "effective_date", "trade_date"],
    }
    for canonical in _required_columns(source):
        candidates = aliases.get(canonical, [canonical])
        mapped_candidates = [_mapped_column(source, x) for x in candidates]
        if not any(c in header for c in mapped_candidates):
            raise PopulationError(
                f"{source.get('source_id')}: missing required column for {canonical}; expected one of {mapped_candidates!r}"
            )
    if first is None:
        raise PopulationError(f"{source.get('source_id')}: source file is empty")

    if source.get("record_kind") == "security_master":
        exchange_cols = {_mapped_column(source, "primary_exchange"), _mapped_column(source, "listed_exchange")}
        shares_cols = {_mapped_column(source, "shares_outstanding"), _mapped_column(source, "shares_outstanding_millions")}
        if not (set(header) & exchange_cols or set(header) & shares_cols):
            raise PopulationError(f"{source.get('source_id')}: security_master must expose exchange and/or shares outstanding")

    return {
        "source_id": str(source.get("source_id", "")),
        "status": "validated",
        "path": str(p),
        "sha256": _sha256(p),
        "size_bytes": p.stat().st_size,
        "header": header,
        "classification": classification,
        "record_kind": str(source.get("record_kind", "")),
        "source_family": str(source.get("source_family", "")),
    }


def _initial_active_contract() -> dict:
    return {
        "schema_version": "1",
        "purpose": "Cumulative point-in-time metadata sources populated by Step 18",
        "sources": [],
    }


def _load_active_contract(path: Path) -> dict:
    raw = _read_json(path, _initial_active_contract())
    if raw.get("schema_version") != "1" or not isinstance(raw.get("sources"), list):
        raise PopulationError("active contract is malformed")
    return raw


def _source_key(source: dict) -> str:
    return str(source.get("source_id", ""))


def _stage_source(runtime_dir: Path, contract_path: Path, source: dict, validation: dict) -> tuple[dict, dict]:
    src_path = Path(validation["path"])
    sha = validation["sha256"]
    source_id = _source_key(source)
    safe_id = "".join(c if c.isalnum() or c in "-_" else "_" for c in source_id)
    dest_dir = runtime_dir / "staged" / safe_id
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
        raise PopulationError(f"staged copy hash mismatch for {source_id}")

    staged = dict(source)
    staged["path"] = str(dest.resolve())
    staged["enabled"] = True
    receipt = {
        "source_id": source_id,
        "record_kind": source.get("record_kind"),
        "source_family": source.get("source_family"),
        "data_classification": source.get("data_classification"),
        "source_path": str(src_path),
        "staged_path": str(dest),
        "sha256": sha,
        "size_bytes": validation["size_bytes"],
        "license_reference": source.get("license_reference", ""),
    }
    return staged, receipt


def _resolver_summary(events: Path, symbol_dates: Path, active_contract: Path, outdir: Path) -> dict:
    return metadata_resolver.build(events, symbol_dates, active_contract, outdir)


def _quality_summary(events: Path, symbol_dates: Path, active_contract: Path, resolver_dir: Path, outdir: Path) -> dict:
    return metadata_quality.build(events_path=events, symbol_dates_path=symbol_dates, contract_path=active_contract,
                                  resolver_dir=resolver_dir, outdir=outdir)


def _combined_state(readiness: dict, quality: dict) -> dict:
    out = dict(readiness)
    out["quality_gate_clear"] = bool(quality.get("quality_gate_clear", False))
    out["quality_cleared_for_non_synthetic_model_evaluation"] = bool(
        quality.get("quality_cleared_for_non_synthetic_model_evaluation", False)
    )
    return out


def _delta(before: dict, after: dict) -> dict:
    numeric = {k: int(after.get(k, 0)) - int(before.get(k, 0)) for k in NUMERIC_PROGRESS_FIELDS}
    gates = {}
    for k in GATE_FIELDS:
        b = bool(before.get(k, False)); a = bool(after.get(k, False))
        gates[k] = {"before": b, "after": a, "transition": "BLOCKED_TO_READY" if (not b and a) else "READY_TO_BLOCKED" if (b and not a) else "UNCHANGED"}
    return {"numeric_progress": numeric, "gate_transitions": gates}


def _ledger_entries(path: Path) -> list[dict]:
    if not path.exists():
        return []
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip(): entries.append(json.loads(line))
    return entries


def verify_ledger(path: Path) -> dict:
    entries = _ledger_entries(path)
    prev = ""
    for i, entry in enumerate(entries):
        expected_prev = entry.get("previous_receipt_hash", "")
        if expected_prev != prev:
            return {"valid": False, "entry_count": len(entries), "error": f"previous hash mismatch at index {i}"}
        payload = dict(entry); stored = payload.pop("receipt_hash", "")
        calc = _json_hash(payload)
        if calc != stored:
            return {"valid": False, "entry_count": len(entries), "error": f"receipt hash mismatch at index {i}"}
        prev = stored
    return {"valid": True, "entry_count": len(entries), "head_hash": prev}


def _append_ledger(path: Path, receipt: dict) -> dict:
    check = verify_ledger(path)
    if not check["valid"]:
        raise PopulationError(f"population ledger is invalid: {check.get('error')}")
    payload = dict(receipt)
    payload["previous_receipt_hash"] = check.get("head_hash", "")
    payload["receipt_hash"] = _json_hash(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, sort_keys=True) + "\n")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return payload


def populate_batch(*, events: Path, symbol_dates: Path, source_contract: Path, runtime_dir: Path, outdir: Path, source_ids: list[str] | None = None, batch_id: str | None = None) -> dict:
    runtime_dir.mkdir(parents=True, exist_ok=True)
    outdir.mkdir(parents=True, exist_ok=True)
    for d in (runtime_dir, outdir):
        try: os.chmod(d, 0o700)
        except OSError: pass

    raw = _load_contract_raw(source_contract)
    selected = [s for s in raw["sources"] if s.get("enabled", True) and (not source_ids or str(s.get("source_id")) in source_ids)]
    if source_ids:
        missing_ids = sorted(set(source_ids) - {str(s.get("source_id")) for s in selected})
        if missing_ids:
            raise PopulationError(f"requested source_ids not found/enabled: {missing_ids}")
    if not selected:
        raise PopulationError("no enabled metadata sources selected")

    active_path = runtime_dir / "active_metadata_sources.json"
    ledger_path = runtime_dir / "metadata_population_ledger.jsonl"
    active = _load_active_contract(active_path)

    # Ensure an initial empty readiness snapshot exists for a true before/after delta.
    baseline_contract_path = runtime_dir / "baseline_empty_contract.json"
    if not baseline_contract_path.exists():
        _write_json(baseline_contract_path, _initial_active_contract(), mode=0o600)
    current_snapshot_dir = runtime_dir / "current_resolver"
    before_contract = active_path if active_path.exists() else baseline_contract_path
    before_resolver_dir = current_snapshot_dir / "before"
    before = _resolver_summary(events, symbol_dates, before_contract, before_resolver_dir)
    before_quality = _quality_summary(events, symbol_dates, before_contract, before_resolver_dir, current_snapshot_dir / "before_quality")
    before_state = _combined_state(before, before_quality)

    existing_pairs = {(str(s.get("source_id")), Path(str(s.get("path", ""))).name.split(".")[0]) for s in active.get("sources", [])}
    staged_sources = []
    source_receipts = []
    no_op_sources = []
    by_id = {str(s.get("source_id")): s for s in active.get("sources", [])}
    for source in selected:
        validation = validate_source_file(source_contract, source)
        source_id = str(source.get("source_id"))
        sha = validation["sha256"]
        current = by_id.get(source_id)
        if current and Path(str(current.get("path", ""))).name.startswith(sha):
            no_op_sources.append({"source_id": source_id, "sha256": sha, "reason": "identical hash already active"})
            continue
        staged, receipt = _stage_source(runtime_dir, source_contract, source, validation)
        by_id[source_id] = staged
        staged_sources.append(staged)
        source_receipts.append(receipt)

    if not source_receipts:
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "NO_OP",
            "batch_id": batch_id or "no-op",
            "no_op_sources": no_op_sources,
            "ledger": verify_ledger(ledger_path),
            "before_summary": before,
            "after_summary": before,
            "before_quality": before_quality,
            "after_quality": before_quality,
            "coverage_delta": _delta(before_state, before_state),
            "research_use_only": True,
            "prohibited_outputs": PROHIBITED_OUTPUTS,
        }

    active = _initial_active_contract()
    active["sources"] = [by_id[k] for k in sorted(by_id)]
    _write_json(active_path, active, mode=0o600)
    active_hash = _sha256(active_path)

    after_dir = current_snapshot_dir / "after"
    after = _resolver_summary(events, symbol_dates, active_path, after_dir)
    after_quality_dir = current_snapshot_dir / "after_quality"
    after_quality = _quality_summary(events, symbol_dates, active_path, after_dir, after_quality_dir)
    after_state = _combined_state(after, after_quality)
    delta = _delta(before_state, after_state)

    now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    batch_id = batch_id or f"batch-{now.replace(':','').replace('-','')}-{source_receipts[0]['sha256'][:8]}"
    receipt = {
        "ledger_schema_version": LEDGER_SCHEMA_VERSION,
        "step_schema_version": SCHEMA_VERSION,
        "batch_id": batch_id,
        "imported_at": now,
        "source_contract": str(source_contract),
        "source_contract_sha256": _sha256(source_contract),
        "events_sha256": _sha256(events),
        "symbol_dates_sha256": _sha256(symbol_dates),
        "active_contract_path": str(active_path),
        "active_contract_sha256": active_hash,
        "sources": source_receipts,
        "no_op_sources": no_op_sources,
        "before_gate_state": {k: bool(before_state.get(k, False)) for k in GATE_FIELDS},
        "after_gate_state": {k: bool(after_state.get(k, False)) for k in GATE_FIELDS},
        "coverage_delta": delta,
        "research_use_only": True,
        "prohibited_outputs": PROHIBITED_OUTPUTS,
    }
    receipt = _append_ledger(ledger_path, receipt)

    batch_dir = outdir / batch_id
    batch_dir.mkdir(parents=True, exist_ok=True)
    # Copy resolver output snapshots into immutable batch report directory (metadata only, no raw source data).
    for src_file in after_dir.glob("*"):
        if src_file.is_file():
            shutil.copy2(src_file, batch_dir / src_file.name)
    for src_file in after_quality_dir.glob("*"):
        if src_file.is_file():
            shutil.copy2(src_file, batch_dir / src_file.name)
    _write_json(batch_dir / "batch_receipt.json", receipt)
    _write_json(batch_dir / "coverage_delta.json", delta)
    _write_json(batch_dir / "before_summary.json", before)
    _write_json(batch_dir / "after_summary.json", after)
    _write_json(batch_dir / "before_quality.json", before_quality)
    _write_json(batch_dir / "after_quality.json", after_quality)

    cumulative = {
        "schema_version": SCHEMA_VERSION,
        "last_batch_id": batch_id,
        "last_imported_at": now,
        "active_source_count": len(active["sources"]),
        "active_contract_sha256": active_hash,
        "ledger": verify_ledger(ledger_path),
        "current_readiness": after,
        "current_quality": after_quality,
        "evaluation_release_gate": bool(after_quality.get("quality_cleared_for_non_synthetic_model_evaluation", False)),
        "last_coverage_delta": delta,
        "research_use_only": True,
        "prohibited_outputs": PROHIBITED_OUTPUTS,
    }
    _write_json(outdir / "metadata_population_status.json", cumulative)
    return cumulative | {"batch_receipt": receipt, "batch_dir": str(batch_dir)}


def main() -> None:
    ap = argparse.ArgumentParser(description="Populate point-in-time metadata in hashed batches and report readiness deltas")
    ap.add_argument("--events", type=Path, required=True)
    ap.add_argument("--symbol-dates", type=Path, required=True)
    ap.add_argument("--source-contract", type=Path, required=True)
    ap.add_argument("--runtime-dir", type=Path, required=True)
    ap.add_argument("--outdir", type=Path, required=True)
    ap.add_argument("--source-id", action="append", dest="source_ids")
    ap.add_argument("--batch-id")
    ap.add_argument("--verify-ledger", action="store_true")
    args = ap.parse_args()
    if args.verify_ledger:
        print(json.dumps(verify_ledger(args.runtime_dir / "metadata_population_ledger.jsonl"), indent=2)); return
    result = populate_batch(events=args.events, symbol_dates=args.symbol_dates, source_contract=args.source_contract,
                            runtime_dir=args.runtime_dir, outdir=args.outdir, source_ids=args.source_ids, batch_id=args.batch_id)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
