from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from pathlib import Path

import security_identity_acquisition as acquisition
import security_identity_evidence_stager as stager
import security_identity_gate as gate


SCHEMA_VERSION = "1"
DEFAULT_CANONICAL_MANIFEST = gate.DEFAULT_OUTPUT
DEFAULT_CANONICAL_QUEUE = acquisition.DEFAULT_QUEUE
DEFAULT_CANONICAL_SUMMARY = acquisition.DEFAULT_SUMMARY
DEFAULT_PUBLICATION_RECEIPT = Path(
    "data/processed/security_identity_real/security_identity_publication_receipt.json"
)


class SecurityIdentityPublishError(ValueError):
    pass


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_csv_text(text: str) -> list[dict[str, str]]:
    reader = csv.DictReader(text.splitlines())
    return [
        {str(key): str(value or "").strip() for key, value in row.items()}
        for row in reader
    ]


def _core_identity_fields(event: dict) -> tuple:
    return (
        str(event.get("event_id") or ""),
        str(event.get("permno") or ""),
        str(event.get("gvkey") or ""),
        str(event.get("historical_symbol") or ""),
        str(event.get("event_date") or ""),
        str(event.get("primary_exchange") or ""),
        tuple(event.get("required_dates") or []),
    )


def evidence_rows_from_manifest(manifest: dict) -> list[dict[str, str]]:
    by_id: dict[str, dict[str, str]] = {}
    for event in manifest.get("events") or []:
        permno = str(event.get("permno") or "")
        symbol = str(event.get("historical_symbol") or "").upper()
        dated = event.get("baseline_identity_evidence") or {}
        if not isinstance(dated, dict):
            raise SecurityIdentityPublishError(
                f"event {event.get('event_id')}: baseline_identity_evidence must be an object"
            )
        for trade_date, entries in dated.items():
            if not isinstance(entries, list):
                raise SecurityIdentityPublishError(
                    f"event {event.get('event_id')}/{trade_date}: evidence must be a list"
                )
            for raw in entries:
                row = {
                    "evidence_id": str(raw.get("evidence_id") or ""),
                    "permno": permno,
                    "historical_symbol": symbol,
                    "market_identifier": str(raw.get("market_identifier") or ""),
                    "valid_from": str(raw.get("valid_from") or ""),
                    "valid_through": str(raw.get("valid_through") or ""),
                    "evidence_lane": str(raw.get("evidence_lane") or ""),
                    "source_reference": str(raw.get("source_reference") or ""),
                    "authorization_reference": str(raw.get("authorization_reference") or ""),
                    "research_use_only": "1",
                }
                evidence_id = row["evidence_id"]
                if not evidence_id:
                    raise SecurityIdentityPublishError(
                        f"event {event.get('event_id')}/{trade_date}: evidence_id is blank"
                    )
                previous = by_id.get(evidence_id)
                if previous is not None and previous != row:
                    raise SecurityIdentityPublishError(
                        f"evidence_id {evidence_id} is reused with conflicting fields"
                    )
                by_id[evidence_id] = row
    return [by_id[key] for key in sorted(by_id)]


