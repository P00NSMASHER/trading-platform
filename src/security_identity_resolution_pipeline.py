from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
from pathlib import Path

import security_identity_acquisition as acquisition
import security_identity_gate as identity_gate


DEFAULT_OUTPUT_DIR = Path("data/processed/security_identity_resolution_candidate")


class IdentityResolutionPipelineError(ValueError):
    pass


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_evidence(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = [
            {str(key): str(value or "").strip() for key, value in row.items()}
            for row in csv.DictReader(handle)
        ]
    if not rows:
        raise IdentityResolutionPipelineError(f"{path}: identity evidence is empty")
    return rows


def merge_evidence(paths: list[Path]) -> tuple[list[dict[str, str]], list[dict[str, object]]]:
    if not paths:
        raise IdentityResolutionPipelineError("at least one identity evidence file is required")

    by_id: dict[str, dict[str, str]] = {}
    receipts: list[dict[str, object]] = []
    for raw_path in paths:
        path = raw_path.expanduser().resolve()
        rows = _read_evidence(path)
        receipts.append({
            "name": path.name,
            "size_bytes": path.stat().st_size,
            "sha256": _sha256_path(path),
            "row_count": len(rows),
        })
        for row in rows:
            evidence_id = row.get("evidence_id", "")
            if not evidence_id:
                raise IdentityResolutionPipelineError(
                    f"{path}: evidence_id must be nonblank"
                )
            previous = by_id.get(evidence_id)
            if previous is not None and previous != row:
                raise IdentityResolutionPipelineError(
                    f"conflicting duplicate evidence_id {evidence_id}"
                )
            by_id[evidence_id] = row

    merged = sorted(
        by_id.values(),
        key=lambda row: (
            row.get("permno", ""),
            row.get("historical_symbol", ""),
            row.get("valid_from", ""),
            row.get("valid_through", ""),
            row.get("market_identifier", ""),
            row.get("evidence_id", ""),
        ),
    )
    return merged, receipts


def build_resolution(
    evidence_rows: list[dict[str, str]],
    *,
    evidence_receipts: list[dict[str, object]] | None = None,
    events_path: Path = identity_gate.DEFAULT_EVENTS,
    requirements_path: Path = identity_gate.DEFAULT_REQUIREMENTS,
    listing_path: Path = identity_gate.DEFAULT_LISTING,
) -> tuple[str, str, str, str]:
    events = identity_gate._read_csv(events_path)
    requirements = identity_gate._read_csv(requirements_path)
    listings = identity_gate._read_csv(listing_path)

    source_sha256 = {
        "historical_events": identity_gate._sha256(events_path),
        "symbol_date_requirements": identity_gate._sha256(requirements_path),
        "event_date_listing_evidence": identity_gate._sha256(listing_path),
    }
    for index, receipt in enumerate(evidence_receipts or []):
        source_sha256[f"identity_evidence_{index}"] = str(receipt["sha256"])

    before = identity_gate.build_manifest_from_rows(
        events,
        requirements,
        listings,
        source_sha256={
            "historical_events": source_sha256["historical_events"],
            "symbol_date_requirements": source_sha256["symbol_date_requirements"],
            "event_date_listing_evidence": source_sha256["event_date_listing_evidence"],
        },
    )
    resolved = identity_gate.build_manifest_from_rows(
        events,
        requirements,
        listings,
        source_sha256=source_sha256,
        identity_evidence=evidence_rows,
    )
    resolved["sources"]["identity_evidence_files"] = list(evidence_receipts or [])

    manifest_text = identity_gate.render_manifest(resolved)
    manifest_sha256 = _sha256_bytes(manifest_text.encode("utf-8"))
    queue, summary = acquisition.build_acquisition(
        resolved,
        identity_sha256=manifest_sha256,
    )
    queue_text = acquisition.render_queue(queue)
    summary_text = acquisition.render_summary(summary)

    before_state = before["state"]
    after_state = resolved["state"]
    baseline_verified = int(after_state.get("baseline_identity_verified_count", 0) or 0)
    receipt = {
        "schema_version": "1",
        "purpose": (
            "Deterministic stable-security-identity resolution candidate. "
            "Evidence is applied through the fail-closed identity gate and the "
            "remaining acquisition queue is regenerated from the resulting manifest."
        ),
        "research_use_only": True,
        "inputs": {
            "evidence_files": list(evidence_receipts or []),
            "evidence_rows_merged": len(evidence_rows),
        },
        "before": {
            "event_date_verified": int(before_state["event_date_identity_verified_count"]),
            "baseline_verified": int(before_state.get("baseline_identity_verified_count", 0) or 0),
            "baseline_unverified": int(before_state["baseline_identity_unverified_count"]),
            "total_required": int(before_state["required_symbol_date_count"]),
        },
        "after": {
            "event_date_verified": int(after_state["event_date_identity_verified_count"]),
            "baseline_verified": baseline_verified,
            "baseline_unverified": int(after_state["baseline_identity_unverified_count"]),
            "total_verified": int(
                after_state.get(
                    "total_identity_verified_count",
                    int(after_state["event_date_identity_verified_count"]) + baseline_verified,
                )
            ),
            "total_required": int(after_state["required_symbol_date_count"]),
            "ready_for_non_synthetic_market_join": bool(
                after_state["ready_for_non_synthetic_market_join"]
            ),
            "remaining_acquisition_requests": len(queue),
        },
        "outputs": {
            "security_identity_manifest_sha256": manifest_sha256,
            "security_identity_acquisition_queue_sha256": _sha256_bytes(
                queue_text.encode("utf-8")
            ),
            "security_identity_acquisition_summary_sha256": _sha256_bytes(
                summary_text.encode("utf-8")
            ),
        },
        "gate_policy": {
            "partial_progress_allowed": True,
            "zero_unresolved_required_for_ready": True,
            "ticker_or_alias_inference_allowed": False,
            "authorization_reference_required_by_identity_gate": True,
        },
    }
    receipt_text = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    return manifest_text, queue_text, summary_text, receipt_text


def write_resolution(
    output_dir: Path,
    *,
    manifest_text: str,
    queue_text: str,
    summary_text: str,
    receipt_text: str,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "security_identity_manifest.json").write_text(
        manifest_text, encoding="utf-8"
    )
    (output_dir / "security_identity_acquisition_queue.csv").write_text(
        queue_text, encoding="utf-8"
    )
    (output_dir / "security_identity_acquisition_summary.json").write_text(
        summary_text, encoding="utf-8"
    )
    (output_dir / "security_identity_resolution_receipt.json").write_text(
        receipt_text, encoding="utf-8"
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Apply one or more authorized stable-ID evidence files through the canonical "
            "fail-closed identity gate and regenerate the remaining acquisition queue."
        )
    )
    parser.add_argument(
        "--evidence",
        type=Path,
        action="append",
        required=True,
        help="Canonical identity evidence CSV; repeat for multiple authorized sources.",
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()

    evidence_rows, evidence_receipts = merge_evidence(args.evidence)
    manifest_text, queue_text, summary_text, receipt_text = build_resolution(
        evidence_rows,
        evidence_receipts=evidence_receipts,
    )
    write_resolution(
        args.output_dir,
        manifest_text=manifest_text,
        queue_text=queue_text,
        summary_text=summary_text,
        receipt_text=receipt_text,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
