from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

import g5_control_identity_evidence_stager as g5_stager
import security_identity_stocknames_adapter as stocknames_adapter

SCHEMA_VERSION = "1"


class G5StocknamesActivationError(ValueError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = list(reader.fieldnames or [])
        rows = [
            {str(key): str(value or "").strip() for key, value in row.items()}
            for row in reader
        ]
    return fields, rows


def _symbol_date_scope(
    fields: list[str],
    rows: list[dict[str, str]],
    *,
    label: str,
) -> set[tuple[str, str]]:
    required = {"historical_symbol", "trade_date", "research_use_only"}
    missing = required.difference(fields)
    if missing:
        raise G5StocknamesActivationError(
            f"{label} missing columns: {sorted(missing)}"
        )
    if not rows:
        raise G5StocknamesActivationError(f"{label} is empty")

    out: set[tuple[str, str]] = set()
    for row_no, row in enumerate(rows, 2):
        symbol = row["historical_symbol"].upper()
        trade_date = row["trade_date"][:10]
        if not symbol or len(trade_date) != 10:
            raise G5StocknamesActivationError(
                f"{label} row {row_no}: historical_symbol/trade_date required"
            )
        if row["research_use_only"] != "1":
            raise G5StocknamesActivationError(
                f"{label} row {row_no}: research_use_only must equal 1"
            )
        key = (symbol, trade_date)
        if key in out:
            raise G5StocknamesActivationError(
                f"{label} contains duplicate symbol-date {symbol}|{trade_date}"
            )
        out.add(key)
    return out


def build(
    *,
    identity_queue_path: Path,
    expanded_stocknames_queue_path: Path,
    stocknames_path: Path,
    authorization_reference: str,
    output_dir: Path,
) -> dict:
    identity_fields, identity_rows = _read_csv(identity_queue_path)
    expanded_fields, expanded_rows = _read_csv(expanded_stocknames_queue_path)

    identity_scope = _symbol_date_scope(
        identity_fields,
        identity_rows,
        label="G5 identity queue",
    )
    expanded_scope = _symbol_date_scope(
        expanded_fields,
        expanded_rows,
        label="expanded Stocknames queue",
    )
    if identity_scope != expanded_scope:
        missing = sorted(identity_scope - expanded_scope)
        extra = sorted(expanded_scope - identity_scope)
        raise G5StocknamesActivationError(
            "expanded Stocknames queue does not exactly match the G5 identity queue; "
            f"missing={missing[:10]}; extra={extra[:10]}"
        )

    required_expanded = {"request_id", "permno"}
    missing_expanded = required_expanded.difference(expanded_fields)
    if missing_expanded:
        raise G5StocknamesActivationError(
            "expanded Stocknames queue missing adapter columns: "
            f"{sorted(missing_expanded)}"
        )

    stocknames_path = stocknames_path.expanduser().resolve()
    if not stocknames_path.is_file():
        raise FileNotFoundError(stocknames_path)
    stocknames_rows = stocknames_adapter.read_csv(stocknames_path)
    if not stocknames_rows:
        raise G5StocknamesActivationError("authorized Stocknames extract is empty")

    source_sha256 = _sha256(stocknames_path)
    evidence_rows, adapter_summary = stocknames_adapter.build_evidence(
        expanded_rows,
        stocknames_rows,
        source_sha256=source_sha256,
        authorization_reference=authorization_reference,
    )

    normalized_dir = output_dir / "normalized"
    staging_dir = output_dir / "staging"
    normalized_dir.mkdir(parents=True, exist_ok=True)

    evidence_path = normalized_dir / "g5_control_identity_stocknames_evidence.csv"
    adapter_summary_path = (
        normalized_dir / "g5_control_identity_stocknames_adapter_summary.json"
    )
    evidence_path.write_text(
        stocknames_adapter.render_evidence(evidence_rows),
        encoding="utf-8",
    )
    adapter_summary_path.write_text(
        stocknames_adapter.render_summary(adapter_summary),
        encoding="utf-8",
    )

    if not evidence_rows:
        raise G5StocknamesActivationError(
            "authorized Stocknames extract produced zero admissible evidence rows; "
            "nothing may be staged"
        )

    staging_receipt = g5_stager.build(
        identity_queue_path=identity_queue_path,
        evidence_path=evidence_path,
        output_dir=staging_dir,
    )

    adapter_unresolved = list(adapter_summary.get("unresolved") or [])
    staging_counts = staging_receipt["counts"]
    summary = {
        "schema_version": SCHEMA_VERSION,
        "purpose": (
            "Activate an explicitly authorized dated Stocknames/name-history extract "
            "for the complete routable G5 control-identity queue by reusing the canonical "
            "Stocknames adapter and G5 evidence stager. This wrapper performs no fetch, "
            "purchase, canonical write, coverage promotion, or release."
        ),
        "research_use_only": True,
        "inputs": {
            "identity_queue": {
                "path": str(identity_queue_path),
                "sha256": _sha256(identity_queue_path),
            },
            "expanded_stocknames_queue": {
                "path": str(expanded_stocknames_queue_path),
                "sha256": _sha256(expanded_stocknames_queue_path),
            },
            "authorized_stocknames_extract": {
                "path": str(stocknames_path),
                "sha256": source_sha256,
            },
            "authorization_reference_present": bool(
                str(authorization_reference or "").strip()
            ),
        },
        "counts": {
            "identity_queue_count": len(identity_rows),
            "expanded_stocknames_request_count": len(expanded_rows),
            "stocknames_source_row_count": len(stocknames_rows),
            "adapter_evidence_row_count": len(evidence_rows),
            "adapter_unresolved_request_count": len(adapter_unresolved),
            "g5_only_staged_verified_count": int(
                staging_counts["g5_only_staged_verified_count"]
            ),
            "g5_only_remaining_count": int(
                staging_counts["g5_only_remaining_count"]
            ),
            "canonical_g2_forward_evidence_row_count": int(
                staging_counts["g2_forward_evidence_row_count"]
            ),
        },
        "all_routable_dates_evidence_ready": bool(
            adapter_summary["all_queue_requests_evidence_ready"]
        ),
        "g5_only_identity_staging_complete": bool(
            staging_receipt["g5_only_identity_staging_complete"]
        ),
        "overall_g5_identity_ready_claimed": False,
        "data_fetch_performed": False,
        "purchase_performed": False,
        "canonical_g2_write_performed": False,
        "canonical_g5_write_performed": False,
        "coverage_promoted": False,
        "release_claimed": False,
        "g5_dates_resolved_change": 0,
        "policy": {
            "complete_identity_queue_scope_required": True,
            "exact_permno_required": True,
            "exact_historical_symbol_required": True,
            "requested_date_must_be_inside_name_interval": True,
            "authorized_source_reference_required": True,
            "adapter_evidence_is_staging_input_not_canonical_identity": True,
            "g2_overlap_requires_existing_canonical_g2_admission": True,
            "g5_only_rows_require_g5_staging_and_gate_revalidation": True,
        },
        "outputs": {
            "normalized_evidence": str(evidence_path),
            "adapter_summary": str(adapter_summary_path),
            "staging_dir": str(staging_dir),
        },
        "output_sha256": {
            "normalized_evidence": _sha256(evidence_path),
            "adapter_summary": _sha256(adapter_summary_path),
            "g5_only_staged_verified": staging_receipt["output_sha256"][
                "g5_only_staged_verified"
            ],
            "g5_only_remaining": staging_receipt["output_sha256"][
                "g5_only_remaining"
            ],
            "canonical_g2_forward_evidence": staging_receipt["output_sha256"][
                "canonical_g2_forward_evidence"
            ],
        },
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_path = output_dir / "g5_control_identity_stocknames_activation_summary.json"
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Normalize an authorized Stocknames extract for all routable G5 identity dates "
            "and stage the resulting evidence without canonical promotion."
        )
    )
    parser.add_argument("--identity-queue", type=Path, required=True)
    parser.add_argument("--expanded-stocknames-queue", type=Path, required=True)
    parser.add_argument("--stocknames", type=Path, required=True)
    parser.add_argument("--authorization-reference", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    result = build(
        identity_queue_path=args.identity_queue,
        expanded_stocknames_queue_path=args.expanded_stocknames_queue,
        stocknames_path=args.stocknames,
        authorization_reference=args.authorization_reference,
        output_dir=args.output_dir,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
