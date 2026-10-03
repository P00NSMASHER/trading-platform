from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
from typing import Iterable

import historical_market_backfill as hmb


LANE_FILES = {
    "equity": {
        "equity_trade": "equity_trades.csv",
        "equity_quote": "equity_quotes.csv",
    },
    "options": {
        "option_trade": "option_trades.csv",
        "option_quote": "option_quotes.csv",
    },
}

COLUMN_MAPS = {
    "equity_trade": {
        "timestamp": "timestamp",
        "symbol": "symbol",
        "price": "price",
        "size": "size",
        "exchange": "exchange",
        "conditions": "conditions",
    },
    "equity_quote": {
        "timestamp": "timestamp",
        "symbol": "symbol",
        "bid": "bid",
        "ask": "ask",
        "bid_size": "bid_size",
        "ask_size": "ask_size",
        "exchange": "exchange",
        "conditions": "conditions",
    },
    "option_trade": {
        "timestamp": "timestamp",
        "symbol": "symbol",
        "underlying_symbol": "underlying_symbol",
        "option_symbol": "option_symbol",
        "expiration": "expiration",
        "strike": "strike",
        "option_type": "option_type",
        "price": "price",
        "size": "size",
        "exchange": "exchange",
        "conditions": "conditions",
    },
    "option_quote": {
        "timestamp": "timestamp",
        "symbol": "symbol",
        "underlying_symbol": "underlying_symbol",
        "option_symbol": "option_symbol",
        "expiration": "expiration",
        "strike": "strike",
        "option_type": "option_type",
        "bid": "bid",
        "ask": "ask",
        "bid_size": "bid_size",
        "ask_size": "ask_size",
        "exchange": "exchange",
        "conditions": "conditions",
    },
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _relative_or_absolute(path: Path, *, contract_parent: Path) -> str:
    resolved = path.expanduser().resolve()
    try:
        return os.path.relpath(resolved, contract_parent.resolve())
    except ValueError:
        return str(resolved)


def _data_row_count(path: Path) -> int:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError(f"{path}: missing CSV header")
        return sum(1 for _ in reader)


def discover_receipts(root: Path) -> list[Path]:
    resolved = root.expanduser().resolve()
    if not resolved.exists():
        raise FileNotFoundError(f"adapted root does not exist: {resolved}")
    receipts = sorted(resolved.rglob("lseg_adaptation_receipt.json"))
    if not receipts:
        raise ValueError(
            f"{resolved}: no lseg_adaptation_receipt.json files were found"
        )
    return receipts


def _load_receipt(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "1":
        raise ValueError(f"{path}: unsupported receipt schema")
    lane = str(payload.get("lane") or "")
    if lane not in LANE_FILES:
        raise ValueError(f"{path}: unsupported LSEG lane {lane!r}")
    trade_date = str(payload.get("trade_date") or "")
    try:
        __import__("datetime").date.fromisoformat(trade_date)
    except ValueError as exc:
        raise ValueError(f"{path}: invalid trade_date {trade_date!r}") from exc

    summary = dict(payload.get("summary") or {})
    if summary.get("g2_coverage_change") not in {False, 0}:
        raise ValueError(
            f"{path}: adaptation receipt must remain non-authoritative for G2 coverage"
        )
    return payload


def sources_from_receipt(
    receipt_path: Path,
    *,
    contract_parent: Path,
    license_reference: str,
) -> tuple[list[dict], dict]:
    if not license_reference.strip():
        raise ValueError("license_reference must be non-blank")

    payload = _load_receipt(receipt_path)
    lane = str(payload["lane"])
    trade_date = str(payload["trade_date"])

    sources: list[dict] = []
    omitted: list[dict] = []
    receipt_hash = sha256_file(receipt_path)

    for record_kind, filename in LANE_FILES[lane].items():
        data_path = receipt_path.parent / filename
        if not data_path.exists():
            omitted.append(
                {
                    "record_kind": record_kind,
                    "reason": "expected_adapted_file_missing",
                    "path_name": filename,
                }
            )
            continue
        rows = _data_row_count(data_path)
        if rows == 0:
            omitted.append(
                {
                    "record_kind": record_kind,
                    "reason": "adapted_file_has_no_data_rows",
                    "path_name": filename,
                }
            )
            continue

        source_id = f"lseg_{trade_date.replace('-', '')}_{record_kind}"
        sources.append(
            {
                "source_id": source_id,
                "source_family": "generic_authorized_market_data",
                "record_kind": record_kind,
                "path": _relative_or_absolute(
                    data_path,
                    contract_parent=contract_parent,
                ),
                "authorized": True,
                "data_classification": hmb.NON_SYNTHETIC_CLASS,
                "license_reference": license_reference.strip(),
                "trade_date": trade_date,
                "timezone": "America/New_York",
                "delimiter": ",",
                "encoding": "utf-8",
                "format_version": "lseg-tick-history-validated-v1",
                "column_map": COLUMN_MAPS[record_kind],
                "notes": (
                    "Generated from a post-validation LSEG adaptation receipt; "
                    f"receipt_sha256={receipt_hash}"
                ),
            }
        )

    return sources, {
        "receipt_path": str(receipt_path),
        "receipt_sha256": receipt_hash,
        "lane": lane,
        "trade_date": trade_date,
        "emitted_source_count": len(sources),
        "omitted": omitted,
    }


def build_contract(
    *,
    adapted_root: Path,
    output_path: Path,
    license_reference: str,
    security_identity_manifest: Path | None = None,
) -> dict:
    if not license_reference.strip():
        raise ValueError("license_reference must be non-blank")

    output_path = output_path.expanduser().resolve()
    contract_parent = output_path.parent
    receipts = discover_receipts(adapted_root)

    all_sources: list[dict] = []
    receipt_reports: list[dict] = []
    seen_source_ids: set[str] = set()

    for receipt in receipts:
        sources, report = sources_from_receipt(
            receipt,
            contract_parent=contract_parent,
            license_reference=license_reference,
        )
        for source in sources:
            source_id = str(source["source_id"])
            if source_id in seen_source_ids:
                raise ValueError(
                    f"duplicate generated source_id {source_id!r}; "
                    "there must be at most one adapted file per date/record kind"
                )
            seen_source_ids.add(source_id)
            all_sources.append(source)
        receipt_reports.append(report)

    if not all_sources:
        raise ValueError("adapted receipts produced no non-empty canonical source files")

    all_sources.sort(key=lambda row: (row["trade_date"], row["record_kind"]))

    contract: dict = {
        "schema_version": "1",
        "purpose": (
            "Generated source contract for validated, authorized LSEG Tick History "
            "canonical files. Coverage remains determined by production content "
            "validation; this contract does not self-assert G2 readiness."
        ),
        "sources": all_sources,
        "lseg_generation_receipts": receipt_reports,
    }

    if security_identity_manifest is not None:
        identity = security_identity_manifest.expanduser().resolve()
        if not identity.exists():
            raise FileNotFoundError(
                f"security identity manifest does not exist: {identity}"
            )
        contract["security_identity_manifest"] = _relative_or_absolute(
            identity,
            contract_parent=contract_parent,
        )

    return contract


def write_contract(
    *,
    adapted_root: Path,
    output_path: Path,
    license_reference: str,
    security_identity_manifest: Path | None = None,
) -> dict:
    contract = build_contract(
        adapted_root=adapted_root,
        output_path=output_path,
        license_reference=license_reference,
        security_identity_manifest=security_identity_manifest,
    )
    output_path = output_path.expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(contract, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    # Validate the exact on-disk contract with the same loader used by replay.
    sources, _ = hmb.load_contract(output_path)
    if len(sources) != len(contract["sources"]):
        raise RuntimeError("generated contract source count changed during validation")
    return contract


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Generate a fail-closed historical market source contract from "
            "post-validation LSEG adaptation outputs."
        )
    )
    parser.add_argument("--adapted-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--license-reference", required=True)
    parser.add_argument("--security-identity-manifest", type=Path)
    args = parser.parse_args()

    contract = write_contract(
        adapted_root=args.adapted_root,
        output_path=args.output,
        license_reference=args.license_reference,
        security_identity_manifest=args.security_identity_manifest,
    )
    print(
        json.dumps(
            {
                "source_count": len(contract["sources"]),
                "receipt_count": len(contract["lseg_generation_receipts"]),
                "output": str(args.output.expanduser().resolve()),
                "coverage_claim": False,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