def _validate_monotonic_progress(current: dict, candidate: dict) -> dict:
    current_events = {
        str(event.get("event_id") or ""): event
        for event in current.get("events") or []
    }
    candidate_events = {
        str(event.get("event_id") or ""): event
        for event in candidate.get("events") or []
    }
    if set(current_events) != set(candidate_events):
        raise SecurityIdentityPublishError("candidate event universe differs from canonical")

    newly_verified = 0
    for event_id in sorted(current_events):
        old = current_events[event_id]
        new = candidate_events[event_id]
        if _core_identity_fields(old) != _core_identity_fields(new):
            raise SecurityIdentityPublishError(
                f"candidate changes canonical core identity fields for {event_id}"
            )

        old_verified = set(old.get("verified_required_dates") or [])
        new_verified = set(new.get("verified_required_dates") or [])
        old_unverified = set(old.get("unverified_required_dates") or [])
        new_unverified = set(new.get("unverified_required_dates") or [])
        if not old_verified.issubset(new_verified):
            raise SecurityIdentityPublishError(
                f"candidate regresses verified identity dates for {event_id}"
            )
        if not new_unverified.issubset(old_unverified):
            raise SecurityIdentityPublishError(
                f"candidate introduces new unresolved identity dates for {event_id}"
            )
        if new_verified | new_unverified != set(new.get("required_dates") or []):
            raise SecurityIdentityPublishError(
                f"candidate identity date partition is incomplete for {event_id}"
            )
        newly_verified += len(new_verified - old_verified)

    old_state = current.get("state") or {}
    new_state = candidate.get("state") or {}
    old_unresolved = int(old_state.get("baseline_identity_unverified_count", -1))
    new_unresolved = int(new_state.get("baseline_identity_unverified_count", -1))
    if min(old_unresolved, new_unresolved) < 0:
        raise SecurityIdentityPublishError("identity unresolved counts are invalid")
    if new_unresolved > old_unresolved:
        raise SecurityIdentityPublishError("candidate increases unresolved identity count")
    if old_unresolved - new_unresolved != newly_verified:
        raise SecurityIdentityPublishError(
            "candidate baseline progress does not match event-level date changes"
        )

    return {
        "previous_unresolved": old_unresolved,
        "candidate_unresolved": new_unresolved,
        "newly_verified_baseline_dates": newly_verified,
    }


