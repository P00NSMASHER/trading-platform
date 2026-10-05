from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import security_identity_evidence_stager as stager
import security_identity_gate as gate
import security_identity_publisher as publisher


def _current():
    return (
        gate._read_csv(ROOT / gate.DEFAULT_EVENTS),
        gate._read_csv(ROOT / gate.DEFAULT_REQUIREMENTS),
        gate._read_csv(ROOT / gate.DEFAULT_LISTING),
    )


def _evidence(
    *,
    evidence_id: str,
    permno: str,
    symbol: str,
    trade_date: str,
    market_identifier: str | None = None,
) -> dict[str, str]:
    return {
        "evidence_id": evidence_id,
        "permno": permno,
        "historical_symbol": symbol,
        "market_identifier": market_identifier or symbol,
        "valid_from": trade_date,
        "valid_through": trade_date,
        "evidence_lane": "LICENSED_STABLE_ID_MASTER",
        "source_reference": "authorized://stable-id-master/test",
        "authorization_reference": "TEST_AUTHORIZATION",
        "research_use_only": "1",
    }


def _write_stage(tmp_path: Path, evidence_rows: list[dict[str, str]]) -> Path:
    events, requirements, listings = _current()
    result = stager.build_staging_from_rows(
        events=events,
        requirements=requirements,
        listings=listings,
        evidence_rows=evidence_rows,
        source_sha256={
            "historical_events": publisher._sha256_path(ROOT / gate.DEFAULT_EVENTS),
            "symbol_date_requirements": publisher._sha256_path(
                ROOT / gate.DEFAULT_REQUIREMENTS
            ),
            "event_date_listing_evidence": publisher._sha256_path(
                ROOT / gate.DEFAULT_LISTING
            ),
        },
    )
    staged = tmp_path / "stage"
    stager.write_staging(result, staged)
    return staged


def test_staged_bundle_verifies_and_reports_monotonic_progress(tmp_path: Path):
    events, requirements, listings = _current()
    baseline = gate.build_manifest_from_rows(events, requirements, listings)
    event = next(row for row in baseline["events"] if row["unverified_required_dates"])
    trade_date = event["unverified_required_dates"][0]
    staged = _write_stage(
        tmp_path,
        [
            _evidence(
                evidence_id="ONE",
                permno=event["permno"],
                symbol=event["historical_symbol"],
                trade_date=trade_date,
            )
        ],
    )

    verification = publisher.verify_staged_bundle(
        staged_dir=staged,
        current_manifest_path=ROOT / gate.DEFAULT_OUTPUT,
        events_path=ROOT / gate.DEFAULT_EVENTS,
        requirements_path=ROOT / gate.DEFAULT_REQUIREMENTS,
        listing_path=ROOT / gate.DEFAULT_LISTING,
    )

    assert verification["candidate_state"]["baseline_identity_verified_count"] == 1
    assert verification["candidate_state"]["baseline_identity_unverified_count"] == 3653
    assert verification["progress"]["newly_verified_baseline_dates"] == 1
    assert verification["progress"]["previous_unresolved"] == 3654
    assert verification["progress"]["candidate_unresolved"] == 3653


def test_tampered_candidate_manifest_is_rejected_by_receipt_hash(tmp_path: Path):
    events, requirements, listings = _current()
    baseline = gate.build_manifest_from_rows(events, requirements, listings)
    event = next(row for row in baseline["events"] if row["unverified_required_dates"])
    trade_date = event["unverified_required_dates"][0]
    staged = _write_stage(
        tmp_path,
        [
            _evidence(
                evidence_id="ONE",
                permno=event["permno"],
                symbol=event["historical_symbol"],
                trade_date=trade_date,
            )
        ],
    )
    candidate = staged / stager.MANIFEST_NAME
    payload = json.loads(candidate.read_text(encoding="utf-8"))
    payload["state"]["baseline_identity_unverified_count"] = 999
    candidate.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(publisher.SecurityIdentityPublishError, match="sha256"):
        publisher.verify_staged_bundle(
            staged_dir=staged,
            current_manifest_path=ROOT / gate.DEFAULT_OUTPUT,
            events_path=ROOT / gate.DEFAULT_EVENTS,
            requirements_path=ROOT / gate.DEFAULT_REQUIREMENTS,
            listing_path=ROOT / gate.DEFAULT_LISTING,
        )


