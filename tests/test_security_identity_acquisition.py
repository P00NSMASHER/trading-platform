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

import security_identity_acquisition as sia


IDENTITY = ROOT / sia.DEFAULT_IDENTITY
QUEUE = ROOT / sia.DEFAULT_QUEUE
SUMMARY = ROOT / sia.DEFAULT_SUMMARY


def test_committed_acquisition_outputs_reproduce_byte_for_byte():
    queue_text, summary_text = sia.build_from_path(IDENTITY)
    assert queue_text == QUEUE.read_text(encoding="utf-8")
    assert summary_text == SUMMARY.read_text(encoding="utf-8")


def test_current_acquisition_state_is_exact_and_fail_closed():
    summary = json.loads(SUMMARY.read_text(encoding="utf-8"))
    state = summary["state"]
    assert state["raw_unverified_event_date_instances"] == 3654
    assert state["unique_permno_date_requests"] == 3654
    assert state["duplicate_request_instances_removed"] == 0
    assert state["unique_permno_count"] == 146
    assert state["ready_for_non_synthetic_market_join"] is False
    counts = [row["request_count"] for row in summary["securities"]]
    assert min(counts) == 21
    assert max(counts) == 84


def test_queue_has_unique_permno_date_and_request_id():
    rows = list(csv.DictReader(io.StringIO(QUEUE.read_text(encoding="utf-8"))))
    assert len(rows) == 3654
    assert len({(row["permno"], row["trade_date"]) for row in rows}) == 3654
    assert len({row["request_id"] for row in rows}) == 3654
    for row in rows:
        assert row["request_id"] == sia._request_id(row["permno"], row["trade_date"])
        assert row["status"] == "PENDING_STABLE_ID_EVIDENCE"
        assert row["research_use_only"] == "1"


def test_public_corporate_action_lane_cannot_close_request_alone():
    assert sia.ACQUISITION_LANES["PUBLIC_CORPORATE_ACTION_CORROBORATION"]["can_close_request"] is False
    assert sia.ACQUISITION_LANES["LICENSED_STABLE_ID_MASTER"]["can_close_request"] is True
    assert sia.ACQUISITION_LANES["AUTHORIZED_MARKET_SECURITY_MASTER"]["can_close_request"] is True


def test_conflicting_symbol_for_same_permno_fails_closed():
    identity = sia.load_identity(IDENTITY)
    bad = copy.deepcopy(identity)
    target = bad["events"][0]["permno"]
    donor = next(event for event in bad["events"][1:] if event["permno"] != target)
    donor["permno"] = target
    with pytest.raises(sia.IdentityAcquisitionError, match="conflicting GVKEY/symbol"):
        sia.build_acquisition(bad)


def test_unverified_state_count_mismatch_fails_closed():
    identity = sia.load_identity(IDENTITY)
    bad = copy.deepcopy(identity)
    bad["state"]["baseline_identity_unverified_count"] += 1
    with pytest.raises(sia.IdentityAcquisitionError, match="unverified count mismatch"):
        sia.build_acquisition(bad)


def test_same_permno_date_can_merge_event_ids_only_when_identity_matches():
    identity = sia.load_identity(IDENTITY)
    bad = copy.deepcopy(identity)
    event = bad["events"][0]
    clone = copy.deepcopy(event)
    clone["event_id"] = event["event_id"] + "-CLONE"
    clone["unverified_required_dates"] = [event["unverified_required_dates"][0]]
    bad["events"].append(clone)
    bad["state"]["baseline_identity_unverified_count"] += 1
    queue, summary = sia.build_acquisition(bad)
    matching = [
        row for row in queue
        if row["permno"] == event["permno"]
        and row["trade_date"] == event["unverified_required_dates"][0]
    ]
    assert len(matching) == 1
    assert matching[0]["event_ids"].split(";") == sorted([
        event["event_id"],
        clone["event_id"],
    ])
    assert summary["state"]["duplicate_request_instances_removed"] == 1


def test_prohibited_shortcuts_include_no_ticker_or_alias_inference():
    summary = json.loads(SUMMARY.read_text(encoding="utf-8"))
    blocked = set(summary["completion_contract"]["prohibited_shortcuts"])
    assert "current_ticker_substitution" in blocked
    assert "symbol_only_join_without_stable_id" in blocked
    assert "inferred_rename_or_merger_alias" in blocked

def test_complete_identity_manifest_emits_empty_queue_and_ready_summary():
    identity = sia.load_identity(IDENTITY)
    complete = copy.deepcopy(identity)
    for event in complete["events"]:
        event["verified_required_dates"] = list(event["required_dates"])
        event["unverified_required_dates"] = []
        event["identity_status"] = "FULL_REQUIRED_DATE_IDENTITY_VERIFIED"
    complete["state"]["baseline_identity_unverified_count"] = 0
    complete["state"]["baseline_identity_verified_count"] = 3654
    complete["state"]["total_identity_verified_count"] = 3828
    complete["state"]["ready_for_non_synthetic_market_join"] = True

    queue, summary = sia.build_acquisition(complete)

    assert queue == []
    assert summary["state"]["raw_unverified_event_date_instances"] == 0
    assert summary["state"]["unique_permno_date_requests"] == 0
    assert summary["state"]["unique_permno_count"] == 0
    assert summary["state"]["ready_for_non_synthetic_market_join"] is True
    assert summary["state"]["reasons"] == []
    rendered = sia.render_queue(queue)
    assert rendered.splitlines() == [",".join(sia.QUEUE_FIELDS)]


def test_identity_readiness_must_match_unresolved_queue_state():
    identity = sia.load_identity(IDENTITY)
    bad = copy.deepcopy(identity)
    bad["state"]["ready_for_non_synthetic_market_join"] = True

    with pytest.raises(sia.IdentityAcquisitionError, match="readiness disagrees"):
        sia.build_acquisition(bad)

