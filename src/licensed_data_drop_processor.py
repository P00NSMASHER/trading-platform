from __future__ import annotations

import argparse
import csv
import hashlib
import json
import time
from pathlib import Path
from typing import Any

import licensed_data_intake as intake
import real_data_replay

SCHEMA_VERSION = "1.0.0"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    obj = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return obj


def _write_json(path: Path, obj: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _load_inventory(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(path)
    with path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    out: dict[str, dict[str, str]] = {}
    for row in rows:
        digest = (row.get("sha256") or "").strip().lower()
        if digest:
            out[digest] = row
    return out


def _validate_entitlement_entry(entry: dict[str, Any], inventory: dict[str, dict[str, str]]) -> tuple[dict[str, Any] | None, str]:
    digest = str(entry.get("sha256") or "").strip().lower()
    if len(digest) != 64:
        return None, "invalid_or_missing_sha256"
    row = inventory.get(digest)
    if row is None:
        return None, "sha256_not_present_in_intake_inventory"

    authorized = bool(entry.get("authorized"))
    if not authorized:
        return None, "authorized_must_be_true"

    license_reference = str(entry.get("license_reference") or "").strip()
    if not license_reference:
        return None, "license_reference_required"

    intake_status = (row.get("status") or "").strip()
    if intake_status != "PENDING_AUTHORIZATION_AND_REVIEW":
        return None, f"intake_status_not_activatable:{intake_status}"

    source_family = str(entry.get("source_family") or row.get("candidate_source_family") or "").strip()
    record_kind = str(entry.get("record_kind") or row.get("candidate_record_kind") or "").strip()
    trade_date = str(entry.get("trade_date") or row.get("detected_trade_date") or "").strip()
    if source_family != (row.get("candidate_source_family") or "").strip():
        return None, "source_family_mismatch_with_intake"
    if record_kind != (row.get("candidate_record_kind") or "").strip():
        return None, "record_kind_mismatch_with_intake"
    if trade_date != (row.get("detected_trade_date") or "").strip():
        return None, "trade_date_mismatch_with_intake"

    try:
        column_map = json.loads(row.get("proposed_column_map") or "{}")
    except Exception:
        return None, "invalid_intake_column_map"

    delimiter = str(entry.get("delimiter") or "").strip()
    if not delimiter:
        delimiter = str(entry.get("detected_delimiter") or ",").strip() or ","

    source_id = str(entry.get("source_id") or f"licensed-{digest[:12]}").strip()
    format_version = str(entry.get("format_version") or row.get("candidate_format_version") or "licensed-vendor-file").strip()

    contract_source = {
        "source_id": source_id,
        "source_family": source_family,
        "record_kind": record_kind,
        "path": row["path"],
        "authorized": True,
        "data_classification": "authorized_historical_market_data",
        "license_reference": license_reference,
        "trade_date": trade_date,
        "timezone": str(entry.get("timezone") or "America/New_York"),
        "delimiter": delimiter,
        "encoding": str(entry.get("encoding") or "utf-8"),
        "format_version": format_version,
        "column_map": column_map,
        "notes": (
            "Activated by licensed-data drop processor after exact SHA-256 binding "
            "to a local entitlement manifest."
        ),
    }
    return contract_source, ""


def activate(
    *,
    drop_dir: Path,
    work_dir: Path,
    entitlement_manifest: Path,
    market_contract_out: Path,
    replay_config_template: Path | None = None,
    replay_config_out: Path | None = None,
    run_replay: bool = False,
) -> dict[str, Any]:
    work_dir.mkdir(parents=True, exist_ok=True)
    intake_manifest = intake.scan(drop_dir, work_dir / "intake")
    inventory_path = work_dir / "intake" / "intake_files.csv"
    inventory = _load_inventory(inventory_path)

    ent = _read_json(entitlement_manifest)
    if str(ent.get("schema_version")) != "1":
        raise ValueError("entitlement manifest schema_version must equal '1'")
    entries = ent.get("files")
    if not isinstance(entries, list):
        raise ValueError("entitlement manifest must contain a files list")

    activated: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for raw in entries:
        if not isinstance(raw, dict):
            rejected.append({"sha256": "", "reason": "entry_not_object"})
            continue
        source, reason = _validate_entitlement_entry(raw, inventory)
        if source is None:
            rejected.append({"sha256": str(raw.get("sha256") or ""), "reason": reason})
        else:
            activated.append(source)

    contract = {
        "schema_version": "1",
        "purpose": (
            "Executable authorized historical market-data contract generated only "
            "from exact file hashes approved in a local entitlement manifest."
        ),
        "sources": activated,
    }
    _write_json(market_contract_out, contract)

    receipt = {
        "schema_version": SCHEMA_VERSION,
        "drop_dir": str(drop_dir),
        "drop_file_count": intake_manifest.get("file_count", 0),
        "entitlement_manifest": str(entitlement_manifest),
        "entitlement_manifest_sha256": _sha256(entitlement_manifest),
        "activated_source_count": len(activated),
        "rejected_entry_count": len(rejected),
        "rejected_entries": rejected,
        "market_contract": str(market_contract_out),
        "market_contract_sha256": _sha256(market_contract_out),
        "activation_policy": {
            "exact_sha256_binding_required": True,
            "authorized_true_required": True,
            "nonblank_license_reference_required": True,
            "intake_schema_must_match_entitlement": True,
            "raw_itch_not_auto_activated": True,
            "credentials_read_or_stored": False,
        },
    }

    replay_result: dict[str, Any] | None = None
    if replay_config_template is not None:
        cfg = _read_json(replay_config_template)
        cfg["market_contract"] = str(market_contract_out.resolve())
        if replay_config_out is None:
            replay_config_out = work_dir / "real_data_replay.generated.json"
        _write_json(replay_config_out, cfg)
        receipt["replay_config"] = str(replay_config_out)
        receipt["replay_config_sha256"] = _sha256(replay_config_out)

        if run_replay:
            if not activated:
                receipt["replay_status"] = "NOT_RUN_NO_ACTIVATED_SOURCES"
            else:
                replay_result = real_data_replay.run_replay(replay_config_out)
                receipt["replay_status"] = (
                    "READY"
                    if replay_result.get("ready_for_non_synthetic_offline_evaluation")
                    else "BLOCKED"
                )
                receipt["replay_status_path"] = str(
                    Path(cfg["output_dir"]).resolve() / "real_data_replay_status.json"
                )

    _write_json(work_dir / "licensed_drop_activation_receipt.json", receipt)
    return receipt


def watch(
    *,
    drop_dir: Path,
    work_dir: Path,
    entitlement_manifest: Path,
    market_contract_out: Path,
    replay_config_template: Path | None,
    replay_config_out: Path | None,
    interval_seconds: int,
    max_iterations: int,
    run_replay: bool,
) -> dict[str, Any]:
    if interval_seconds < 1:
        raise ValueError("interval_seconds must be >= 1")
    if max_iterations < 1:
        raise ValueError("max_iterations must be >= 1")

    last_fingerprint = ""
    last_receipt: dict[str, Any] = {}
    for _ in range(max_iterations):
        parts = []
        if drop_dir.exists():
            for p in sorted(x for x in drop_dir.rglob("*") if x.is_file()):
                parts.append(f"{p}:{p.stat().st_size}:{p.stat().st_mtime_ns}")
        if entitlement_manifest.exists():
            parts.append(f"ENT:{_sha256(entitlement_manifest)}")
        fingerprint = hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()

        if fingerprint != last_fingerprint:
            last_receipt = activate(
                drop_dir=drop_dir,
                work_dir=work_dir,
                entitlement_manifest=entitlement_manifest,
                market_contract_out=market_contract_out,
                replay_config_template=replay_config_template,
                replay_config_out=replay_config_out,
                run_replay=run_replay,
            )
            last_fingerprint = fingerprint
        time.sleep(interval_seconds)

    return last_receipt


def main() -> None:
    p = argparse.ArgumentParser(
        description="Bind licensed drop-folder files to explicit entitlement hashes and optionally trigger real-data replay."
    )
    sub = p.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--drop-dir", type=Path, required=True)
    common.add_argument("--work-dir", type=Path, required=True)
    common.add_argument("--entitlement-manifest", type=Path, required=True)
    common.add_argument("--market-contract-out", type=Path, required=True)
    common.add_argument("--replay-config-template", type=Path)
    common.add_argument("--replay-config-out", type=Path)
    common.add_argument("--run-replay", action="store_true")

    sub.add_parser("activate", parents=[common])
    w = sub.add_parser("watch", parents=[common])
    w.add_argument("--interval-seconds", type=int, default=60)
    w.add_argument("--max-iterations", type=int, default=60)

    args = p.parse_args()
    kwargs = dict(
        drop_dir=args.drop_dir,
        work_dir=args.work_dir,
        entitlement_manifest=args.entitlement_manifest,
        market_contract_out=args.market_contract_out,
        replay_config_template=args.replay_config_template,
        replay_config_out=args.replay_config_out,
        run_replay=args.run_replay,
    )

    if args.command == "activate":
        result = activate(**kwargs)
    else:
        result = watch(
            **kwargs,
            interval_seconds=args.interval_seconds,
            max_iterations=args.max_iterations,
        )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
