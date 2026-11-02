from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
from pathlib import Path

import security_identity_acquisition as acquisition
import security_identity_gate as gate


SCHEMA_VERSION = "1"
DEFAULT_OUTDIR = Path("private_runtime/security_identity_staging")

MANIFEST_NAME = "security_identity_manifest.candidate.json"
QUEUE_NAME = "security_identity_acquisition_queue.remaining.csv"
SUMMARY_NAME = "security_identity_acquisition_summary.remaining.json"
RECEIPT_NAME = "security_identity_evidence_staging_receipt.json"


class SecurityIdentityStagingError(ValueError):
    pass


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [
            {str(key): str(value or "").strip() for key, value in row.items()}
            for row in csv.DictReader(handle)
        ]


def load_evidence_files(paths: list[Path]) -> tuple[list[dict[str, str]], list[dict[str, object]]]:
    if not paths:
        raise SecurityIdentityStagingError(
            "at least one --identity-evidence file is required"
        )

    rows: list[dict[str, str]] = []
    inputs: list[dict[str, object]] = []
    for raw_path in paths:
        path = raw_path.expanduser().resolve()
        if not path.is_file():
            raise SecurityIdentityStagingError(
                f"identity evidence file does not exist: {path}"
            )
        file_rows = _read_csv(path)
        rows.extend(file_rows)
        inputs.append(
            {
                "path": str(path),
                "sha256": _sha256_path(path),
                "row_count": len(file_rows),
            }
        )
    return rows, inputs


def evidence_rows_from_manifest(manifest: dict) -> list[dict[str, str]]:
    by_id: dict[str, dict[str, str]] = {}
    for event in manifest.get("events") or []:
        permno = str(event.get("permno") or "")
        symbol = str(event.get("historical_symbol") or "").upper()
        dated = event.get("baseline_identity_evidence") or {}
        if not isinstance(dated, dict):
            raise SecurityIdentityStagingError(
                f"event {event.get('event_id')}: baseline_identity_evidence must be an object"
            )
        for trade_date, entries in dated.items():
            if not isinstance(entries, list):
                raise SecurityIdentityStagingError(
                    f"event {event.get('event_id')}/{trade_date}: evidence must be a list"
                )
            for raw in entries:
                row = {
                    "evidence_id": str(raw.get("evidence_id") or "").strip(),
                    "permno": permno,
                    "historical_symbol": symbol,
                    "market_identifier": str(raw.get("market_identifier") or "").strip(),
                    "valid_from": str(raw.get("valid_from") or "").strip(),
                    "valid_through": str(raw.get("valid_through") or "").strip(),
                    "evidence_lane": str(raw.get("evidence_lane") or "").strip(),
                    "source_reference": str(raw.get("source_reference") or "").strip(),
                    "authorization_reference": str(
                        raw.get("authorization_reference") or ""
                    ).strip(),
                    "research_use_only": "1",
                }
                evidence_id = row["evidence_id"]
                if not evidence_id:
                    raise SecurityIdentityStagingError(
                        f"event {event.get('event_id')}/{trade_date}: evidence_id is blank"
                    )
                previous = by_id.get(evidence_id)
                if previous is not None and previous != row:
                    raise SecurityIdentityStagingError(
                        f"evidence_id {evidence_id} is reused with conflicting fields"
                    )
                by_id[evidence_id] = row

    baseline_verified = int(
        (manifest.get("state") or {}).get("baseline_identity_verified_count", 0) or 0
    )
    if baseline_verified > 0 and not by_id:
        raise SecurityIdentityStagingError(
            "canonical manifest reports verified baseline identity without embedded evidence"
        )
    return [by_id[key] for key in sorted(by_id)]


def merge_evidence_rows(*groups: list[dict[str, str]]) -> list[dict[str, str]]:
    by_id: dict[str, dict[str, str]] = {}
    for rows in groups:
        for raw in rows:
            row = {
                str(key): str(value or "").strip()
                for key, value in raw.items()
            }
            evidence_id = row.get("evidence_id", "")
            if not evidence_id:
                raise SecurityIdentityStagingError("identity evidence_id must be nonblank")
            previous = by_id.get(evidence_id)
            if previous is not None and previous != row:
                raise SecurityIdentityStagingError(
                    f"evidence_id {evidence_id} conflicts with previously staged evidence"
                )
            by_id[evidence_id] = row
    return [by_id[key] for key in sorted(by_id)]