def verify_staged_bundle(
    *,
    staged_dir: Path,
    current_manifest_path: Path = DEFAULT_CANONICAL_MANIFEST,
    events_path: Path = gate.DEFAULT_EVENTS,
    requirements_path: Path = gate.DEFAULT_REQUIREMENTS,
    listing_path: Path = gate.DEFAULT_LISTING,
) -> dict:
    staged_dir = staged_dir.expanduser().resolve()
    candidate_path = staged_dir / stager.MANIFEST_NAME
    queue_path = staged_dir / stager.QUEUE_NAME
    summary_path = staged_dir / stager.SUMMARY_NAME
    receipt_path = staged_dir / stager.RECEIPT_NAME
    for path in (candidate_path, queue_path, summary_path, receipt_path):
        if not path.is_file():
            raise SecurityIdentityPublishError(f"staged artifact is missing: {path.name}")

    candidate_text = candidate_path.read_text(encoding="utf-8")
    queue_text = queue_path.read_text(encoding="utf-8")
    summary_text = summary_path.read_text(encoding="utf-8")
    candidate = json.loads(candidate_text)
    summary = json.loads(summary_text)
    receipt = _read_json(receipt_path)
    current = _read_json(current_manifest_path)

    candidate_sha = _sha256_bytes(candidate_text.encode("utf-8"))
    if receipt.get("candidate_manifest_sha256") != candidate_sha:
        raise SecurityIdentityPublishError(
            "staging receipt candidate_manifest_sha256 does not match candidate manifest"
        )
    if receipt.get("canonical_write_performed") is not False:
        raise SecurityIdentityPublishError(
            "staging receipt must state canonical_write_performed=false"
        )
    if receipt.get("coverage_promoted") is not False:
        raise SecurityIdentityPublishError(
            "staging receipt must state coverage_promoted=false"
        )

    source_hashes = ((candidate.get("sources") or {}).get("sha256") or {})
    expected_core_hashes = {
        "historical_events": _sha256_path(events_path),
        "symbol_date_requirements": _sha256_path(requirements_path),
        "event_date_listing_evidence": _sha256_path(listing_path),
    }
    for key, expected in expected_core_hashes.items():
        if source_hashes.get(key) != expected:
            raise SecurityIdentityPublishError(
                f"candidate core source hash mismatch for {key}"
            )

    prior_canonical_sha = source_hashes.get("prior_canonical_identity_manifest")
    if prior_canonical_sha is not None:
        current_sha = _sha256_path(current_manifest_path)
        if prior_canonical_sha != current_sha:
            raise SecurityIdentityPublishError(
                "staged bundle was built from a stale canonical identity manifest"
            )

    evidence_rows = evidence_rows_from_manifest(candidate)
    rebuilt = gate.build_manifest_from_rows(
        gate._read_csv(events_path),
        gate._read_csv(requirements_path),
        gate._read_csv(listing_path),
        source_sha256=source_hashes,
        identity_evidence=evidence_rows,
    )
    rebuilt_text = gate.render_manifest(rebuilt)
    if rebuilt_text != candidate_text:
        raise SecurityIdentityPublishError(
            "candidate manifest does not reproduce exactly from embedded dated evidence"
        )

    rebuilt_queue, rebuilt_summary = acquisition.build_acquisition(
        candidate,
        identity_sha256=candidate_sha,
    )
    if acquisition.render_queue(rebuilt_queue) != queue_text:
        raise SecurityIdentityPublishError(
            "staged remaining queue does not reproduce from candidate manifest"
        )
    if acquisition.render_summary(rebuilt_summary) != summary_text:
        raise SecurityIdentityPublishError(
            "staged remaining summary does not reproduce from candidate manifest"
        )

    state = candidate.get("state") or {}
    required = int(state.get("required_symbol_date_count", -1))
    event_verified = int(state.get("event_date_identity_verified_count", -1))
    baseline_verified = int(state.get("baseline_identity_verified_count", 0) or 0)
    unresolved = int(state.get("baseline_identity_unverified_count", -1))
    if min(required, event_verified, baseline_verified, unresolved) < 0:
        raise SecurityIdentityPublishError("candidate identity counts are invalid")
    if event_verified + baseline_verified + unresolved != required:
        raise SecurityIdentityPublishError("candidate identity counts do not reconcile")
    if bool(state.get("ready_for_non_synthetic_market_join")) != (unresolved == 0):
        raise SecurityIdentityPublishError(
            "candidate readiness disagrees with unresolved identity count"
        )
    if len(rebuilt_queue) != unresolved:
        raise SecurityIdentityPublishError(
            "candidate remaining queue count disagrees with unresolved identity count"
        )

    receipt_state = receipt.get("candidate_state") or {}
    for key in (
        "event_date_identity_verified_count",
        "baseline_identity_verified_count",
        "total_identity_verified_count",
        "baseline_identity_unverified_count",
        "required_symbol_date_count",
        "ready_for_non_synthetic_market_join",
    ):
        candidate_value = (
            event_verified + baseline_verified
            if key == "total_identity_verified_count"
            else state.get(key)
        )
        if receipt_state.get(key) != candidate_value:
            raise SecurityIdentityPublishError(
                f"staging receipt candidate_state mismatch for {key}"
            )
    if receipt.get("remaining_acquisition_queue_count") != len(rebuilt_queue):
        raise SecurityIdentityPublishError(
            "staging receipt remaining queue count mismatch"
        )

    progress = _validate_monotonic_progress(current, candidate)
    return {
        "schema_version": SCHEMA_VERSION,
        "candidate_manifest_sha256": candidate_sha,
        "staging_receipt_sha256": _sha256_path(receipt_path),
        "current_manifest_sha256": _sha256_path(current_manifest_path),
        "candidate_state": {
            "event_date_identity_verified_count": event_verified,
            "baseline_identity_verified_count": baseline_verified,
            "total_identity_verified_count": event_verified + baseline_verified,
            "baseline_identity_unverified_count": unresolved,
            "required_symbol_date_count": required,
            "ready_for_non_synthetic_market_join": bool(
                state.get("ready_for_non_synthetic_market_join")
            ),
        },
        "progress": progress,
        "candidate_manifest_text": candidate_text,
        "remaining_queue_text": queue_text,
        "remaining_summary_text": summary_text,
    }


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp-security-identity-publish")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def promote_staged_bundle(
    *,
    staged_dir: Path,
    approve_candidate_sha256: str,
    current_manifest_path: Path = DEFAULT_CANONICAL_MANIFEST,
    canonical_queue_path: Path = DEFAULT_CANONICAL_QUEUE,
    canonical_summary_path: Path = DEFAULT_CANONICAL_SUMMARY,
    publication_receipt_path: Path = DEFAULT_PUBLICATION_RECEIPT,
    events_path: Path = gate.DEFAULT_EVENTS,
    requirements_path: Path = gate.DEFAULT_REQUIREMENTS,
    listing_path: Path = gate.DEFAULT_LISTING,
) -> dict:
    verification = verify_staged_bundle(
        staged_dir=staged_dir,
        current_manifest_path=current_manifest_path,
        events_path=events_path,
        requirements_path=requirements_path,
        listing_path=listing_path,
    )
    expected = verification["candidate_manifest_sha256"]
    if approve_candidate_sha256.strip().lower() != expected:
        raise SecurityIdentityPublishError(
            "approve_candidate_sha256 does not match the verified candidate manifest"
        )

    publication_receipt = {
        "schema_version": SCHEMA_VERSION,
        "purpose": (
            "Receipt for explicit canonical promotion of a verified stable-ID staging bundle."
        ),
        "research_use_only": True,
        "canonical_write_performed": True,
        "identity_promoted": True,
        "market_data_coverage_promoted": False,
        "previous_manifest_sha256": verification["current_manifest_sha256"],
        "candidate_manifest_sha256": expected,
        "staging_receipt_sha256": verification["staging_receipt_sha256"],
        "candidate_state": verification["candidate_state"],
        "progress": verification["progress"],
    }
    publication_receipt_text = (
        json.dumps(publication_receipt, indent=2, sort_keys=True) + "\n"
    )

    _atomic_write(current_manifest_path, verification["candidate_manifest_text"])
    _atomic_write(canonical_queue_path, verification["remaining_queue_text"])
    _atomic_write(canonical_summary_path, verification["remaining_summary_text"])
    _atomic_write(publication_receipt_path, publication_receipt_text)
    return publication_receipt


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Verify a stable-ID staging bundle and optionally promote it to canonical "
            "identity outputs only with an exact candidate SHA approval."
        )
    )
    parser.add_argument("--staged-dir", type=Path, required=True)
    parser.add_argument("--current-manifest", type=Path, default=DEFAULT_CANONICAL_MANIFEST)
    parser.add_argument("--queue-output", type=Path, default=DEFAULT_CANONICAL_QUEUE)
    parser.add_argument("--summary-output", type=Path, default=DEFAULT_CANONICAL_SUMMARY)
    parser.add_argument(
        "--publication-receipt",
        type=Path,
        default=DEFAULT_PUBLICATION_RECEIPT,
    )
    parser.add_argument(
        "--approve-candidate-sha256",
        help=(
            "Exact verified candidate manifest SHA-256. Required with --promote; "
            "this prevents accidental or stale promotion."
        ),
    )
    parser.add_argument("--promote", action="store_true")
    args = parser.parse_args()

    if args.promote:
        if not args.approve_candidate_sha256:
            raise SecurityIdentityPublishError(
                "--approve-candidate-sha256 is required with --promote"
            )
        receipt = promote_staged_bundle(
            staged_dir=args.staged_dir,
            approve_candidate_sha256=args.approve_candidate_sha256,
            current_manifest_path=args.current_manifest,
            canonical_queue_path=args.queue_output,
            canonical_summary_path=args.summary_output,
            publication_receipt_path=args.publication_receipt,
        )
        print(json.dumps(receipt, indent=2, sort_keys=True))
        return 0

    verification = verify_staged_bundle(
        staged_dir=args.staged_dir,
        current_manifest_path=args.current_manifest,
    )
    print(
        json.dumps(
            {
                "verified": True,
                "candidate_manifest_sha256": verification[
                    "candidate_manifest_sha256"
                ],
                "candidate_state": verification["candidate_state"],
                "progress": verification["progress"],
                "canonical_write_performed": False,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
