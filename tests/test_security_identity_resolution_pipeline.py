from __future__ import annotations

import copy
import csv
import io
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import security_identity_gate as identity_gate
import security_identity_resolution_pipeline as pipeline


def _baseline():
    return identity_gate.build_manifest()


def _evidence_row(event: dict, trade_date: str, *, suffix: str = "") -> dict[str, str]:
    return {
        "evidence_id": f"PIPE-{event['permno']}-{trade_date}{suffix}",
        "permno": event["permno"],
        "historical_symbol": event["historical_symbol"],
        "market_identifier": event["historical_symbol"],
        "valid_from": trade_date,
        "valid_through": trade_date,
        "evidence_lane": "LICENSED_STABLE_ID_MASTER",
        "source_reference": "authorized://test/stable-id-master",
        "authorization_reference": "TEST_AUTHORIZATION",
        "research_use_only": "1",
    }


def test_one_authorized_date_makes_truthful_partial_progress():
    baseline = _baseline()
    event = next(row for row in baseline["events"] if row["unverified_required_dates"])
    trade_date = event["unverified_required_dates"][0]

    manifest_text, queue_text, summary_text, receipt_text = pipeline.build_resolution(
        [_evidence_row(event, trade_date)],
        evidence_receipts=[{
            "name": "one.csv",
            "size_bytes": 1,
            "sha256": "a" * 64,
            "row_count": 1,
        }],
    )

    manifest = json.loads(manifest_text)
    summary = json.loads(summary_text)
    receipt = json.loads(receipt_text)
    queue = list(csv.DictReader(io.StringIO(queue_text)))

    assert manifest["state"]["event_date_identity_verified_count"] == 174
    assert manifest["state"]["baseline_identity_verified_count"] == 1
    assert manifest["state"]["baseline_identity_unverified_count"] == 3653
    assert manifest["state"]["total_identity_verified_count"] == 175
    assert manifest["state"]["ready_for_non_synthetic_market_join"] is False
    assert len(queue) == 3653
    assert summary["state"]["unique_permno_date_requests"] == 3653
    assert receipt["after"]["total_verified"] == 175
    assert receipt["after"]["remaining_acquisition_requests"] == 3653


def test_complete_synthetic_evidence_reaches_3828_and_empty_terminal_queue():
    baseline = _baseline()
    evidence = [
        _evidence_row(event, trade_date)
        for event in baseline["events"]
        for trade_date in event["unverified_required_dates"]
    ]

    manifest_text, queue_text, summary_text, receipt_text = pipeline.build_resolution(
        evidence,
        evidence_receipts=[{
            "name": "complete.csv",
            "size_bytes": len(evidence),
            "sha256": "b" * 64,
            "row_count": len(evidence),
        }],
    )

    manifest = json.loads(manifest_text)
    summary = json.loads(summary_text)
    receipt = json.loads(receipt_text)

    assert len(evidence) == 3654
    assert manifest["state"]["event_date_identity_verified_count"] == 174
    assert manifest["state"]["baseline_identity_verified_count"] == 3654
    assert manifest["state"]["baseline_identity_unverified_count"] == 0
    assert manifest["state"]["total_identity_verified_count"] == 3828
    assert manifest["state"]["ready_for_non_synthetic_market_join"] is True
    assert list(csv.DictReader(io.StringIO(queue_text))) == []
    assert summary["state"]["ready_for_non_synthetic_market_join"] is True
    assert receipt["after"]["total_verified"] == 3828
    assert receipt["after"]["remaining_acquisition_requests"] == 0


def test_conflicting_duplicate_evidence_id_fails_closed(tmp_path: Path):
    baseline = _baseline()
    event = next(row for row in baseline["events"] if row["unverified_required_dates"])
    trade_date = event["unverified_required_dates"][0]
    first = _evidence_row(event, trade_date)
    second = copy.deepcopy(first)
    second["market_identifier"] = "CONFLICT"

    fields = list(first)
    paths = []
    for index, row in enumerate((first, second)):
        path = tmp_path / f"evidence-{index}.csv"
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerow(row)
        paths.append(path)

    with pytest.raises(
        pipeline.IdentityResolutionPipelineError,
        match="conflicting duplicate evidence_id",
    ):
        pipeline.merge_evidence(paths)


def test_resolution_writer_is_candidate_only(tmp_path: Path):
    baseline = _baseline()
    event = next(row for row in baseline["events"] if row["unverified_required_dates"])
    trade_date = event["unverified_required_dates"][0]
    outputs = pipeline.build_resolution([_evidence_row(event, trade_date)])

    pipeline.write_resolution(
        tmp_path,
        manifest_text=outputs[0],
        queue_text=outputs[1],
        summary_text=outputs[2],
        receipt_text=outputs[3],
    )

    assert {path.name for path in tmp_path.iterdir()} == {
        "security_identity_manifest.json",
        "security_identity_acquisition_queue.csv",
        "security_identity_acquisition_summary.json",
        "security_identity_resolution_receipt.json",
    }