def build_staging_from_rows(
    *,
    events: list[dict[str, str]],
    requirements: list[dict[str, str]],
    listings: list[dict[str, str]],
    evidence_rows: list[dict[str, str]],
    evidence_inputs: list[dict[str, object]] | None = None,
    source_sha256: dict[str, str] | None = None,
    prior_canonical_evidence_row_count: int = 0,
    new_evidence_row_count: int | None = None,
) -> dict[str, object]:
    candidate_manifest = gate.build_manifest_from_rows(
        events,
        requirements,
        listings,
        source_sha256=source_sha256,
        identity_evidence=evidence_rows,
    )
    manifest_text = gate.render_manifest(candidate_manifest)
    manifest_sha256 = _sha256_bytes(manifest_text.encode("utf-8"))

    remaining_queue, remaining_summary = acquisition.build_acquisition(
        candidate_manifest,
        identity_sha256=manifest_sha256,
    )
    queue_text = acquisition.render_queue(remaining_queue)
    summary_text = acquisition.render_summary(remaining_summary)

    state = candidate_manifest["state"]
    required = int(state["required_symbol_date_count"])
    event_verified = int(state["event_date_identity_verified_count"])
    baseline_verified = int(state.get("baseline_identity_verified_count", 0))
    unresolved = int(state["baseline_identity_unverified_count"])
    total_verified = event_verified + baseline_verified
    ready = bool(state["ready_for_non_synthetic_market_join"])

    if event_verified != int(state["event_count"]):
        raise SecurityIdentityStagingError(
            "candidate event-date identity count disagrees with event_count"
        )
    if total_verified + unresolved != required:
        raise SecurityIdentityStagingError(
            "candidate identity counts do not reconcile to required symbol-dates"
        )
    if ready != (unresolved == 0):
        raise SecurityIdentityStagingError(
            "candidate readiness disagrees with unresolved identity count"
        )
    if len(remaining_queue) != unresolved:
        raise SecurityIdentityStagingError(
            "remaining acquisition queue does not reconcile to unresolved identity count"
        )

    receipt = {
        "schema_version": SCHEMA_VERSION,
        "purpose": (
            "Deterministic staging receipt for authorized dated stable-ID evidence. "
            "This receipt never promotes canonical identity state by itself."
        ),
        "research_use_only": True,
        "canonical_write_performed": False,
        "coverage_promoted": False,
        "evidence_inputs": list(evidence_inputs or []),
        "evidence_row_count": len(evidence_rows),
        "prior_canonical_evidence_row_count": prior_canonical_evidence_row_count,
        "new_evidence_row_count": (
            len(evidence_rows) - prior_canonical_evidence_row_count
            if new_evidence_row_count is None
            else new_evidence_row_count
        ),
        "candidate_manifest_sha256": manifest_sha256,
        "candidate_state": {
            "event_date_identity_verified_count": event_verified,
            "baseline_identity_verified_count": baseline_verified,
            "total_identity_verified_count": total_verified,
            "baseline_identity_unverified_count": unresolved,
            "required_symbol_date_count": required,
            "ready_for_non_synthetic_market_join": ready,
        },
        "remaining_acquisition_queue_count": len(remaining_queue),
        "completion_rule": (
            "Canonical G2_STABLE_SECURITY_IDENTITY may become READY only after this "
            "same evidence is explicitly reviewed/published into the canonical identity "
            "manifest and baseline_identity_unverified_count is zero."
        ),
    }

    return {
        "manifest": candidate_manifest,
        "manifest_text": manifest_text,
        "queue": remaining_queue,
        "queue_text": queue_text,
        "summary": remaining_summary,
        "summary_text": summary_text,
        "receipt": receipt,
        "receipt_text": json.dumps(receipt, indent=2, sort_keys=True) + "\n",
    }