def test_approval_hash_must_match_exact_verified_candidate(tmp_path: Path):
    events, requirements, listings = _current()
    baseline = gate.build_manifest_from_rows(events, requirements, listings)
    event = next(row for row in baseline["events"] if row["unverified_required_dates"])
    trade_date = event["unverified_required_dates"][0]
    staged = _write_stage(
        tmp_path,
        [
            _evidence(
                evidence_id="ONE",
                permno=event["permno"],
                symbol=event["historical_symbol"],
                trade_date=trade_date,
            )
        ],
    )
    current_copy = tmp_path / "current.json"
    current_copy.write_text(
        (ROOT / gate.DEFAULT_OUTPUT).read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    with pytest.raises(publisher.SecurityIdentityPublishError, match="approve_candidate_sha256"):
        publisher.promote_staged_bundle(
            staged_dir=staged,
            approve_candidate_sha256="0" * 64,
            current_manifest_path=current_copy,
            canonical_queue_path=tmp_path / "queue.csv",
            canonical_summary_path=tmp_path / "summary.json",
            publication_receipt_path=tmp_path / "receipt.json",
            events_path=ROOT / gate.DEFAULT_EVENTS,
            requirements_path=ROOT / gate.DEFAULT_REQUIREMENTS,
            listing_path=ROOT / gate.DEFAULT_LISTING,
        )


def test_partial_candidate_can_be_promoted_only_after_exact_verification(tmp_path: Path):
    events, requirements, listings = _current()
    baseline = gate.build_manifest_from_rows(events, requirements, listings)
    event = next(row for row in baseline["events"] if row["unverified_required_dates"])
    trade_date = event["unverified_required_dates"][0]
    staged = _write_stage(
        tmp_path,
        [
            _evidence(
                evidence_id="ONE",
                permno=event["permno"],
                symbol=event["historical_symbol"],
                trade_date=trade_date,
            )
        ],
    )

    current_copy = tmp_path / "canonical" / "manifest.json"
    current_copy.parent.mkdir(parents=True)
    current_copy.write_text(
        (ROOT / gate.DEFAULT_OUTPUT).read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    verification = publisher.verify_staged_bundle(
        staged_dir=staged,
        current_manifest_path=current_copy,
        events_path=ROOT / gate.DEFAULT_EVENTS,
        requirements_path=ROOT / gate.DEFAULT_REQUIREMENTS,
        listing_path=ROOT / gate.DEFAULT_LISTING,
    )
    queue_path = tmp_path / "canonical" / "queue.csv"
    summary_path = tmp_path / "canonical" / "summary.json"
    receipt_path = tmp_path / "canonical" / "publication.json"

    receipt = publisher.promote_staged_bundle(
        staged_dir=staged,
        approve_candidate_sha256=verification["candidate_manifest_sha256"],
        current_manifest_path=current_copy,
        canonical_queue_path=queue_path,
        canonical_summary_path=summary_path,
        publication_receipt_path=receipt_path,
        events_path=ROOT / gate.DEFAULT_EVENTS,
        requirements_path=ROOT / gate.DEFAULT_REQUIREMENTS,
        listing_path=ROOT / gate.DEFAULT_LISTING,
    )

    promoted = json.loads(current_copy.read_text(encoding="utf-8"))
    assert promoted["state"]["baseline_identity_verified_count"] == 1
    assert promoted["state"]["baseline_identity_unverified_count"] == 3653
    assert len(queue_path.read_text(encoding="utf-8").splitlines()) == 3654
    assert json.loads(summary_path.read_text(encoding="utf-8"))["state"][
        "unique_permno_date_requests"
    ] == 3653
    assert receipt["canonical_write_performed"] is True
    assert receipt["identity_promoted"] is True
    assert receipt["market_data_coverage_promoted"] is False
    assert receipt_path.exists()


def test_candidate_regression_against_partially_promoted_manifest_is_rejected(tmp_path: Path):
    events, requirements, listings = _current()
    baseline = gate.build_manifest_from_rows(events, requirements, listings)
    event = next(row for row in baseline["events"] if len(row["unverified_required_dates"]) >= 2)
    first_date, second_date = event["unverified_required_dates"][:2]

    current_partial = gate.build_manifest_from_rows(
        events,
        requirements,
        listings,
        identity_evidence=[
            _evidence(
                evidence_id="CURRENT",
                permno=event["permno"],
                symbol=event["historical_symbol"],
                trade_date=first_date,
            )
        ],
    )
    current_path = tmp_path / "current-partial.json"
    current_path.write_text(gate.render_manifest(current_partial), encoding="utf-8")

    staged = _write_stage(
        tmp_path,
        [
            _evidence(
                evidence_id="NEW-ONLY",
                permno=event["permno"],
                symbol=event["historical_symbol"],
                trade_date=second_date,
            )
        ],
    )

    with pytest.raises(publisher.SecurityIdentityPublishError, match="regresses verified"):
        publisher.verify_staged_bundle(
            staged_dir=staged,
            current_manifest_path=current_path,
            events_path=ROOT / gate.DEFAULT_EVENTS,
            requirements_path=ROOT / gate.DEFAULT_REQUIREMENTS,
            listing_path=ROOT / gate.DEFAULT_LISTING,
        )


def test_embedded_candidate_evidence_reconstructs_exactly(tmp_path: Path):
    events, requirements, listings = _current()
    baseline = gate.build_manifest_from_rows(events, requirements, listings)
    event = next(row for row in baseline["events"] if row["unverified_required_dates"])
    trade_date = event["unverified_required_dates"][0]
    staged = _write_stage(
        tmp_path,
        [
            _evidence(
                evidence_id="RIC-EVIDENCE",
                permno=event["permno"],
                symbol=event["historical_symbol"],
                trade_date=trade_date,
                market_identifier=event["historical_symbol"] + ".O",
            )
        ],
    )
    candidate = json.loads(
        (staged / stager.MANIFEST_NAME).read_text(encoding="utf-8")
    )
    rows = publisher.evidence_rows_from_manifest(candidate)

    assert len(rows) == 1
    assert rows[0]["evidence_id"] == "RIC-EVIDENCE"
    assert rows[0]["market_identifier"].endswith(".O")

def test_publisher_rejects_staging_built_from_stale_canonical_manifest(tmp_path: Path):
    events, requirements, listings = _current()
    baseline = gate.build_manifest_from_rows(events, requirements, listings)
    event = next(row for row in baseline["events"] if row["unverified_required_dates"])
    trade_date = event["unverified_required_dates"][0]
    result = stager.build_staging_from_rows(
        events=events,
        requirements=requirements,
        listings=listings,
        evidence_rows=[
            _evidence(
                evidence_id="ONE",
                permno=event["permno"],
                symbol=event["historical_symbol"],
                trade_date=trade_date,
            )
        ],
        source_sha256={
            "historical_events": publisher._sha256_path(ROOT / gate.DEFAULT_EVENTS),
            "symbol_date_requirements": publisher._sha256_path(
                ROOT / gate.DEFAULT_REQUIREMENTS
            ),
            "event_date_listing_evidence": publisher._sha256_path(
                ROOT / gate.DEFAULT_LISTING
            ),
            "prior_canonical_identity_manifest": "0" * 64,
        },
    )
    staged = tmp_path / "stale-stage"
    stager.write_staging(result, staged)

    with pytest.raises(publisher.SecurityIdentityPublishError, match="stale canonical"):
        publisher.verify_staged_bundle(
            staged_dir=staged,
            current_manifest_path=ROOT / gate.DEFAULT_OUTPUT,
            events_path=ROOT / gate.DEFAULT_EVENTS,
            requirements_path=ROOT / gate.DEFAULT_REQUIREMENTS,
            listing_path=ROOT / gate.DEFAULT_LISTING,
        )