def build_staging(
    *,
    evidence_paths: list[Path],
    events_path: Path = gate.DEFAULT_EVENTS,
    requirements_path: Path = gate.DEFAULT_REQUIREMENTS,
    listing_path: Path = gate.DEFAULT_LISTING,
    current_manifest_path: Path = gate.DEFAULT_OUTPUT,
) -> dict[str, object]:
    new_evidence_rows, new_evidence_inputs = load_evidence_files(evidence_paths)
    events = _read_csv(events_path)
    requirements = _read_csv(requirements_path)
    listings = _read_csv(listing_path)

    current_manifest_path = current_manifest_path.expanduser().resolve()
    if not current_manifest_path.is_file():
        raise SecurityIdentityStagingError(
            f"current canonical identity manifest does not exist: {current_manifest_path}"
        )
    current_text = current_manifest_path.read_text(encoding="utf-8")
    current_manifest = json.loads(current_text)
    prior_evidence_rows = evidence_rows_from_manifest(current_manifest)

    if prior_evidence_rows:
        current_source_hashes = (
            (current_manifest.get("sources") or {}).get("sha256") or {}
        )
        rebuilt_current = gate.build_manifest_from_rows(
            events,
            requirements,
            listings,
            source_sha256=current_source_hashes,
            identity_evidence=prior_evidence_rows,
        )
        if gate.render_manifest(rebuilt_current) != current_text:
            raise SecurityIdentityStagingError(
                "current canonical identity manifest does not reproduce from embedded evidence"
            )

    evidence_rows = merge_evidence_rows(prior_evidence_rows, new_evidence_rows)
    current_sha256 = _sha256_path(current_manifest_path)
    evidence_inputs = [
        {
            "path": str(current_manifest_path),
            "sha256": current_sha256,
            "row_count": len(prior_evidence_rows),
            "role": "prior_canonical_identity_manifest",
        },
        *new_evidence_inputs,
    ]
    source_sha256 = {
        "historical_events": _sha256_path(events_path),
        "symbol_date_requirements": _sha256_path(requirements_path),
        "event_date_listing_evidence": _sha256_path(listing_path),
        "prior_canonical_identity_manifest": current_sha256,
    }
    for index, item in enumerate(new_evidence_inputs, 1):
        source_sha256[f"identity_evidence_{index:02d}"] = str(item["sha256"])

    return build_staging_from_rows(
        events=events,
        requirements=requirements,
        listings=listings,
        evidence_rows=evidence_rows,
        evidence_inputs=evidence_inputs,
        source_sha256=source_sha256,
        prior_canonical_evidence_row_count=len(prior_evidence_rows),
        new_evidence_row_count=len(new_evidence_rows),
    )


def write_staging(result: dict[str, object], outdir: Path) -> dict[str, str]:
    outdir = outdir.expanduser().resolve()
    canonical_dir = gate.DEFAULT_OUTPUT.parent.resolve()
    if outdir == canonical_dir:
        raise SecurityIdentityStagingError(
            "staging output directory may not equal the canonical security-identity directory"
        )
    outdir.mkdir(parents=True, exist_ok=True)

    outputs = {
        "candidate_manifest": outdir / MANIFEST_NAME,
        "remaining_queue": outdir / QUEUE_NAME,
        "remaining_summary": outdir / SUMMARY_NAME,
        "receipt": outdir / RECEIPT_NAME,
    }
    outputs["candidate_manifest"].write_text(
        str(result["manifest_text"]), encoding="utf-8"
    )
    outputs["remaining_queue"].write_text(
        str(result["queue_text"]), encoding="utf-8"
    )
    outputs["remaining_summary"].write_text(
        str(result["summary_text"]), encoding="utf-8"
    )
    outputs["receipt"].write_text(
        str(result["receipt_text"]), encoding="utf-8"
    )
    return {name: str(path) for name, path in outputs.items()}


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Stage one or more authorized dated stable-ID evidence files against the "
            "canonical 3,828 symbol-date identity gate without modifying canonical outputs."
        )
    )
    parser.add_argument(
        "--identity-evidence",
        type=Path,
        action="append",
        required=True,
        help="Repeat for each generic stable-ID evidence CSV to combine.",
    )
    parser.add_argument("--events", type=Path, default=gate.DEFAULT_EVENTS)
    parser.add_argument("--requirements", type=Path, default=gate.DEFAULT_REQUIREMENTS)
    parser.add_argument("--listing", type=Path, default=gate.DEFAULT_LISTING)
    parser.add_argument(
        "--current-manifest",
        type=Path,
        default=gate.DEFAULT_OUTPUT,
        help=(
            "Current canonical identity manifest. Any previously promoted embedded "
            "evidence is carried forward automatically."
        ),
    )
    parser.add_argument("--outdir", type=Path, default=DEFAULT_OUTDIR)
    args = parser.parse_args()

    result = build_staging(
        evidence_paths=args.identity_evidence,
        events_path=args.events,
        requirements_path=args.requirements,
        listing_path=args.listing,
        current_manifest_path=args.current_manifest,
    )
    outputs = write_staging(result, args.outdir)
    print(
        json.dumps(
            {
                "outputs": outputs,
                "candidate_state": result["receipt"]["candidate_state"],
                "canonical_write_performed": False,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
